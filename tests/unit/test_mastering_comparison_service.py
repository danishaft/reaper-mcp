import hashlib
import math
import shutil
import struct
import wave
from pathlib import Path

import pytest

from reaper_mcp.errors import ErrorCode
from reaper_mcp.models.audio_measurement import AudioMeasurementRequest
from reaper_mcp.models.mastering import MasteringCandidate
from reaper_mcp.services.audio_measurement_backend import FfmpegEbur128Backend
from reaper_mcp.services.mastering_audition_service import (
    AuditionCopyResult,
    FfmpegAuditionBackend,
    MasteringAuditionService,
)
from reaper_mcp.services.mastering_comparison_service import (
    MasteringComparisonService,
)


def candidate(
    candidate_id: str,
    path: Path,
    integrated_lufs: float,
    true_peak_dbtp: float,
) -> dict:
    rendered_sha256 = (
        hashlib.sha256(path.read_bytes()).hexdigest()
        if path.is_file()
        else ("e" if candidate_id.endswith("a" * 24) else "f") * 64
    )
    return MasteringCandidate.model_validate(
        {
            "candidate_id": candidate_id,
            "label": candidate_id,
            "plan_id": "mp_" + "a" * 24,
            "approval_hash": "b" * 64,
            "source_sha256": "c" * 64,
            "master_chain_sha256": "d" * 64,
            "render": {
                "scope": "project",
                "status": "completed",
                "primary_output_path": str(path),
                "output_files": [
                    {"path": str(path), "size_bytes": 2048, "exists": True}
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
            "rendered_sha256": rendered_sha256,
            "measurement": {
                "path": str(path),
                "source_sha256": rendered_sha256,
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
                "dynamics": {
                    "peak_to_loudness_ratio_db": (true_peak_dbtp - integrated_lufs)
                },
                "stereo": {"channel_layout": "stereo"},
                "quality": {
                    "complete_loudness_metrics": True,
                    "sample_peak_available": True,
                    "true_peak_available": True,
                    "loudness_range_stable": True,
                    "source_integrity_verified": True,
                },
                "technical": {
                    "codec": "pcm_s24le",
                    "sample_rate_hz": 48_000,
                    "channel_layout": "stereo",
                    "sample_format": "s32",
                    "effective_bit_depth": 24,
                },
            },
        }
    ).model_dump(mode="json")


class FakeAuditionBackend:
    def __init__(self) -> None:
        self.gains: list[float] = []

    async def create_copy(
        self,
        source_path: Path,
        output_path: Path,
        gain_db: float,
        *,
        start_seconds: float,
        duration_seconds: float | None,
    ) -> AuditionCopyResult:
        self.gains.append(gain_db)
        output_path.write_bytes(b"audition:" + source_path.read_bytes())
        return AuditionCopyResult(
            backend_name="test_audition",
            executable_path=Path("/usr/bin/test-ffmpeg"),
            version="1.0",
        )


class FakeIsolatedProjectService:
    def validate_project_destination(self, project_path: Path) -> None:
        return None

    async def create_media_sequence_project(
        self,
        media_paths: list[Path],
        project_path: Path,
    ) -> dict:
        project_path.write_text(
            "<REAPER_PROJECT\n" + "\n".join(str(path) for path in media_paths) + "\n>",
            encoding="utf-8",
        )
        return {
            "ok": True,
            "project": {
                "project_path": str(project_path),
                "project_sha256": hashlib.sha256(project_path.read_bytes()).hexdigest(),
                "size_bytes": project_path.stat().st_size,
                "media_paths": [str(path) for path in media_paths],
                "reaper_executable": "/usr/bin/test-reaper",
            },
            "warnings": [],
        }


async def test_comparison_attenuates_louder_candidate_only(
    tmp_path: Path,
) -> None:
    candidate_a = candidate(
        "mc_" + "a" * 24,
        tmp_path / "a.wav",
        -10.0,
        -0.8,
    )
    candidate_b = candidate(
        "mc_" + "b" * 24,
        tmp_path / "b.wav",
        -14.0,
        -1.2,
    )

    result = await MasteringComparisonService().compare_candidates(
        candidate_a,
        candidate_b,
    )

    assert result["ok"] is True
    comparison = result["comparison"]
    assert comparison["method"] == "integrated_lufs_attenuation_only"
    assert comparison["reference_lufs"] == -14.0
    assert comparison["entries"][0]["audition_gain_db"] == -4.0
    assert comparison["entries"][0]["predicted_true_peak_dbtp"] == -4.8
    assert comparison["entries"][1]["audition_gain_db"] == 0.0


async def test_candidate_approval_requires_listening_confirmation(
    tmp_path: Path,
) -> None:
    candidate_a = candidate(
        "mc_" + "a" * 24,
        tmp_path / "a.wav",
        -10.0,
        -0.8,
    )
    candidate_b = candidate(
        "mc_" + "b" * 24,
        tmp_path / "b.wav",
        -14.0,
        -1.2,
    )
    service = MasteringComparisonService()
    compared = await service.compare_candidates(candidate_a, candidate_b)

    rejected = await service.approve_candidate(
        candidate_a,
        compared["comparison"],
        "Mastering Engineer",
        ["Candidate A keeps the vocal clearer."],
        False,
    )
    approved = await service.approve_candidate(
        candidate_a,
        compared["comparison"],
        "Mastering Engineer",
        ["Candidate A keeps the vocal clearer."],
        True,
    )

    assert rejected["ok"] is False
    assert rejected["error"]["code"] == ErrorCode.MASTERING_CANDIDATE_INVALID
    assert approved["ok"] is True
    assert approved["approval"]["state"] == "approved"
    assert approved["approval"]["listening_confirmed"] is True


async def test_audition_prepares_isolated_gain_matched_sequence(
    tmp_path: Path,
) -> None:
    path_a = tmp_path / "a.wav"
    path_b = tmp_path / "b.wav"
    path_a.write_bytes(b"candidate-a")
    path_b.write_bytes(b"candidate-b")
    candidate_a = candidate("mc_" + "a" * 24, path_a, -10.0, -0.8)
    candidate_b = candidate("mc_" + "b" * 24, path_b, -14.0, -1.2)
    comparison_service = MasteringComparisonService()
    compared = await comparison_service.compare_candidates(
        candidate_a,
        candidate_b,
    )
    backend = FakeAuditionBackend()
    project_path = tmp_path / "audition.rpp"

    result = await MasteringAuditionService(
        backend,
        FakeIsolatedProjectService(),
        allowed_source_roots=[tmp_path],
    ).prepare(
        candidate_a,
        candidate_b,
        compared["comparison"],
        str(project_path),
        blind_labels=True,
    )

    assert result["ok"] is True
    assert backend.gains == [-4.0, 0.0]
    assert project_path.is_file()
    audition = result["audition"]
    assert audition["layout"] == "sequential_a_then_b"
    assert audition["interactive_project_untouched"] is True
    assert [asset["display_label"] for asset in audition["assets"]] == ["A", "B"]
    assert all(Path(asset["audition_path"]).is_file() for asset in audition["assets"])
    assert path_a.read_bytes() == b"candidate-a"
    assert path_b.read_bytes() == b"candidate-b"


async def test_audition_rejects_candidate_changed_after_comparison(
    tmp_path: Path,
) -> None:
    path_a = tmp_path / "a.wav"
    path_b = tmp_path / "b.wav"
    path_a.write_bytes(b"candidate-a")
    path_b.write_bytes(b"candidate-b")
    candidate_a = candidate("mc_" + "a" * 24, path_a, -10.0, -0.8)
    candidate_b = candidate("mc_" + "b" * 24, path_b, -14.0, -1.2)
    compared = await MasteringComparisonService().compare_candidates(
        candidate_a,
        candidate_b,
    )
    path_a.write_bytes(b"changed")

    result = await MasteringAuditionService(
        FakeAuditionBackend(),
        FakeIsolatedProjectService(),
        allowed_source_roots=[tmp_path],
    ).prepare(
        candidate_a,
        candidate_b,
        compared["comparison"],
        str(tmp_path / "audition.rpp"),
    )

    assert result["ok"] is False
    assert result["error"]["code"] == ErrorCode.MASTERING_SOURCE_CHANGED
    assert not (tmp_path / "audition.audition-assets").exists()


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg is not installed")
async def test_ffmpeg_audition_copy_applies_exact_gain_without_source_change(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "candidate.wav"
    output_path = tmp_path / "Audition-A.wav"
    sample_rate = 48_000
    with wave.open(str(source_path), "wb") as wav_file:
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
                for frame in range(sample_rate * 4)
            )
        )
    source_sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()

    backend_result = await FfmpegAuditionBackend(timeout_seconds=10.0).create_copy(
        source_path,
        output_path,
        -6.0,
        start_seconds=0.0,
        duration_seconds=None,
    )
    measured = await FfmpegEbur128Backend(timeout_seconds=10.0).measure(
        AudioMeasurementRequest(audio_path=output_path),
        hashlib.sha256(output_path.read_bytes()).hexdigest(),
    )

    assert backend_result.backend_name == "ffmpeg_gain_matched_float_wav"
    assert measured.technical.codec == "pcm_f32le"
    assert measured.peaks.sample_peak_dbfs == pytest.approx(-18.0, abs=0.2)
    assert hashlib.sha256(source_path.read_bytes()).hexdigest() == source_sha256
