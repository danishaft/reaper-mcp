"""Replaceable standards-based audio measurement backends."""

from __future__ import annotations

import asyncio
import math
import re
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from reaper_mcp.models.audio_measurement import (
    AudioMeasurementBackendInfo,
    AudioMeasurementBounds,
    AudioMeasurementQuality,
    AudioMeasurementRequest,
    AudioMeasurementResult,
    AudioTechnicalProperties,
    DynamicsMeasurement,
    LoudnessMeasurement,
    PeakMeasurement,
    PlaybackNormalizationSimulation,
    StereoMeasurement,
)

_NUMBER = r"(?:[-+]?(?:\d+(?:\.\d*)?|\.\d+)|[-+]?inf)"
_FRAME_PATTERN = re.compile(
    rf"\bt:\s*(?P<time>{_NUMBER}).*?"
    rf"\bM:\s*(?P<momentary>{_NUMBER})\s+"
    rf"S:\s*(?P<short_term>{_NUMBER})\s+"
    rf"I:\s*(?P<integrated>{_NUMBER})\s+LUFS\s+"
    rf"LRA:\s*(?P<range>{_NUMBER})\s+LU",
    re.IGNORECASE,
)
_PHASE_PATTERN = re.compile(
    rf"lavfi\.aphasemeter\.phase=(?P<value>{_NUMBER})", re.IGNORECASE
)
_CHANNEL_LAYOUT_PATTERN = re.compile(
    r"Stream #0:[^:\n]*: Audio: [^\n]*? Hz, (?P<layout>[^,\n]+),",
    re.IGNORECASE,
)
_AUDIO_STREAM_PATTERN = re.compile(
    r"Stream #0:[^:\n]*: Audio: (?P<codec>[^ ,]+)[^\n]*?, "
    r"(?P<sample_rate>\d+) Hz, (?P<layout>[^,\n]+), "
    r"(?P<sample_format>[^,\s]+)",
    re.IGNORECASE,
)


class AudioMeasurementBackend(Protocol):
    """Measure one complete approved source without mutating it."""

    async def measure(
        self, request: AudioMeasurementRequest, source_sha256: str
    ) -> AudioMeasurementResult:
        """Return a typed measurement or raise a backend error."""


@dataclass(frozen=True)
class CommandResult:
    """Bounded external-command result."""

    returncode: int
    output: str


class CommandRunner(Protocol):
    """Run an argv-only command with explicit resource bounds."""

    async def run(
        self, arguments: Sequence[str], *, timeout_seconds: float, max_output_bytes: int
    ) -> CommandResult:
        """Run a command without a shell."""


class CommandTimedOutError(RuntimeError):
    """The measurement process exceeded its configured deadline."""


class CommandOutputLimitError(RuntimeError):
    """The measurement process exceeded its configured output budget."""


class AsyncioCommandRunner:
    """Run one subprocess while bounding time and captured output."""

    async def run(
        self, arguments: Sequence[str], *, timeout_seconds: float, max_output_bytes: int
    ) -> CommandResult:
        try:
            process = await asyncio.create_subprocess_exec(
                *arguments,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except OSError as exc:
            raise MeasurementBackendUnavailableError(str(exc)) from exc

        async def collect() -> bytes:
            assert process.stdout is not None
            output = bytearray()
            while chunk := await process.stdout.read(64 * 1024):
                output.extend(chunk)
                if len(output) > max_output_bytes:
                    raise CommandOutputLimitError(
                        f"Command output exceeded {max_output_bytes} bytes."
                    )
            await process.wait()
            return bytes(output)

        try:
            raw_output = await asyncio.wait_for(collect(), timeout_seconds)
        except TimeoutError as exc:
            process.kill()
            await process.wait()
            raise CommandTimedOutError(
                f"Command exceeded {timeout_seconds:g} seconds."
            ) from exc
        except CommandOutputLimitError:
            process.kill()
            await process.wait()
            raise

        return CommandResult(
            returncode=process.returncode or 0,
            output=raw_output.decode("utf-8", errors="replace"),
        )


class MeasurementBackendUnavailableError(RuntimeError):
    """The configured measurement executable cannot be used."""


class AudioMeasurementFailedError(RuntimeError):
    """The backend ran but did not return an acceptable measurement."""


class FfmpegEbur128Backend:
    """Measure full-program EBU R128 metrics with FFmpeg's ebur128 filter."""

    STANDARD = "ITU-R BS.1770-4 / EBU R128"

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

    async def measure(
        self, request: AudioMeasurementRequest, source_sha256: str
    ) -> AudioMeasurementResult:
        executable_path = self._resolve_executable()
        version = await self._read_version(executable_path)
        command = self._measurement_command(executable_path, request)
        try:
            completed = await self.runner.run(
                command,
                timeout_seconds=self.timeout_seconds,
                max_output_bytes=self.max_output_bytes,
            )
        except (CommandTimedOutError, CommandOutputLimitError) as exc:
            raise AudioMeasurementFailedError(str(exc)) from exc
        if completed.returncode != 0:
            detail = self._last_nonempty_line(completed.output)
            raise AudioMeasurementFailedError(
                f"FFmpeg returned {completed.returncode}: {detail}"
            )

        return self._parse_result(
            completed.output,
            request=request,
            source_sha256=source_sha256,
            executable_path=executable_path,
            version=version,
        )

    def _resolve_executable(self) -> Path:
        resolved = shutil.which(self.executable)
        if resolved is None:
            raise MeasurementBackendUnavailableError(
                f"FFmpeg executable was not found: {self.executable}"
            )
        return Path(resolved).resolve()

    async def _read_version(self, executable_path: Path) -> str:
        try:
            completed = await self.runner.run(
                [str(executable_path), "-version"],
                timeout_seconds=min(self.timeout_seconds, 10.0),
                max_output_bytes=min(self.max_output_bytes, 64 * 1024),
            )
        except (CommandTimedOutError, CommandOutputLimitError) as exc:
            raise MeasurementBackendUnavailableError(str(exc)) from exc
        if completed.returncode != 0:
            raise MeasurementBackendUnavailableError(
                f"FFmpeg version check returned {completed.returncode}."
            )
        first_line = self._last_nonempty_line(
            completed.output.splitlines()[0] if completed.output else ""
        )
        if not first_line.lower().startswith("ffmpeg version "):
            raise MeasurementBackendUnavailableError(
                "The configured executable did not identify itself as FFmpeg."
            )
        return first_line.removeprefix("ffmpeg version ").split(maxsplit=1)[0]

    @staticmethod
    def _measurement_command(
        executable_path: Path, request: AudioMeasurementRequest
    ) -> list[str]:
        arguments = [
            str(executable_path),
            "-hide_banner",
            "-nostats",
            "-loglevel",
            "verbose",
        ]
        if request.start_seconds > 0.0:
            arguments.extend(["-ss", f"{request.start_seconds:.9f}"])
        arguments.extend(["-i", str(request.audio_path)])
        if request.end_seconds is not None:
            duration = request.end_seconds - request.start_seconds
            arguments.extend(["-t", f"{duration:.9f}"])
        arguments.extend(
            [
                "-filter_complex",
                (
                    "[0:a]asplit=2[levels][phase];"
                    "[levels]ebur128=peak=sample+true:framelog=verbose[metered];"
                    "[phase]aformat=channel_layouts=stereo,"
                    "asetnsamples=n=4096:p=0,aphasemeter=video=0,"
                    "ametadata=print:key=lavfi.aphasemeter.phase[phased]"
                ),
                "-map",
                "[metered]",
                "-map",
                "[phased]",
                "-f",
                "null",
                "-",
            ]
        )
        return arguments

    def _parse_result(
        self,
        output: str,
        *,
        request: AudioMeasurementRequest,
        source_sha256: str,
        executable_path: Path,
        version: str,
    ) -> AudioMeasurementResult:
        frames = list(_FRAME_PATTERN.finditer(output))
        summary = output.rsplit("Summary:", maxsplit=1)[-1]
        integrated = self._section_value(summary, "Integrated loudness", "I", "LUFS")
        loudness_range = self._section_value(summary, "Loudness range", "LRA", "LU")
        sample_peak = self._section_value(summary, "Sample peak", "Peak", "dBFS")
        true_peak = self._section_value(summary, "True peak", "Peak", "dBFS")
        if not frames or integrated is None:
            raise AudioMeasurementFailedError(
                "FFmpeg output did not contain a complete EBU R128 measurement."
            )

        momentary_values = [
            value
            for frame in frames
            if (value := self._finite_meter_value(frame.group("momentary"))) is not None
        ]
        short_term_values = [
            value
            for frame in frames
            if (value := self._finite_meter_value(frame.group("short_term")))
            is not None
        ]
        measured_duration = max(float(frame.group("time")) for frame in frames)
        integrated_threshold = self._nth_value(summary, "Threshold", "LUFS", 0)
        range_threshold = self._nth_value(summary, "Threshold", "LUFS", 1)
        range_low = self._labeled_value(summary, "LRA low", "LUFS")
        range_high = self._labeled_value(summary, "LRA high", "LUFS")
        input_header = output.split("Stream mapping:", maxsplit=1)[0]
        stream_match = _AUDIO_STREAM_PATTERN.search(input_header)
        layout_match = _CHANNEL_LAYOUT_PATTERN.search(input_header)
        channel_layout = layout_match.group("layout").strip() if layout_match else None
        channel_layout = {
            "1 channels": "mono",
            "2 channels": "stereo",
        }.get(channel_layout, channel_layout)
        phase_values = [
            value
            for match in _PHASE_PATTERN.finditer(output)
            if (value := self._finite_value(match.group("value"))) is not None
        ]

        simulations = self._normalization_simulations(
            request.normalization_targets_lufs,
            integrated_lufs=integrated,
            true_peak_dbtp=true_peak,
        )
        warnings: list[str] = []
        if not request.normalization_targets_lufs:
            warnings.append(
                "No playback-normalization targets were requested; no platform "
                "gain simulation was inferred."
            )
        if measured_duration < 60.0:
            warnings.append(
                "Loudness range is reported but is not stable before 60 seconds "
                "of measured program."
            )
        if channel_layout == "mono":
            phase_values = []
            warnings.append(
                "Stereo phase correlation does not apply to the mono source."
            )
        elif channel_layout not in {None, "stereo"}:
            warnings.append(
                "Phase correlation was measured from FFmpeg's stereo downmix of "
                f"the {channel_layout} source."
            )

        complete_loudness = all(
            value is not None
            for value in (
                integrated,
                max(momentary_values, default=None),
                max(short_term_values, default=None),
                loudness_range,
            )
        )

        return AudioMeasurementResult(
            path=request.audio_path,
            source_sha256=source_sha256,
            standard=self.STANDARD,
            backend=AudioMeasurementBackendInfo(
                name="ffmpeg_ebur128",
                executable_path=executable_path,
                version=version,
            ),
            bounds=AudioMeasurementBounds(
                start_seconds=request.start_seconds,
                end_seconds=request.end_seconds,
                measured_duration_seconds=measured_duration,
            ),
            loudness=LoudnessMeasurement(
                integrated_lufs=integrated,
                momentary_max_lufs=max(momentary_values, default=None),
                short_term_max_lufs=max(short_term_values, default=None),
                loudness_range_lu=loudness_range,
                integrated_threshold_lufs=integrated_threshold,
                range_threshold_lufs=range_threshold,
                range_low_lufs=range_low,
                range_high_lufs=range_high,
            ),
            peaks=PeakMeasurement(
                sample_peak_dbfs=sample_peak,
                true_peak_dbtp=true_peak,
            ),
            dynamics=DynamicsMeasurement(
                peak_to_loudness_ratio_db=(
                    true_peak - integrated if true_peak is not None else None
                )
            ),
            stereo=StereoMeasurement(
                channel_layout=channel_layout,
                phase_correlation_mean=(
                    sum(phase_values) / len(phase_values) if phase_values else None
                ),
                phase_correlation_minimum=min(phase_values, default=None),
            ),
            quality=AudioMeasurementQuality(
                complete_loudness_metrics=complete_loudness,
                sample_peak_available=sample_peak is not None,
                true_peak_available=true_peak is not None,
                loudness_range_stable=measured_duration >= 60.0,
                source_integrity_verified=False,
            ),
            technical=AudioTechnicalProperties(
                codec=stream_match.group("codec") if stream_match else None,
                sample_rate_hz=(
                    int(stream_match.group("sample_rate")) if stream_match else None
                ),
                channel_layout=channel_layout,
                sample_format=(
                    stream_match.group("sample_format") if stream_match else None
                ),
                effective_bit_depth=self._effective_bit_depth(
                    stream_match.group("codec") if stream_match else None,
                    stream_match.group("sample_format") if stream_match else None,
                ),
            ),
            normalization_simulations=simulations,
            warnings=warnings,
        )

    @staticmethod
    def _normalization_simulations(
        targets: dict[str, float],
        *,
        integrated_lufs: float,
        true_peak_dbtp: float | None,
    ) -> list[PlaybackNormalizationSimulation]:
        simulations = []
        for name, target in targets.items():
            gain = target - integrated_lufs
            simulations.append(
                PlaybackNormalizationSimulation(
                    name=name,
                    target_lufs=target,
                    gain_adjustment_db=gain,
                    predicted_true_peak_dbtp=(
                        true_peak_dbtp + gain if true_peak_dbtp is not None else None
                    ),
                )
            )
        return simulations

    @staticmethod
    def _section_value(
        output: str, section: str, label: str, unit: str
    ) -> float | None:
        pattern = re.compile(
            rf"{re.escape(section)}:\s+.*?"
            rf"{re.escape(label)}:\s*(?P<value>{_NUMBER})\s+{re.escape(unit)}",
            re.IGNORECASE | re.DOTALL,
        )
        match = pattern.search(output)
        return (
            FfmpegEbur128Backend._finite_value(match.group("value")) if match else None
        )

    @staticmethod
    def _nth_value(output: str, label: str, unit: str, index: int) -> float | None:
        pattern = re.compile(
            rf"{re.escape(label)}:\s*(?P<value>{_NUMBER})\s+{re.escape(unit)}",
            re.IGNORECASE,
        )
        matches = list(pattern.finditer(output))
        return (
            FfmpegEbur128Backend._finite_value(matches[index].group("value"))
            if len(matches) > index
            else None
        )

    @staticmethod
    def _labeled_value(output: str, label: str, unit: str) -> float | None:
        pattern = re.compile(
            rf"{re.escape(label)}:\s*(?P<value>{_NUMBER})\s+{re.escape(unit)}",
            re.IGNORECASE,
        )
        match = pattern.search(output)
        return (
            FfmpegEbur128Backend._finite_value(match.group("value")) if match else None
        )

    @staticmethod
    def _finite_meter_value(value: str) -> float | None:
        parsed = FfmpegEbur128Backend._finite_value(value)
        return parsed if parsed is not None and parsed > -120.0 else None

    @staticmethod
    def _finite_value(value: str) -> float | None:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None

    @staticmethod
    def _effective_bit_depth(
        codec: str | None,
        sample_format: str | None,
    ) -> int | None:
        for value in (codec, sample_format):
            if not value:
                continue
            match = re.search(r"(?:s|u|f)(16|24|32|64)", value)
            if match:
                return int(match.group(1))
        return None

    @staticmethod
    def _last_nonempty_line(output: str) -> str:
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        return lines[-1] if lines else "no diagnostic output"
