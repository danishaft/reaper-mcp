from pathlib import Path

from reaper_mcp.errors import ErrorCode
from reaper_mcp.models.audio_measurement import (
    AudioMeasurementBackendInfo,
    AudioMeasurementBounds,
    AudioMeasurementQuality,
    AudioMeasurementRequest,
    AudioMeasurementResult,
    DynamicsMeasurement,
    LoudnessMeasurement,
    PeakMeasurement,
    StereoMeasurement,
)
from reaper_mcp.services.audio_measurement_backend import (
    AudioMeasurementFailedError,
    MeasurementBackendUnavailableError,
)
from reaper_mcp.services.audio_measurement_service import AudioMeasurementService


class FakeBackend:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.request: AudioMeasurementRequest | None = None
        self.source_sha256: str | None = None

    async def measure(
        self, request: AudioMeasurementRequest, source_sha256: str
    ) -> AudioMeasurementResult:
        if self.error is not None:
            raise self.error
        self.request = request
        self.source_sha256 = source_sha256
        return AudioMeasurementResult(
            path=request.audio_path,
            source_sha256=source_sha256,
            standard="ITU-R BS.1770-4 / EBU R128",
            backend=AudioMeasurementBackendInfo(
                name="fake",
                executable_path=Path("/usr/bin/ffmpeg"),
                version="test",
            ),
            bounds=AudioMeasurementBounds(
                start_seconds=request.start_seconds,
                end_seconds=request.end_seconds,
                measured_duration_seconds=10.0,
            ),
            loudness=LoudnessMeasurement(integrated_lufs=-16.0),
            peaks=PeakMeasurement(
                sample_peak_dbfs=-2.0,
                true_peak_dbtp=-1.8,
            ),
            dynamics=DynamicsMeasurement(peak_to_loudness_ratio_db=14.2),
            stereo=StereoMeasurement(channel_layout="stereo"),
            quality=AudioMeasurementQuality(
                complete_loudness_metrics=True,
                sample_peak_available=True,
                true_peak_available=True,
                loudness_range_stable=False,
                source_integrity_verified=False,
            ),
        )


async def test_measure_file_hashes_and_delegates_approved_source(
    tmp_path: Path,
) -> None:
    audio_path = tmp_path / "mix.flac"
    audio_path.write_bytes(b"approved mix")
    backend = FakeBackend()

    result = await AudioMeasurementService(
        backend, allowed_audio_roots=[tmp_path]
    ).measure_file(str(audio_path), normalization_targets_lufs={"custom": -14.0})

    assert result["ok"] is True
    assert backend.request is not None
    assert backend.request.audio_path == audio_path
    assert backend.request.normalization_targets_lufs == {"custom": -14.0}
    assert backend.source_sha256 == result["measurement"]["source_sha256"]
    assert result["measurement"]["quality"]["source_integrity_verified"] is True


async def test_measure_file_rejects_invalid_bounds_before_backend(
    tmp_path: Path,
) -> None:
    audio_path = tmp_path / "mix.wav"
    audio_path.write_bytes(b"approved mix")
    backend = FakeBackend()

    result = await AudioMeasurementService(
        backend, allowed_audio_roots=[tmp_path]
    ).measure_file(str(audio_path), start_seconds=10.0, end_seconds=5.0)

    assert result["ok"] is False
    assert result["error"]["code"] == ErrorCode.INVALID_AUDIO_MEASUREMENT_REQUEST
    assert backend.request is None


async def test_measure_file_reports_missing_backend(tmp_path: Path) -> None:
    audio_path = tmp_path / "mix.wav"
    audio_path.write_bytes(b"approved mix")
    backend = FakeBackend(MeasurementBackendUnavailableError("missing"))

    result = await AudioMeasurementService(
        backend, allowed_audio_roots=[tmp_path]
    ).measure_file(str(audio_path))

    assert result["ok"] is False
    assert result["error"]["code"] == ErrorCode.MEASUREMENT_BACKEND_UNAVAILABLE


async def test_measure_file_reports_backend_failure(tmp_path: Path) -> None:
    audio_path = tmp_path / "mix.wav"
    audio_path.write_bytes(b"approved mix")
    backend = FakeBackend(AudioMeasurementFailedError("bad meter output"))

    result = await AudioMeasurementService(
        backend, allowed_audio_roots=[tmp_path]
    ).measure_file(str(audio_path))

    assert result["ok"] is False
    assert result["error"]["code"] == ErrorCode.AUDIO_MEASUREMENT_FAILED


async def test_measure_file_rejects_path_outside_allowed_roots(
    tmp_path: Path,
) -> None:
    audio_path = tmp_path / "mix.wav"
    audio_path.write_bytes(b"approved mix")

    result = await AudioMeasurementService(
        FakeBackend(), allowed_audio_roots=[]
    ).measure_file(str(audio_path))

    assert result["ok"] is False
    assert result["error"]["code"] == ErrorCode.AUDIO_PATH_NOT_ALLOWED
