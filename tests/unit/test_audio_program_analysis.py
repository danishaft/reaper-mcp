import hashlib
import math
import shutil
import struct
import wave
from pathlib import Path

import pytest

from reaper_mcp.services.audio_measurement_backend import CommandResult
from reaper_mcp.services.audio_program_analysis_backend import (
    FfmpegProgramAnalysisBackend,
)
from reaper_mcp.services.audio_program_analysis_service import (
    AudioProgramAnalysisService,
)


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


PROGRAM_OUTPUT = """
Input #0, wav, from 'master.wav':
  Stream #0:0: Audio: pcm_s24le, 48000 Hz, stereo, s32 (24 bit)
[silencedetect@silence @ 0x1] silence_start: 0
[silencedetect@silence @ 0x1] silence_end: 0.2 | silence_duration: 0.2
[silencedetect@silence @ 0x1] silence_start: 9.8
[silencedetect@silence @ 0x1] silence_end: 10 | silence_duration: 0.2
[astats@high @ 0x1] Overall
[astats@high @ 0x1] RMS level dB: -28.0
[astats@highmid @ 0x1] Overall
[astats@highmid @ 0x1] RMS level dB: -20.0
[astats@lowmid @ 0x1] Overall
[astats@lowmid @ 0x1] RMS level dB: -17.0
[astats@low @ 0x1] Overall
[astats@low @ 0x1] RMS level dB: -22.0
[astats@overall @ 0x1] Channel: 1
[astats@overall @ 0x1] DC offset: 0.000100
[astats@overall @ 0x1] Peak level dB: -1.2
[astats@overall @ 0x1] RMS level dB: -16.1
[astats@overall @ 0x1] Number of samples: 480000
[astats@overall @ 0x1] Channel: 2
[astats@overall @ 0x1] DC offset: -0.000200
[astats@overall @ 0x1] Peak level dB: -1.0
[astats@overall @ 0x1] RMS level dB: -15.9
[astats@overall @ 0x1] Number of samples: 480000
[astats@overall @ 0x1] Overall
[astats@overall @ 0x1] DC offset: -0.000050
[astats@overall @ 0x1] Peak level dB: -1.0
[astats@overall @ 0x1] RMS level dB: -16.0
[astats@overall @ 0x1] Number of samples: 480000
"""


async def test_program_backend_parses_bands_dc_and_boundaries(
    monkeypatch,
    tmp_path: Path,
) -> None:
    executable = tmp_path / "ffmpeg"
    executable.touch()
    monkeypatch.setattr(shutil, "which", lambda _: str(executable))
    runner = FakeRunner(
        [
            CommandResult(0, "ffmpeg version 6.1.1 Copyright\n"),
            CommandResult(0, PROGRAM_OUTPUT),
        ]
    )

    result = await FfmpegProgramAnalysisBackend(runner=runner).analyze(
        tmp_path / "master.wav",
        "a" * 64,
    )

    assert result.duration_seconds == 10.0
    assert result.maximum_absolute_dc_offset == 0.0002
    assert result.sample_peak_dbfs == -1.0
    assert result.clipping_detected is False
    assert result.source_integrity_verified is False
    assert result.silence.leading_silence_seconds == 0.2
    assert result.silence.trailing_silence_seconds == pytest.approx(0.2)
    assert result.silence.total_silence_seconds == pytest.approx(0.4)
    bands = {band.name: band for band in result.bands}
    assert bands["lowmid"].balance_to_full_range_db == -1.0
    assert (
        "astats@overall"
        in runner.calls[1][runner.calls[1].index("-filter_complex") + 1]
    )


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg is not installed")
async def test_program_service_analyzes_real_full_program(
    tmp_path: Path,
) -> None:
    audio_path = tmp_path / "boundaries.wav"
    sample_rate = 48_000
    with wave.open(str(audio_path), "wb") as wav_file:
        wav_file.setnchannels(2)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(
            b"".join(
                struct.pack(
                    "<hh",
                    0
                    if frame < sample_rate // 5 or frame >= sample_rate * 6 // 5
                    else round(
                        math.sin(2 * math.pi * 997 * frame / sample_rate) * 8192
                    ),
                    0
                    if frame < sample_rate // 5 or frame >= sample_rate * 6 // 5
                    else round(
                        math.sin(2 * math.pi * 997 * frame / sample_rate) * 8192
                    ),
                )
                for frame in range(sample_rate * 7 // 5)
            )
        )
    source_sha256 = hashlib.sha256(audio_path.read_bytes()).hexdigest()

    result = await AudioProgramAnalysisService(
        FfmpegProgramAnalysisBackend(timeout_seconds=10.0),
        allowed_audio_roots=[tmp_path],
    ).analyze_file(str(audio_path))

    assert result["ok"] is True
    analysis = result["analysis"]
    assert analysis["sample_rate_hz"] == 48_000
    assert analysis["sample_peak_dbfs"] == pytest.approx(-12.0, abs=0.2)
    assert analysis["maximum_absolute_dc_offset"] < 0.001
    assert analysis["silence"]["leading_silence_seconds"] == pytest.approx(
        0.2, abs=0.02
    )
    assert analysis["silence"]["trailing_silence_seconds"] == pytest.approx(
        0.2, abs=0.02
    )
    assert len(analysis["bands"]) == 4
    assert analysis["source_integrity_verified"] is True
    assert hashlib.sha256(audio_path.read_bytes()).hexdigest() == source_sha256
