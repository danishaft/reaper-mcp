import hashlib
import math
import shutil
import struct
import wave
from pathlib import Path

import pytest

from reaper_mcp.errors import ErrorCode
from reaper_mcp.models.audio_measurement import AudioMeasurementRequest
from reaper_mcp.models.mastering import (
    ApprovedMasteringCandidate,
    MasteringCandidate,
)
from reaper_mcp.services.audio_measurement_backend import FfmpegEbur128Backend
from reaper_mcp.services.mastering_album_backend import (
    AlbumAssetResult,
    FfmpegAlbumAssetBackend,
)
from reaper_mcp.services.mastering_album_service import MasteringAlbumService
from reaper_mcp.services.mastering_version_service import MasteringVersionService


def candidate_approval(
    path: Path,
    *,
    suffix: str,
    integrated_lufs: float,
    true_peak_dbtp: float,
) -> ApprovedMasteringCandidate:
    rendered_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    measurement = {
        "path": path,
        "source_sha256": rendered_sha256,
        "standard": "ITU-R BS.1770-4 / EBU R128",
        "backend": {
            "name": "ffmpeg_ebur128",
            "executable_path": "/usr/bin/ffmpeg",
            "version": "6.1.1",
        },
        "bounds": {
            "start_seconds": 0.0,
            "measured_duration_seconds": 10.0,
        },
        "loudness": {
            "integrated_lufs": integrated_lufs,
            "momentary_max_lufs": integrated_lufs + 4.0,
            "short_term_max_lufs": integrated_lufs + 2.0,
            "loudness_range_lu": 5.0,
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
            "codec": "pcm_s24le",
            "sample_rate_hz": 48_000,
            "channel_layout": "stereo",
            "sample_format": "s32",
            "effective_bit_depth": 24,
        },
    }
    candidate = MasteringCandidate.model_validate(
        {
            "candidate_id": "mc_" + suffix * 24,
            "label": f"Song {suffix.upper()}",
            "plan_id": "mp_" + suffix * 24,
            "approval_hash": suffix * 64,
            "source_sha256": ("d" if suffix != "d" else "e") * 64,
            "master_chain_sha256": ("e" if suffix != "e" else "f") * 64,
            "render": {
                "scope": "project",
                "status": "completed",
                "primary_output_path": str(path),
                "output_files": [
                    {
                        "path": str(path),
                        "size_bytes": path.stat().st_size,
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
            "rendered_sha256": rendered_sha256,
            "measurement": measurement,
        }
    )
    return ApprovedMasteringCandidate(
        approval_id="ca_" + suffix * 24,
        candidate=candidate,
        comparison_id="cmp_" + suffix * 24,
        approved_by="Song Mastering Engineer",
        judgment_notes=["Song master approved."],
        listening_confirmed=True,
    )


class FakeProgramAnalysisService:
    async def analyze_file(self, audio_path: str) -> dict:
        path = Path(audio_path)
        sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        offset = 0.0 if path.stem.endswith("1") else 2.0
        return {
            "ok": True,
            "analysis": {
                "path": path,
                "source_sha256": sha256,
                "backend": {
                    "name": "test_program",
                    "executable_path": "/usr/bin/test-ffmpeg",
                    "version": "1.0",
                },
                "duration_seconds": 10.0,
                "sample_rate_hz": 48_000,
                "sample_count_per_channel": 480_000,
                "sample_peak_dbfs": -1.0,
                "full_range_rms_dbfs": -15.0,
                "maximum_absolute_dc_offset": 0.0001,
                "clipping_detected": False,
                "bands": [
                    {
                        "name": name,
                        "low_hz": low,
                        "high_hz": high,
                        "rms_dbfs": rms + offset,
                        "balance_to_full_range_db": rms + 15.0 + offset,
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
            },
            "warnings": [],
        }


class FakeAlbumBackend:
    async def create_asset(
        self,
        source_path: Path,
        output_path: Path,
        *,
        sample_rate_hz: int,
        duration_seconds: float,
        gap_before_seconds: float,
        fade_in_seconds: float,
        fade_out_seconds: float,
    ) -> AlbumAssetResult:
        output_path.write_bytes(
            f"gap={gap_before_seconds}:".encode() + source_path.read_bytes()
        )
        return AlbumAssetResult(
            backend_name="test_album",
            executable_path=Path("/usr/bin/test-ffmpeg"),
            version="1.0",
        )


class FakeProjectService:
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


def album_tracks(
    approval_a: ApprovedMasteringCandidate,
    approval_b: ApprovedMasteringCandidate,
) -> list[dict]:
    return [
        {
            "approval": approval_a.model_dump(mode="json"),
            "metadata": {
                "sequence_number": 1,
                "title": "Opening Song",
                "artist": "The Artist",
                "isrc": "USABC2600001",
            },
            "gap_before_seconds": 0.0,
            "fade_in_seconds": 0.1,
            "fade_out_seconds": 0.1,
        },
        {
            "approval": approval_b.model_dump(mode="json"),
            "metadata": {
                "sequence_number": 2,
                "title": "Second Song",
                "artist": "The Artist",
                "isrc": "USABC2600002",
            },
            "gap_before_seconds": 2.0,
        },
    ]


async def test_album_prepares_continuity_project_manifest_and_approval(
    tmp_path: Path,
) -> None:
    path_a = tmp_path / "song-1.wav"
    path_b = tmp_path / "song-2.wav"
    path_a.write_bytes(b"song-one")
    path_b.write_bytes(b"song-two")
    approval_a = candidate_approval(
        path_a,
        suffix="a",
        integrated_lufs=-12.0,
        true_peak_dbtp=-1.0,
    )
    approval_b = candidate_approval(
        path_b,
        suffix="b",
        integrated_lufs=-15.0,
        true_peak_dbtp=-1.5,
    )
    service = MasteringAlbumService(
        FakeAlbumBackend(),
        FakeProgramAnalysisService(),
        FakeProjectService(),
        allowed_source_roots=[tmp_path],
        allowed_project_roots=[tmp_path],
    )
    manifest_path = tmp_path / "album.json"

    result = await service.prepare(
        {"title": "The Album", "artist": "The Artist"},
        "explicit_gaps",
        album_tracks(approval_a, approval_b),
        str(tmp_path / "album.rpp"),
        str(manifest_path),
        continuity_limits={
            "maximum_adjacent_loudness_delta_lu": 2.0,
            "maximum_adjacent_band_balance_delta_db": 1.0,
        },
    )

    assert result["ok"] is True
    album = result["album"]
    assert album["median_integrated_lufs"] == -13.5
    assert album["integrated_loudness_span_lu"] == 3.0
    assert album["transitions"][0]["integrated_loudness_delta_lu"] == -3.0
    assert set(album["transitions"][0]["continuity_flags"]) == {
        "adjacent_loudness_delta",
        "adjacent_band_balance_delta",
    }
    assert album["pq_preview"][1]["pregap_frames"] == 150
    assert album["ddp_available"] is False
    assert manifest_path.is_file()

    approved = await service.approve(
        album,
        "Album Mastering Engineer",
        ["The sequence translates and the song-to-song movement is intentional."],
        True,
    )
    manifest_path.write_text("changed", encoding="utf-8")
    stale = await service.approve(
        album,
        "Album Mastering Engineer",
        ["Still approved."],
        True,
    )

    assert approved["ok"] is True
    assert approved["approval"]["ddp_available"] is False
    assert stale["ok"] is False
    assert stale["error"]["code"] == ErrorCode.MASTERING_SOURCE_CHANGED


async def test_gapless_album_rejects_inserted_gap(tmp_path: Path) -> None:
    path_a = tmp_path / "song-1.wav"
    path_b = tmp_path / "song-2.wav"
    path_a.write_bytes(b"song-one")
    path_b.write_bytes(b"song-two")
    tracks = album_tracks(
        candidate_approval(
            path_a,
            suffix="a",
            integrated_lufs=-12.0,
            true_peak_dbtp=-1.0,
        ),
        candidate_approval(
            path_b,
            suffix="b",
            integrated_lufs=-13.0,
            true_peak_dbtp=-1.0,
        ),
    )

    result = await MasteringAlbumService(
        FakeAlbumBackend(),
        FakeProgramAnalysisService(),
        FakeProjectService(),
        allowed_source_roots=[tmp_path],
        allowed_project_roots=[tmp_path],
    ).prepare(
        {"title": "Gapless Album", "artist": "The Artist"},
        "gapless",
        tracks,
        str(tmp_path / "album.rpp"),
        str(tmp_path / "album.json"),
    )

    assert result["ok"] is False
    assert result["error"]["code"] == ErrorCode.INVALID_MASTERING_REQUEST


async def test_version_set_requires_distinct_approved_sources(
    tmp_path: Path,
) -> None:
    main_path = tmp_path / "main.wav"
    clean_path = tmp_path / "clean.wav"
    main_path.write_bytes(b"main-version")
    clean_path.write_bytes(b"clean-version")
    main = candidate_approval(
        main_path,
        suffix="a",
        integrated_lufs=-12.0,
        true_peak_dbtp=-1.0,
    )
    clean = candidate_approval(
        clean_path,
        suffix="b",
        integrated_lufs=-12.2,
        true_peak_dbtp=-1.1,
    )
    service = MasteringVersionService(allowed_source_roots=[tmp_path])

    result = await service.create_version_set(
        "Single",
        [
            {
                "role": "main",
                "label": "Main",
                "approval": main.model_dump(mode="json"),
            },
            {
                "role": "clean",
                "label": "Clean",
                "approval": clean.model_dump(mode="json"),
            },
        ],
    )
    reused = await service.create_version_set(
        "Invalid",
        [
            {
                "role": "main",
                "label": "Main",
                "approval": main.model_dump(mode="json"),
            },
            {
                "role": "clean",
                "label": "Fake clean",
                "approval": main.model_dump(mode="json"),
            },
        ],
    )

    assert result["ok"] is True
    assert result["version_set"]["version_set_id"].startswith("vs_")
    assert [entry["role"] for entry in result["version_set"]["entries"]] == [
        "main",
        "clean",
    ]
    assert reused["ok"] is False
    assert reused["error"]["code"] == ErrorCode.MASTERING_VERSION_SET_INVALID


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg is not installed")
async def test_ffmpeg_album_asset_applies_gap_and_fades_as_float(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "song.wav"
    output_path = tmp_path / "01.wav"
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
                for frame in range(sample_rate)
            )
        )
    source_sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()

    await FfmpegAlbumAssetBackend(timeout_seconds=10.0).create_asset(
        source_path,
        output_path,
        sample_rate_hz=sample_rate,
        duration_seconds=1.0,
        gap_before_seconds=0.2,
        fade_in_seconds=0.1,
        fade_out_seconds=0.1,
    )
    measured = await FfmpegEbur128Backend(timeout_seconds=10.0).measure(
        AudioMeasurementRequest(audio_path=output_path),
        hashlib.sha256(output_path.read_bytes()).hexdigest(),
    )

    assert measured.technical.codec == "pcm_f32le"
    assert measured.bounds.measured_duration_seconds == pytest.approx(1.2, abs=0.02)
    assert hashlib.sha256(source_path.read_bytes()).hexdigest() == source_sha256
