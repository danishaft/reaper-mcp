import hashlib
import math
import shutil
import struct
import sys
import wave
from pathlib import Path

import pytest

from reaper_mcp.models.audio_measurement import AudioMeasurementRequest
from reaper_mcp.services.audio_measurement_backend import (
    AsyncioCommandRunner,
    AudioMeasurementFailedError,
    CommandOutputLimitError,
    CommandResult,
    CommandTimedOutError,
    FfmpegEbur128Backend,
    MeasurementBackendUnavailableError,
)

FFMPEG_OUTPUT = """
[Parsed_ebur128_0] t: 0.399979 TARGET:-23 LUFS M: -24.0 S: -120.7
I: -24.0 LUFS LRA: 0.0 LU SPK: -4.0 -3.0 dBFS FTPK: -3.9 -2.9 dBFS
TPK: -3.9 -2.9 dBFS
[Parsed_ebur128_0] t: 3.99998 TARGET:-23 LUFS M: -12.5 S: -14.2
I: -16.0 LUFS LRA: 4.5 LU SPK: -2.1 -2.0 dBFS FTPK: -1.9 -1.8 dBFS
TPK: -1.9 -1.8 dBFS
[Parsed_ebur128_0] Summary:

  Integrated loudness:
    I:         -16.0 LUFS
    Threshold: -26.0 LUFS

  Loudness range:
    LRA:         4.5 LU
    Threshold: -36.0 LUFS
    LRA low:   -19.0 LUFS
    LRA high:  -14.5 LUFS

  Sample peak:
    Peak:       -2.0 dBFS

  True peak:
    Peak:       -1.8 dBFS
"""


class FakeRunner:
    def __init__(self, results: list[CommandResult]) -> None:
        self.results = results
        self.calls: list[list[str]] = []

    async def run(
        self,
        arguments,
        *,
        timeout_seconds: float,
        max_output_bytes: int,
    ) -> CommandResult:
        self.calls.append(list(arguments))
        return self.results.pop(0)


async def test_ffmpeg_backend_returns_distinct_typed_metrics(
    monkeypatch, tmp_path: Path
) -> None:
    executable = tmp_path / "ffmpeg"
    executable.touch()
    monkeypatch.setattr(shutil, "which", lambda _: str(executable))
    runner = FakeRunner(
        [
            CommandResult(0, "ffmpeg version 6.1.1 Copyright\n"),
            CommandResult(0, FFMPEG_OUTPUT),
        ]
    )
    request = AudioMeasurementRequest(
        audio_path=tmp_path / "master.wav",
        start_seconds=10.0,
        end_seconds=14.0,
        normalization_targets_lufs={"listener preset": -14.0},
    )

    result = await FfmpegEbur128Backend(runner=runner).measure(request, "a" * 64)

    assert result.standard == "ITU-R BS.1770-4 / EBU R128"
    assert result.backend.version == "6.1.1"
    assert result.bounds.measured_duration_seconds == pytest.approx(3.99998)
    assert result.loudness.integrated_lufs == -16.0
    assert result.loudness.momentary_max_lufs == -12.5
    assert result.loudness.short_term_max_lufs == -14.2
    assert result.loudness.loudness_range_lu == 4.5
    assert result.peaks.sample_peak_dbfs == -2.0
    assert result.peaks.true_peak_dbtp == -1.8
    assert result.dynamics.peak_to_loudness_ratio_db == 14.2
    assert result.quality.complete_loudness_metrics is True
    assert result.quality.loudness_range_stable is False
    simulation = result.normalization_simulations[0]
    assert simulation.gain_adjustment_db == 2.0
    assert simulation.predicted_true_peak_dbtp == pytest.approx(0.2)
    command = runner.calls[1]
    assert command[command.index("-ss") + 1] == "10.000000000"
    assert command[command.index("-t") + 1] == "4.000000000"
    assert any(
        "ebur128=peak=sample+true:framelog=verbose" in argument for argument in command
    )


async def test_ffmpeg_backend_rejects_missing_executable() -> None:
    backend = FfmpegEbur128Backend(executable="definitely-not-an-ffmpeg")
    request = AudioMeasurementRequest(audio_path=Path("/tmp/master.wav"))

    with pytest.raises(MeasurementBackendUnavailableError, match="not found"):
        await backend.measure(request, "a" * 64)


async def test_ffmpeg_backend_rejects_incomplete_meter_output(
    monkeypatch, tmp_path: Path
) -> None:
    executable = tmp_path / "ffmpeg"
    executable.touch()
    monkeypatch.setattr(shutil, "which", lambda _: str(executable))
    runner = FakeRunner(
        [
            CommandResult(0, "ffmpeg version 6.1.1 Copyright\n"),
            CommandResult(0, "FFmpeg ran but produced no meter summary."),
        ]
    )
    backend = FfmpegEbur128Backend(runner=runner)

    with pytest.raises(AudioMeasurementFailedError, match="complete EBU R128"):
        await backend.measure(
            AudioMeasurementRequest(audio_path=tmp_path / "master.wav"),
            "a" * 64,
        )


async def test_command_runner_enforces_output_limit() -> None:
    runner = AsyncioCommandRunner()

    with pytest.raises(CommandOutputLimitError):
        await runner.run(
            [sys.executable, "-c", "print('x' * 1000)"],
            timeout_seconds=2.0,
            max_output_bytes=100,
        )


async def test_command_runner_enforces_timeout() -> None:
    runner = AsyncioCommandRunner()

    with pytest.raises(CommandTimedOutError):
        await runner.run(
            [sys.executable, "-c", "import time; time.sleep(1)"],
            timeout_seconds=0.01,
            max_output_bytes=1024,
        )


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg is not installed")
async def test_ffmpeg_backend_parses_real_full_program_output(tmp_path: Path) -> None:
    audio_path = tmp_path / "sine.wav"
    sample_rate = 48_000
    frame_count = sample_rate * 4
    with wave.open(str(audio_path), "wb") as wav_file:
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
                for frame in range(frame_count)
            )
        )
    source_before = hashlib.sha256(audio_path.read_bytes()).hexdigest()

    result = await FfmpegEbur128Backend(timeout_seconds=10.0).measure(
        AudioMeasurementRequest(audio_path=audio_path),
        source_before,
    )

    assert result.loudness.integrated_lufs == pytest.approx(-12.0, abs=0.2)
    assert result.loudness.momentary_max_lufs == pytest.approx(-12.0, abs=0.2)
    assert result.loudness.short_term_max_lufs == pytest.approx(-12.0, abs=0.2)
    assert result.peaks.sample_peak_dbfs == pytest.approx(-12.0, abs=0.2)
    assert result.peaks.true_peak_dbtp == pytest.approx(-12.0, abs=0.2)
    assert result.stereo.channel_layout == "stereo"
    assert result.stereo.phase_correlation_mean == pytest.approx(1.0)
    assert result.technical.codec == "pcm_s16le"
    assert result.technical.sample_rate_hz == 48_000
    assert result.technical.effective_bit_depth == 16
    assert hashlib.sha256(audio_path.read_bytes()).hexdigest() == source_before
