from pathlib import Path

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
from reaper_mcp.services.mastering_session_service import MasteringSessionService


def measurement_payload(path: Path) -> dict:
    return AudioMeasurementResult(
        path=path,
        source_sha256="a" * 64,
        standard="ITU-R BS.1770-4 / EBU R128",
        backend=AudioMeasurementBackendInfo(
            name="ffmpeg_ebur128",
            executable_path=Path("/usr/bin/ffmpeg"),
            version="6.1.1",
        ),
        bounds=AudioMeasurementBounds(
            start_seconds=0.0,
            measured_duration_seconds=180.0,
        ),
        loudness=LoudnessMeasurement(
            integrated_lufs=-16.0,
            momentary_max_lufs=-11.0,
            short_term_max_lufs=-13.0,
            loudness_range_lu=7.0,
        ),
        peaks=PeakMeasurement(
            sample_peak_dbfs=-2.0,
            true_peak_dbtp=-1.5,
        ),
        dynamics=DynamicsMeasurement(peak_to_loudness_ratio_db=14.5),
        stereo=StereoMeasurement(
            channel_layout="stereo",
            phase_correlation_mean=0.8,
            phase_correlation_minimum=0.2,
        ),
        quality=AudioMeasurementQuality(
            complete_loudness_metrics=True,
            sample_peak_available=True,
            true_peak_available=True,
            loudness_range_stable=True,
            source_integrity_verified=True,
        ),
    ).model_dump(mode="json")


class FakeMeasurementService:
    def __init__(self, result: dict) -> None:
        self.result = result
        self.calls: list[tuple[str, dict[str, float]]] = []

    async def measure_file(
        self,
        source_path: str,
        *,
        normalization_targets_lufs: dict[str, float],
    ) -> dict:
        self.calls.append((source_path, normalization_targets_lufs))
        return self.result


class FakeProjectService:
    def __init__(self) -> None:
        self.calls = 0

    async def get_project_snapshot(self) -> dict:
        self.calls += 1
        return {
            "ok": True,
            "snapshot": {
                "project": {
                    "path": "/sessions/song.rpp",
                    "name": "Song",
                    "dirty": False,
                    "state_change_count": 42,
                }
            },
            "warnings": [],
        }


async def test_stereo_mix_session_is_measured_and_deterministic(
    tmp_path: Path,
) -> None:
    audio_path = tmp_path / "approved-mix.wav"
    measurement = FakeMeasurementService(
        {"ok": True, "measurement": measurement_payload(audio_path), "warnings": []}
    )
    projects = FakeProjectService()
    service = MasteringSessionService(measurement, projects)

    first = await service.create_session(
        str(audio_path),
        "stereo_mix",
        "Open, punchy, and translation-safe",
        priorities=["vocal focus", "preserve transients"],
        normalization_targets_lufs={"client playback": -14.0},
    )
    second = await service.create_session(
        str(audio_path),
        "stereo_mix",
        "Open, punchy, and translation-safe",
        priorities=["vocal focus", "preserve transients"],
        normalization_targets_lufs={"client playback": -14.0},
    )

    assert first["ok"] is True
    assert first["session"]["session_id"] == second["session"]["session_id"]
    assert first["session"]["source"]["project_context"] is None
    assert projects.calls == 0
    assert measurement.calls[0] == (
        str(audio_path),
        {"client playback": -14.0},
    )


async def test_current_project_session_fingerprints_project_snapshot(
    tmp_path: Path,
) -> None:
    audio_path = tmp_path / "approved-mix.wav"
    measurement = FakeMeasurementService(
        {"ok": True, "measurement": measurement_payload(audio_path), "warnings": []}
    )
    projects = FakeProjectService()

    result = await MasteringSessionService(measurement, projects).create_session(
        str(audio_path),
        "current_project",
        "Keep the approved mix balance",
    )

    assert result["ok"] is True
    context = result["session"]["source"]["project_context"]
    assert context["project_path"] == "/sessions/song.rpp"
    assert context["state_change_count"] == 42
    assert len(context["snapshot_sha256"]) == 64
    assert projects.calls == 1


async def test_session_rejects_unknown_workflow_mode(tmp_path: Path) -> None:
    audio_path = tmp_path / "approved-mix.wav"
    measurement = FakeMeasurementService(
        {"ok": True, "measurement": measurement_payload(audio_path), "warnings": []}
    )

    result = await MasteringSessionService(
        measurement, FakeProjectService()
    ).create_session(str(audio_path), "album", "Coherent")

    assert result["ok"] is False
    assert result["error"]["code"] == ErrorCode.INVALID_MASTERING_REQUEST
    assert measurement.calls == []


async def test_session_propagates_measurement_failure(tmp_path: Path) -> None:
    failure = {
        "ok": False,
        "error": {
            "code": ErrorCode.MEASUREMENT_BACKEND_UNAVAILABLE,
            "message": "missing",
            "details": {},
            "recoverable": True,
            "suggested_action": "configure ffmpeg",
        },
        "warnings": [],
    }
    measurement = FakeMeasurementService(failure)

    result = await MasteringSessionService(
        measurement, FakeProjectService()
    ).create_session(str(tmp_path / "mix.wav"), "stereo_mix", "Balanced")

    assert result is failure
