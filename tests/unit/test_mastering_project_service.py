import hashlib
import shutil
import struct
import wave
from pathlib import Path

import pytest

from reaper_mcp.errors import ErrorCode
from reaper_mcp.models.audio_measurement import (
    AudioMeasurementBackendInfo,
    AudioMeasurementBounds,
    AudioMeasurementQuality,
    AudioMeasurementResult,
    DynamicsMeasurement,
    LoudnessMeasurement,
    PeakMeasurement,
    StereoMeasurement,
)
from reaper_mcp.models.mastering import (
    MasteringIntent,
    MasteringSession,
    MasteringSource,
)
from reaper_mcp.services.mastering_project_service import MasteringProjectService


def write_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(2)
        wav_file.setsampwidth(2)
        wav_file.setframerate(48_000)
        wav_file.writeframes(struct.pack("<hh", 0, 0) * 4_800)


def session_payload(path: Path) -> dict:
    source_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    measurement = AudioMeasurementResult(
        path=path,
        source_sha256=source_sha256,
        standard="ITU-R BS.1770-4 / EBU R128",
        backend=AudioMeasurementBackendInfo(
            name="ffmpeg_ebur128",
            executable_path=Path("/usr/bin/ffmpeg"),
            version="6.1.1",
        ),
        bounds=AudioMeasurementBounds(
            start_seconds=0.0,
            measured_duration_seconds=0.1,
        ),
        loudness=LoudnessMeasurement(integrated_lufs=-70.0),
        peaks=PeakMeasurement(
            sample_peak_dbfs=-120.0,
            true_peak_dbtp=-120.0,
        ),
        dynamics=DynamicsMeasurement(peak_to_loudness_ratio_db=-50.0),
        stereo=StereoMeasurement(channel_layout="stereo"),
        quality=AudioMeasurementQuality(
            complete_loudness_metrics=False,
            sample_peak_available=True,
            true_peak_available=True,
            loudness_range_stable=False,
            source_integrity_verified=True,
        ),
    )
    return MasteringSession(
        session_id="ms_" + "a" * 24,
        source=MasteringSource(
            workflow_mode="stereo_mix",
            measurement=measurement,
        ),
        intent=MasteringIntent(desired_outcome="Create an isolated project"),
    ).model_dump(mode="json")


async def test_stereo_project_rejects_existing_destination(
    tmp_path: Path,
) -> None:
    source = tmp_path / "mix.wav"
    write_wav(source)
    destination = tmp_path / "master.rpp"
    destination.write_text("user project", encoding="utf-8")

    result = await MasteringProjectService(
        allowed_project_roots=[tmp_path],
    ).create_stereo_project(session_payload(source), str(destination))

    assert result["ok"] is False
    assert result["error"]["code"] == ErrorCode.PROJECT_PATH_NOT_ALLOWED
    assert destination.read_text(encoding="utf-8") == "user project"


@pytest.mark.skipif(shutil.which("reaper") is None, reason="REAPER is not installed")
async def test_stereo_project_is_created_by_isolated_reaper_process(
    tmp_path: Path,
) -> None:
    source = tmp_path / "approved-mix.wav"
    write_wav(source)
    source_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    destination = tmp_path / "master.rpp"

    result = await MasteringProjectService(
        allowed_project_roots=[tmp_path],
        reaper_executable=Path(shutil.which("reaper") or ""),
        timeout_seconds=10.0,
        poll_interval_seconds=0.05,
    ).create_stereo_project(session_payload(source), str(destination))

    assert result["ok"] is True
    assert destination.read_bytes().lstrip().startswith(b"<REAPER_PROJECT")
    assert "approved-mix.wav" in destination.read_text(
        encoding="utf-8", errors="replace"
    )
    assert (
        result["project"]["project_sha256"]
        == hashlib.sha256(destination.read_bytes()).hexdigest()
    )
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_sha256


@pytest.mark.skipif(shutil.which("reaper") is None, reason="REAPER is not installed")
async def test_media_sequence_project_preserves_supplied_order(
    tmp_path: Path,
) -> None:
    source_a = tmp_path / "Audition-A.wav"
    source_b = tmp_path / "Audition-B.wav"
    write_wav(source_a)
    write_wav(source_b)
    destination = tmp_path / "audition.rpp"

    result = await MasteringProjectService(
        allowed_project_roots=[tmp_path],
        reaper_executable=Path(shutil.which("reaper") or ""),
        timeout_seconds=10.0,
        poll_interval_seconds=0.05,
    ).create_media_sequence_project(
        [source_a, source_b],
        destination,
    )

    project_text = destination.read_text(encoding="utf-8", errors="replace")
    assert result["ok"] is True
    assert project_text.index("Audition-A.wav") < project_text.index("Audition-B.wav")
    assert result["project"]["media_paths"] == [str(source_a), str(source_b)]
