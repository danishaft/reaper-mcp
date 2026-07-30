import hashlib
import math
import shutil
import struct
import wave
from pathlib import Path

import pytest

from reaper_mcp.errors import ErrorCode
from reaper_mcp.models.audio_measurement import (
    AudioMeasurementRequest,
    AudioMeasurementResult,
)
from reaper_mcp.models.mastering import (
    ApprovedMasteringCandidate,
    CodecPreviewSpecification,
    DeliveryBackendInfo,
    DeliverySpecification,
    MasteringCandidate,
)
from reaper_mcp.services.audio_measurement_backend import FfmpegEbur128Backend
from reaper_mcp.services.mastering_codec_service import (
    CodecBackendResult,
    FfmpegCodecPreviewBackend,
    MasteringCodecService,
)
from reaper_mcp.services.mastering_delivery_service import (
    FfmpegDeliveryBackend,
    MasteringDeliveryService,
    TranscodeResult,
)


def write_sine_wav(path: Path, *, duration_seconds: int = 1) -> None:
    sample_rate = 48_000
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(2)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(
            b"".join(
                struct.pack(
                    "<hh",
                    round(math.sin(2 * math.pi * 997 * frame / sample_rate) * 8192),
                    round(math.sin(2 * math.pi * 997 * frame / sample_rate) * 8192),
                )
                for frame in range(sample_rate * duration_seconds)
            )
        )


def measurement(
    path: Path,
    sha256: str,
    *,
    sample_rate_hz: int = 48_000,
    bit_depth: int = 24,
    integrated_lufs: float = -12.0,
    true_peak_dbtp: float = -1.0,
) -> AudioMeasurementResult:
    return AudioMeasurementResult.model_validate(
        {
            "path": path,
            "source_sha256": sha256,
            "standard": "ITU-R BS.1770-4 / EBU R128",
            "backend": {
                "name": "ffmpeg_ebur128",
                "executable_path": "/usr/bin/ffmpeg",
                "version": "6.1.1",
            },
            "bounds": {
                "start_seconds": 0.0,
                "measured_duration_seconds": 180.0,
            },
            "loudness": {
                "integrated_lufs": integrated_lufs,
                "momentary_max_lufs": integrated_lufs + 4.0,
                "short_term_max_lufs": integrated_lufs + 2.0,
                "loudness_range_lu": 6.0,
            },
            "peaks": {
                "sample_peak_dbfs": true_peak_dbtp - 0.2,
                "true_peak_dbtp": true_peak_dbtp,
            },
            "dynamics": {"peak_to_loudness_ratio_db": true_peak_dbtp - integrated_lufs},
            "stereo": {"channel_layout": "stereo"},
            "quality": {
                "complete_loudness_metrics": True,
                "sample_peak_available": True,
                "true_peak_available": True,
                "loudness_range_stable": True,
                "source_integrity_verified": True,
            },
            "technical": {
                "codec": f"pcm_s{bit_depth}le",
                "sample_rate_hz": sample_rate_hz,
                "channel_layout": "stereo",
                "sample_format": "s32" if bit_depth == 24 else f"s{bit_depth}",
                "effective_bit_depth": bit_depth,
            },
        }
    )


def approval(source_path: Path) -> ApprovedMasteringCandidate:
    source_sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()
    source_measurement = measurement(source_path, source_sha256)
    candidate = MasteringCandidate.model_validate(
        {
            "candidate_id": "mc_" + "a" * 24,
            "label": "Approved A",
            "plan_id": "mp_" + "b" * 24,
            "approval_hash": "c" * 64,
            "source_sha256": "d" * 64,
            "master_chain_sha256": "e" * 64,
            "render": {
                "scope": "project",
                "status": "completed",
                "primary_output_path": str(source_path),
                "output_files": [
                    {
                        "path": str(source_path),
                        "size_bytes": source_path.stat().st_size,
                        "exists": True,
                    }
                ],
                "output_file_count": 1,
                "transaction": {
                    "settings_restored": True,
                    "dirty_state_before": False,
                    "dirty_state_after": False,
                    "dirty_state_preserved": True,
                    "trace": [
                        {"stage": "render_external_started", "elapsed_ms": 0},
                        {"stage": "render_external_returned", "elapsed_ms": 1},
                        {"stage": "transaction_verified", "elapsed_ms": 2},
                    ],
                },
            },
            "rendered_sha256": source_sha256,
            "measurement": source_measurement,
        }
    )
    return ApprovedMasteringCandidate(
        approval_id="ca_" + "f" * 24,
        candidate=candidate,
        comparison_id="cmp_" + "1" * 24,
        approved_by="Mastering Engineer",
        judgment_notes=["Translation and vocal balance approved."],
        listening_confirmed=True,
    )


class FakeDeliveryBackend:
    def __init__(self) -> None:
        self.applied_dither: list[str] = []

    async def transcode(
        self,
        source_path: Path,
        output_path: Path,
        specification: DeliverySpecification,
        applied_dither: str,
    ) -> TranscodeResult:
        self.applied_dither.append(applied_dither)
        output_path.write_bytes(b"verified-delivery")
        return TranscodeResult(
            backend=DeliveryBackendInfo(
                name="test_delivery",
                executable_path="/usr/bin/test-ffmpeg",
                version="1.0",
            ),
            metadata={
                key.lower(): value for key, value in specification.metadata.items()
            },
        )


class FakeMeasurementService:
    def __init__(self, *, true_peak_dbtp: float = -1.0) -> None:
        self.true_peak_dbtp = true_peak_dbtp

    async def measure_file(self, path: str) -> dict:
        measured_path = Path(path)
        sha256 = hashlib.sha256(measured_path.read_bytes()).hexdigest()
        result = measurement(
            measured_path,
            sha256,
            sample_rate_hz=44_100,
            bit_depth=16,
            true_peak_dbtp=self.true_peak_dbtp,
        )
        return {"ok": True, "measurement": result.model_dump(mode="json")}


class FakeProgramAnalysisService:
    def __init__(
        self,
        *,
        clipping_detected: bool = False,
        maximum_absolute_dc_offset: float = 0.0001,
    ) -> None:
        self.clipping_detected = clipping_detected
        self.maximum_absolute_dc_offset = maximum_absolute_dc_offset

    async def analyze_file(self, path: str) -> dict:
        analyzed_path = Path(path)
        sha256 = hashlib.sha256(analyzed_path.read_bytes()).hexdigest()
        analysis = {
            "path": analyzed_path,
            "source_sha256": sha256,
            "backend": {
                "name": "test_program_analysis",
                "executable_path": "/usr/bin/test-ffmpeg",
                "version": "1.0",
            },
            "duration_seconds": 180.0,
            "sample_rate_hz": 44_100,
            "sample_count_per_channel": 7_938_000,
            "sample_peak_dbfs": -1.0,
            "full_range_rms_dbfs": -15.0,
            "maximum_absolute_dc_offset": self.maximum_absolute_dc_offset,
            "clipping_detected": self.clipping_detected,
            "bands": [
                {
                    "name": name,
                    "low_hz": low,
                    "high_hz": high,
                    "rms_dbfs": rms,
                    "balance_to_full_range_db": rms + 15.0,
                }
                for name, low, high, rms in [
                    ("low", 0.0, 200.0, -20.0),
                    ("lowmid", 200.0, 2_000.0, -17.0),
                    ("highmid", 2_000.0, 8_000.0, -22.0),
                    ("high", 8_000.0, None, -28.0),
                ]
            ],
            "silence": {
                "threshold_dbfs": -80.0,
                "minimum_duration_seconds": 0.1,
                "leading_silence_seconds": 0.0,
                "trailing_silence_seconds": 0.0,
                "total_silence_seconds": 0.0,
                "intervals": [],
            },
            "source_integrity_verified": True,
        }
        return {"ok": True, "analysis": analysis, "warnings": []}


class FakeCodecBackend:
    async def encode_decode(
        self,
        source_path: Path,
        encoded_path: Path,
        decoded_wav_path: Path,
        specification,
        *,
        sample_rate_hz: int,
    ) -> CodecBackendResult:
        encoded_path.write_bytes(b"lossy-bitstream")
        decoded_wav_path.write_bytes(b"decoded-preview")
        return CodecBackendResult(
            backend_name="test_codec",
            encoder_name=f"test-{specification.format}",
            executable_path=Path("/usr/bin/test-ffmpeg"),
            version="1.0",
        )


async def test_delivery_publishes_only_qc_passed_final_files(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "candidate.wav"
    source_path.write_bytes(b"approved-candidate")
    backend = FakeDeliveryBackend()
    service = MasteringDeliveryService(
        backend,
        FakeMeasurementService(),
        FakeProgramAnalysisService(),
        allowed_delivery_roots=[tmp_path],
    )
    output_path = tmp_path / "distribution.wav"
    manifest_path = tmp_path / "delivery.json"
    summary_path = tmp_path / "delivery.md"

    result = await service.deliver(
        approval(source_path).model_dump(mode="json"),
        [
            {
                "name": "Distribution WAV",
                "output_path": output_path,
                "sample_rate_hz": 44_100,
                "bit_depth": 16,
                "true_peak_ceiling_dbtp": -0.5,
                "metadata": {"artist": "The Artist"},
            }
        ],
        str(manifest_path),
        str(summary_path),
    )

    assert result["ok"] is True
    assert output_path.read_bytes() == b"verified-delivery"
    assert manifest_path.is_file()
    assert summary_path.is_file()
    assert backend.applied_dither == ["triangular"]
    artifact = result["manifest"]["artifacts"][0]
    assert artifact["path"] == str(output_path)
    assert artifact["measurement"]["path"] == str(output_path)
    assert artifact["qc_passed"] is True
    assert all(check["passed"] for check in artifact["qc_checks"])
    assert not list(tmp_path.glob(".*.tmp.wav"))


async def test_delivery_qc_failure_removes_every_partial_output(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "candidate.wav"
    source_path.write_bytes(b"approved-candidate")
    service = MasteringDeliveryService(
        FakeDeliveryBackend(),
        FakeMeasurementService(true_peak_dbtp=-0.1),
        FakeProgramAnalysisService(),
        allowed_delivery_roots=[tmp_path],
    )
    output_path = tmp_path / "distribution.wav"
    manifest_path = tmp_path / "delivery.json"
    summary_path = tmp_path / "delivery.md"

    result = await service.deliver(
        approval(source_path).model_dump(mode="json"),
        [
            {
                "name": "Distribution WAV",
                "output_path": output_path,
                "sample_rate_hz": 44_100,
                "bit_depth": 16,
                "true_peak_ceiling_dbtp": -0.5,
            }
        ],
        str(manifest_path),
        str(summary_path),
    )

    assert result["ok"] is False
    assert result["error"]["code"] == ErrorCode.DELIVERY_QC_FAILED
    assert not output_path.exists()
    assert not manifest_path.exists()
    assert not summary_path.exists()
    assert not list(tmp_path.glob(".*.tmp.wav"))


async def test_delivery_rejects_changed_approved_candidate(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "candidate.wav"
    source_path.write_bytes(b"approved-candidate")
    approved = approval(source_path)
    source_path.write_bytes(b"changed-after-approval")
    service = MasteringDeliveryService(
        FakeDeliveryBackend(),
        FakeMeasurementService(),
        FakeProgramAnalysisService(),
        allowed_delivery_roots=[tmp_path],
    )

    result = await service.deliver(
        approved.model_dump(mode="json"),
        [
            {
                "name": "Distribution WAV",
                "output_path": tmp_path / "distribution.wav",
                "sample_rate_hz": 44_100,
                "bit_depth": 16,
            }
        ],
        str(tmp_path / "delivery.json"),
        str(tmp_path / "delivery.md"),
    )

    assert result["ok"] is False
    assert result["error"]["code"] == ErrorCode.MASTERING_SOURCE_CHANGED


async def test_delivery_rejects_invalid_isrc_metadata(tmp_path: Path) -> None:
    source_path = tmp_path / "candidate.wav"
    source_path.write_bytes(b"approved-candidate")
    service = MasteringDeliveryService(
        FakeDeliveryBackend(),
        FakeMeasurementService(),
        FakeProgramAnalysisService(),
        allowed_delivery_roots=[tmp_path],
    )

    result = await service.deliver(
        approval(source_path).model_dump(mode="json"),
        [
            {
                "name": "Distribution WAV",
                "output_path": tmp_path / "distribution.wav",
                "sample_rate_hz": 48_000,
                "bit_depth": 24,
                "metadata": {"isrc": "not-an-isrc"},
            }
        ],
        str(tmp_path / "delivery.json"),
        str(tmp_path / "delivery.md"),
    )

    assert result["ok"] is False
    assert result["error"]["code"] == ErrorCode.INVALID_MASTERING_REQUEST


async def test_codec_preview_publishes_measured_encode_and_decode(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "candidate.wav"
    source_path.write_bytes(b"approved-candidate")
    encoded_path = tmp_path / "preview.mp3"
    decoded_path = tmp_path / "preview-decoded.wav"
    service = MasteringCodecService(
        FakeCodecBackend(),
        FakeMeasurementService(),
        FakeProgramAnalysisService(),
        allowed_preview_roots=[tmp_path],
    )

    result = await service.create_preview(
        approval(source_path).model_dump(mode="json"),
        {
            "format": "mp3",
            "encoded_path": encoded_path,
            "decoded_wav_path": decoded_path,
            "bitrate_kbps": 320,
        },
    )

    assert result["ok"] is True
    assert encoded_path.read_bytes() == b"lossy-bitstream"
    assert decoded_path.read_bytes() == b"decoded-preview"
    assert result["preview"]["state"] == "measured_preview"
    assert result["preview"]["encoder_name"] == "test-mp3"
    assert result["preview"]["measurement"]["path"] == str(decoded_path)
    assert source_path.read_bytes() == b"approved-candidate"


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg and FFprobe are required",
)
async def test_ffmpeg_delivery_backend_writes_real_pcm_and_metadata(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "source.wav"
    output_path = tmp_path / "distribution.wav"
    write_sine_wav(source_path)
    specification = DeliverySpecification(
        name="CD WAV",
        output_path=output_path,
        sample_rate_hz=44_100,
        bit_depth=16,
        metadata={"title": "Delivery Test"},
    )

    result = await FfmpegDeliveryBackend(timeout_seconds=10.0).transcode(
        source_path,
        output_path,
        specification,
        "triangular",
    )

    with wave.open(str(output_path), "rb") as wav_file:
        assert wav_file.getframerate() == 44_100
        assert wav_file.getsampwidth() == 2
        assert wav_file.getnchannels() == 2
    assert result.backend.name == "ffmpeg_pcm_wav"
    assert result.metadata["title"] == "Delivery Test"


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg and FFprobe are required",
)
@pytest.mark.parametrize(
    ("bit_depth", "expected_codec", "expected_effective_depth"),
    [
        (24, "pcm_s24le", 24),
        ("32_float", "pcm_f32le", 32),
    ],
)
async def test_ffmpeg_delivery_backend_writes_high_resolution_formats(
    tmp_path: Path,
    bit_depth,
    expected_codec: str,
    expected_effective_depth: int,
) -> None:
    source_path = tmp_path / "source.wav"
    output_path = tmp_path / f"master-{bit_depth}.wav"
    write_sine_wav(source_path, duration_seconds=4)
    specification = DeliverySpecification(
        name=f"{bit_depth} master",
        output_path=output_path,
        sample_rate_hz=48_000,
        bit_depth=bit_depth,
    )

    await FfmpegDeliveryBackend(timeout_seconds=10.0).transcode(
        source_path,
        output_path,
        specification,
        "none",
    )
    measured = await FfmpegEbur128Backend(timeout_seconds=10.0).measure(
        AudioMeasurementRequest(audio_path=output_path),
        hashlib.sha256(output_path.read_bytes()).hexdigest(),
    )

    assert measured.technical.codec == expected_codec
    assert measured.technical.effective_bit_depth == expected_effective_depth


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None,
    reason="FFmpeg is required",
)
@pytest.mark.parametrize(
    ("codec", "suffix", "bitrate", "expected_encoder"),
    [
        ("aac", ".m4a", 256, "aac"),
        ("mp3", ".mp3", 320, "libmp3lame"),
        ("opus", ".opus", 160, "libopus"),
    ],
)
async def test_ffmpeg_codec_backend_round_trips_real_preview(
    tmp_path: Path,
    codec: str,
    suffix: str,
    bitrate: int,
    expected_encoder: str,
) -> None:
    source_path = tmp_path / "source.wav"
    encoded_path = tmp_path / f"preview{suffix}"
    decoded_path = tmp_path / f"decoded-{codec}.wav"
    write_sine_wav(source_path, duration_seconds=4)
    specification = {
        "format": codec,
        "encoded_path": encoded_path,
        "decoded_wav_path": decoded_path,
        "bitrate_kbps": bitrate,
    }
    result = await FfmpegCodecPreviewBackend(timeout_seconds=10.0).encode_decode(
        source_path,
        encoded_path,
        decoded_path,
        CodecPreviewSpecification.model_validate(specification),
        sample_rate_hz=48_000,
    )
    measured = await FfmpegEbur128Backend(timeout_seconds=10.0).measure(
        AudioMeasurementRequest(audio_path=decoded_path),
        hashlib.sha256(decoded_path.read_bytes()).hexdigest(),
    )

    assert result.encoder_name == expected_encoder
    assert encoded_path.stat().st_size > 0
    assert measured.technical.codec == "pcm_f32le"
