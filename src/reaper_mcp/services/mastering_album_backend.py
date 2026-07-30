"""Audio asset backend for multi-song mastering sequences."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from reaper_mcp.services.audio_measurement_backend import (
    AsyncioCommandRunner,
    CommandOutputLimitError,
    CommandRunner,
    CommandTimedOutError,
    MeasurementBackendUnavailableError,
)


class AlbumBackendError(RuntimeError):
    """An album sequence asset could not be created."""


@dataclass(frozen=True)
class AlbumAssetResult:
    """Observed backend identity for one prepared sequence asset."""

    backend_name: str
    executable_path: Path
    version: str


class AlbumAssetBackend(Protocol):
    """Create one float sequence copy with only approved gap/fade intent."""

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
        """Create one sequence asset."""


class FfmpegAlbumAssetBackend:
    """Prepare sample-accurate gap/fade copies as 32-bit float WAV."""

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
        """Create one non-dithered float copy."""

        resolved = shutil.which(self.executable)
        if resolved is None:
            raise MeasurementBackendUnavailableError(
                f"FFmpeg executable was not found: {self.executable}"
            )
        executable = Path(resolved).resolve()
        version = await self._version(executable)
        filters = []
        if fade_in_seconds > 0.0:
            filters.append(f"afade=t=in:st=0:d={fade_in_seconds:.9f}")
        if fade_out_seconds > 0.0:
            fade_start = duration_seconds - fade_out_seconds
            filters.append(f"afade=t=out:st={fade_start:.9f}:d={fade_out_seconds:.9f}")
        gap_samples = round(gap_before_seconds * sample_rate_hz)
        if gap_samples > 0:
            filters.append(f"adelay=delays={gap_samples}S:all=1")
        if not filters:
            filters.append("anull")
        command = [
            str(executable),
            "-hide_banner",
            "-nostdin",
            "-n",
            "-i",
            str(source_path),
            "-map_metadata",
            "-1",
            "-af",
            ",".join(filters),
            "-ar",
            str(sample_rate_hz),
            "-c:a",
            "pcm_f32le",
            str(output_path),
        ]
        try:
            completed = await self.runner.run(
                command,
                timeout_seconds=self.timeout_seconds,
                max_output_bytes=self.max_output_bytes,
            )
        except (CommandTimedOutError, CommandOutputLimitError) as exc:
            raise AlbumBackendError(str(exc)) from exc
        if completed.returncode != 0:
            raise AlbumBackendError(
                f"FFmpeg returned {completed.returncode}: "
                f"{self._last_line(completed.output)}"
            )
        if not output_path.is_file() or output_path.stat().st_size <= 0:
            raise AlbumBackendError("FFmpeg did not create an album sequence asset.")
        return AlbumAssetResult(
            backend_name="ffmpeg_album_float_sequence",
            executable_path=executable,
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
            raise AlbumBackendError(str(exc)) from exc
        first_line = result.output.splitlines()[0] if result.output else ""
        if result.returncode != 0 or not first_line.startswith("ffmpeg version "):
            raise AlbumBackendError("The FFmpeg version check failed.")
        return first_line.removeprefix("ffmpeg version ").split(maxsplit=1)[0]

    @staticmethod
    def _last_line(output: str) -> str:
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        return lines[-1] if lines else "no diagnostic output"
