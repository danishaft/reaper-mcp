"""Bounded FFmpeg backend for full-program technical and band analysis."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from reaper_mcp.models.audio_measurement import AudioMeasurementBackendInfo
from reaper_mcp.models.audio_program_analysis import (
    AudioProgramAnalysisResult,
    FrequencyBandLevel,
    ProgramSilenceAnalysis,
    SilenceInterval,
)
from reaper_mcp.services.audio_measurement_backend import (
    AsyncioCommandRunner,
    CommandOutputLimitError,
    CommandRunner,
    CommandTimedOutError,
    MeasurementBackendUnavailableError,
)

_NUMBER = r"(?:[-+]?(?:\d+(?:\.\d*)?|\.\d+)|[-+]?inf)"
_ASTATS_PATTERN = re.compile(
    rf"\[astats@(?P<filter>overall|low|lowmid|highmid|high) @[^\]]+\] "
    rf"(?P<field>DC offset|Peak level dB|RMS level dB|Number of samples): "
    rf"(?P<value>{_NUMBER})",
    re.IGNORECASE,
)
_SILENCE_PATTERN = re.compile(
    rf"\bsilence_(?P<event>start|end):\s*(?P<time>{_NUMBER})",
    re.IGNORECASE,
)
_SAMPLE_RATE_PATTERN = re.compile(r"\bAudio: [^\n]*?, (?P<rate>\d+) Hz,", re.I)


class AudioProgramAnalysisError(RuntimeError):
    """FFmpeg could not return complete program-analysis evidence."""


class FfmpegProgramAnalysisBackend:
    """Measure whole-program DC, peak, RMS, bands, and silence."""

    SILENCE_THRESHOLD_DBFS = -80.0
    SILENCE_MINIMUM_SECONDS = 0.1

    def __init__(
        self,
        executable: str = "ffmpeg",
        *,
        timeout_seconds: float = 120.0,
        max_output_bytes: int = 8 * 1024 * 1024,
        runner: CommandRunner | None = None,
    ) -> None:
        self.executable = executable
        self.timeout_seconds = timeout_seconds
        self.max_output_bytes = max_output_bytes
        self.runner = runner or AsyncioCommandRunner()

    async def analyze(
        self,
        path: Path,
        source_sha256: str,
    ) -> AudioProgramAnalysisResult:
        """Analyze one complete audio program."""

        resolved = shutil.which(self.executable)
        if resolved is None:
            raise MeasurementBackendUnavailableError(
                f"FFmpeg executable was not found: {self.executable}"
            )
        executable = Path(resolved).resolve()
        version = await self._version(executable)
        try:
            completed = await self.runner.run(
                self._command(executable, path),
                timeout_seconds=self.timeout_seconds,
                max_output_bytes=self.max_output_bytes,
            )
        except (CommandTimedOutError, CommandOutputLimitError) as exc:
            raise AudioProgramAnalysisError(str(exc)) from exc
        if completed.returncode != 0:
            raise AudioProgramAnalysisError(
                f"FFmpeg returned {completed.returncode}: "
                f"{self._last_line(completed.output)}"
            )
        return self._parse(
            completed.output,
            path=path,
            source_sha256=source_sha256,
            executable=executable,
            version=version,
        )

    async def _version(self, executable: Path) -> str:
        try:
            result = await self.runner.run(
                [str(executable), "-version"],
                timeout_seconds=min(self.timeout_seconds, 10.0),
                max_output_bytes=min(self.max_output_bytes, 64 * 1024),
            )
        except (CommandTimedOutError, CommandOutputLimitError) as exc:
            raise MeasurementBackendUnavailableError(str(exc)) from exc
        first_line = result.output.splitlines()[0] if result.output else ""
        if result.returncode != 0 or not first_line.startswith("ffmpeg version "):
            raise MeasurementBackendUnavailableError("The FFmpeg version check failed.")
        return first_line.removeprefix("ffmpeg version ").split(maxsplit=1)[0]

    @classmethod
    def _command(cls, executable: Path, path: Path) -> list[str]:
        filter_graph = (
            "[0:a]asplit=6[overall][silence][low][lowmid][highmid][high];"
            "[overall]astats@overall=metadata=0:reset=0:"
            "measure_perchannel=DC_offset+Peak_level+RMS_level+Number_of_samples:"
            "measure_overall=DC_offset+Peak_level+RMS_level+Number_of_samples[o];"
            f"[silence]silencedetect@silence=noise={cls.SILENCE_THRESHOLD_DBFS}dB:"
            f"d={cls.SILENCE_MINIMUM_SECONDS}[s];"
            "[low]lowpass=f=200,astats@low=metadata=0:reset=0:"
            "measure_perchannel=none:measure_overall=RMS_level[l];"
            "[lowmid]highpass=f=200,lowpass=f=2000,"
            "astats@lowmid=metadata=0:reset=0:measure_perchannel=none:"
            "measure_overall=RMS_level[lm];"
            "[highmid]highpass=f=2000,lowpass=f=8000,"
            "astats@highmid=metadata=0:reset=0:measure_perchannel=none:"
            "measure_overall=RMS_level[hm];"
            "[high]highpass=f=8000,astats@high=metadata=0:reset=0:"
            "measure_perchannel=none:measure_overall=RMS_level[h]"
        )
        return [
            str(executable),
            "-hide_banner",
            "-nostdin",
            "-nostats",
            "-i",
            str(path),
            "-filter_complex",
            filter_graph,
            "-map",
            "[o]",
            "-map",
            "[s]",
            "-map",
            "[l]",
            "-map",
            "[lm]",
            "-map",
            "[hm]",
            "-map",
            "[h]",
            "-f",
            "null",
            "-",
        ]

    @classmethod
    def _parse(
        cls,
        output: str,
        *,
        path: Path,
        source_sha256: str,
        executable: Path,
        version: str,
    ) -> AudioProgramAnalysisResult:
        values: dict[tuple[str, str], list[float]] = {}
        for match in _ASTATS_PATTERN.finditer(output):
            key = (match.group("filter").lower(), match.group("field").lower())
            values.setdefault(key, []).append(float(match.group("value")))
        sample_rates = [
            int(match.group("rate")) for match in _SAMPLE_RATE_PATTERN.finditer(output)
        ]
        try:
            sample_rate = sample_rates[0]
            sample_count = round(max(values[("overall", "number of samples")]))
            peak = max(values[("overall", "peak level db")])
            full_rms = values[("overall", "rms level db")][-1]
            dc_offset = max(abs(value) for value in values[("overall", "dc offset")])
            band_rms = {
                name: values[(name, "rms level db")][-1]
                for name in ("low", "lowmid", "highmid", "high")
            }
        except (KeyError, IndexError, ValueError) as exc:
            raise AudioProgramAnalysisError(
                "FFmpeg did not return complete astats evidence."
            ) from exc
        if sample_rate <= 0 or sample_count <= 0:
            raise AudioProgramAnalysisError(
                "FFmpeg returned invalid sample-rate or duration evidence."
            )
        duration = sample_count / sample_rate
        silence = cls._silence(output, duration)
        band_ranges = {
            "low": (0.0, 200.0),
            "lowmid": (200.0, 2_000.0),
            "highmid": (2_000.0, 8_000.0),
            "high": (8_000.0, None),
        }
        bands = [
            FrequencyBandLevel(
                name=name,
                low_hz=band_ranges[name][0],
                high_hz=band_ranges[name][1],
                rms_dbfs=band_rms[name],
                balance_to_full_range_db=band_rms[name] - full_rms,
            )
            for name in ("low", "lowmid", "highmid", "high")
        ]
        return AudioProgramAnalysisResult(
            path=path,
            source_sha256=source_sha256,
            backend=AudioMeasurementBackendInfo(
                name="ffmpeg_astats_bands_silence",
                executable_path=executable,
                version=version,
            ),
            duration_seconds=duration,
            sample_rate_hz=sample_rate,
            sample_count_per_channel=sample_count,
            sample_peak_dbfs=peak,
            full_range_rms_dbfs=full_rms,
            maximum_absolute_dc_offset=dc_offset,
            clipping_detected=peak >= -0.0001,
            bands=bands,
            silence=silence,
            source_integrity_verified=False,
        )

    @classmethod
    def _silence(
        cls,
        output: str,
        duration_seconds: float,
    ) -> ProgramSilenceAnalysis:
        intervals: list[SilenceInterval] = []
        pending_start = None
        for match in _SILENCE_PATTERN.finditer(output):
            event = match.group("event").lower()
            time_seconds = max(0.0, float(match.group("time")))
            if event == "start":
                pending_start = time_seconds
            elif pending_start is not None:
                end_seconds = min(duration_seconds, time_seconds)
                intervals.append(
                    SilenceInterval(
                        start_seconds=pending_start,
                        end_seconds=end_seconds,
                        duration_seconds=max(0.0, end_seconds - pending_start),
                    )
                )
                pending_start = None
        if pending_start is not None:
            intervals.append(
                SilenceInterval(
                    start_seconds=pending_start,
                    end_seconds=duration_seconds,
                    duration_seconds=max(0.0, duration_seconds - pending_start),
                )
            )
        tolerance = 1.0 / 75.0
        leading = (
            intervals[0].duration_seconds
            if intervals and intervals[0].start_seconds <= tolerance
            else 0.0
        )
        trailing = (
            intervals[-1].duration_seconds
            if intervals
            and abs(intervals[-1].end_seconds - duration_seconds) <= tolerance
            else 0.0
        )
        return ProgramSilenceAnalysis(
            threshold_dbfs=cls.SILENCE_THRESHOLD_DBFS,
            minimum_duration_seconds=cls.SILENCE_MINIMUM_SECONDS,
            leading_silence_seconds=leading,
            trailing_silence_seconds=trailing,
            total_silence_seconds=sum(
                interval.duration_seconds for interval in intervals
            ),
            intervals=intervals,
        )

    @staticmethod
    def _last_line(output: str) -> str:
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        return lines[-1] if lines else "no diagnostic output"
