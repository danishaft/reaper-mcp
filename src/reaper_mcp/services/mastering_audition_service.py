"""Prepare an isolated gain-matched mastering audition project."""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from pydantic import ValidationError

from reaper_mcp.errors import ErrorCode
from reaper_mcp.models.bridge import ErrorResponse
from reaper_mcp.models.mastering import (
    CreateMasteringAuditionRequest,
    MasteringAuditionAsset,
    MasteringAuditionProject,
)
from reaper_mcp.services._bridge_result import validation_error
from reaper_mcp.services.audio_measurement_backend import (
    AsyncioCommandRunner,
    CommandOutputLimitError,
    CommandRunner,
    CommandTimedOutError,
    MeasurementBackendUnavailableError,
)


class AuditionBackendError(RuntimeError):
    """An audition copy could not be created safely."""


@dataclass(frozen=True)
class AuditionCopyResult:
    """Observed FFmpeg identity for one prepared audition copy."""

    backend_name: str
    executable_path: Path
    version: str


class AuditionBackend(Protocol):
    """Create a level-adjusted float copy without changing its source."""

    async def create_copy(
        self,
        source_path: Path,
        output_path: Path,
        gain_db: float,
        *,
        start_seconds: float,
        duration_seconds: float | None,
    ) -> AuditionCopyResult:
        """Create one isolated audition asset."""


class IsolatedProjectService(Protocol):
    """Create child REAPER projects without changing the interactive instance."""

    def validate_project_destination(self, project_path: Path) -> dict[str, Any] | None:
        """Validate a new project path without writing."""

    async def create_media_sequence_project(
        self,
        media_paths: list[Path],
        project_path: Path,
    ) -> dict[str, Any]:
        """Create a new project containing media in order."""


class FfmpegAuditionBackend:
    """Render gain-matched 32-bit float WAV copies with bounded FFmpeg."""

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

    async def create_copy(
        self,
        source_path: Path,
        output_path: Path,
        gain_db: float,
        *,
        start_seconds: float,
        duration_seconds: float | None,
    ) -> AuditionCopyResult:
        """Create one non-normalized float copy at the exact audition gain."""

        resolved = shutil.which(self.executable)
        if resolved is None:
            raise MeasurementBackendUnavailableError(
                f"FFmpeg executable was not found: {self.executable}"
            )
        executable = Path(resolved).resolve()
        version = await self._version(executable)
        command = [
            str(executable),
            "-hide_banner",
            "-nostdin",
            "-n",
        ]
        if start_seconds > 0.0:
            command.extend(["-ss", f"{start_seconds:.9f}"])
        command.extend(["-i", str(source_path)])
        if duration_seconds is not None:
            command.extend(["-t", f"{duration_seconds:.9f}"])
        command.extend(
            [
                "-map_metadata",
                "-1",
                "-af",
                f"volume={gain_db:.9f}dB:precision=double",
                "-c:a",
                "pcm_f32le",
                str(output_path),
            ]
        )
        try:
            completed = await self.runner.run(
                command,
                timeout_seconds=self.timeout_seconds,
                max_output_bytes=self.max_output_bytes,
            )
        except (CommandTimedOutError, CommandOutputLimitError) as exc:
            raise AuditionBackendError(str(exc)) from exc
        if completed.returncode != 0:
            raise AuditionBackendError(
                f"FFmpeg returned {completed.returncode}: "
                f"{self._last_line(completed.output)}"
            )
        if not output_path.is_file() or output_path.stat().st_size <= 0:
            raise AuditionBackendError(
                "FFmpeg did not create a non-empty audition WAV."
            )
        return AuditionCopyResult(
            backend_name="ffmpeg_gain_matched_float_wav",
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
            raise AuditionBackendError(str(exc)) from exc
        first_line = result.output.splitlines()[0] if result.output else ""
        if result.returncode != 0 or not first_line.startswith("ffmpeg version "):
            raise AuditionBackendError("The FFmpeg version check failed.")
        return first_line.removeprefix("ffmpeg version ").split(maxsplit=1)[0]

    @staticmethod
    def _last_line(output: str) -> str:
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        return lines[-1] if lines else "no diagnostic output"


class MasteringAuditionService:
    """Verify candidates, create gain-matched copies, and build one child RPP."""

    def __init__(
        self,
        backend: AuditionBackend,
        project_service: IsolatedProjectService,
        *,
        allowed_source_roots: list[Path] | None = None,
    ) -> None:
        self.backend = backend
        self.project_service = project_service
        self.allowed_source_roots = [
            root.expanduser().resolve() for root in (allowed_source_roots or [])
        ]

    async def prepare(
        self,
        candidate_a: dict[str, Any],
        candidate_b: dict[str, Any],
        comparison: dict[str, Any],
        project_path: str,
        *,
        blind_labels: bool = True,
        excerpt_start_seconds: float = 0.0,
        excerpt_duration_seconds: float | None = None,
    ) -> dict[str, Any]:
        """Create an isolated sequential A/B project or clean up every output."""

        resolved_project_path = Path(project_path).expanduser().resolve(strict=False)
        try:
            request = CreateMasteringAuditionRequest(
                candidates=(candidate_a, candidate_b),
                comparison=comparison,
                project_path=resolved_project_path,
                blind_labels=blind_labels,
                excerpt_start_seconds=excerpt_start_seconds,
                excerpt_duration_seconds=excerpt_duration_seconds,
            )
        except ValidationError as exc:
            return validation_error(
                exc,
                ErrorCode.MASTERING_CANDIDATE_INVALID,
                "The mastering audition request is invalid.",
                "Use the exact two measured candidates and their comparison.",
            )
        path_error = self.project_service.validate_project_destination(
            request.project_path
        )
        if path_error is not None:
            return path_error
        asset_directory = request.project_path.with_suffix(".audition-assets")
        if asset_directory.exists():
            return self._error(
                ErrorCode.PROJECT_PATH_NOT_ALLOWED,
                "The audition asset directory already exists.",
                {"asset_directory": str(asset_directory)},
                "Choose a new audition project path.",
            )

        candidate_by_id = {
            candidate.candidate_id: candidate for candidate in request.candidates
        }
        source_error = await self._validate_sources(candidate_by_id)
        if source_error is not None:
            return source_error

        created_files: list[Path] = []
        assets: list[MasteringAuditionAsset] = []
        backend_result = None
        try:
            asset_directory.mkdir()
            for index, entry in enumerate(request.comparison.entries):
                candidate = candidate_by_id[entry.candidate_id]
                label = chr(ord("A") + index)
                output_path = asset_directory / f"Audition-{label}.wav"
                created_files.append(output_path)
                backend_result = await self.backend.create_copy(
                    entry.rendered_path,
                    output_path,
                    entry.audition_gain_db,
                    start_seconds=request.excerpt_start_seconds,
                    duration_seconds=request.excerpt_duration_seconds,
                )
                source_sha256 = await asyncio.to_thread(
                    self._sha256, entry.rendered_path
                )
                if source_sha256 != candidate.rendered_sha256:
                    raise AuditionBackendError(
                        f"Candidate {candidate.candidate_id} changed during audition."
                    )
                assets.append(
                    MasteringAuditionAsset(
                        display_label=label
                        if request.blind_labels
                        else candidate.label,
                        candidate_id=candidate.candidate_id,
                        source_path=entry.rendered_path,
                        source_sha256=source_sha256,
                        audition_path=output_path,
                        audition_sha256=await asyncio.to_thread(
                            self._sha256, output_path
                        ),
                        audition_gain_db=entry.audition_gain_db,
                    )
                )
            project_result = await self.project_service.create_media_sequence_project(
                [asset.audition_path for asset in assets],
                request.project_path,
            )
            if not project_result["ok"]:
                self._cleanup(created_files, asset_directory)
                return project_result
            assert backend_result is not None
            project = project_result["project"]
            payload = {
                "comparison_id": request.comparison.comparison_id,
                "project_path": request.project_path,
                "project_sha256": project["project_sha256"],
                "asset_directory": asset_directory,
                "assets": [asset.model_dump(mode="json") for asset in assets],
                "blind_labels": request.blind_labels,
                "backend_name": backend_result.backend_name,
                "backend_executable": backend_result.executable_path,
                "backend_version": backend_result.version,
                "reaper_executable": project["reaper_executable"],
            }
            fingerprint = self._canonical_sha256(payload)
            audition = MasteringAuditionProject(
                audition_id=f"ma_{fingerprint[:24]}",
                **payload,
            )
        except (
            AuditionBackendError,
            MeasurementBackendUnavailableError,
            CommandTimedOutError,
            CommandOutputLimitError,
            OSError,
            ValidationError,
        ) as exc:
            request.project_path.unlink(missing_ok=True)
            self._cleanup(created_files, asset_directory)
            return self._error(
                ErrorCode.MASTERING_AUDITION_FAILED,
                "The isolated mastering audition could not be prepared.",
                {"reason": str(exc)},
                "Fix the candidate, FFmpeg, REAPER, or destination and retry.",
            )
        return {
            "ok": True,
            "audition": audition.model_dump(mode="json"),
            "warnings": [
                "The child-created project plays A then B. Candidate identity "
                "remains in this result even when project labels are blind."
            ],
        }

    async def _validate_sources(
        self,
        candidate_by_id: dict[str, Any],
    ) -> dict[str, Any] | None:
        for candidate in candidate_by_id.values():
            path = Path(candidate.render.primary_output_path).resolve(strict=False)
            if not any(path.is_relative_to(root) for root in self.allowed_source_roots):
                return self._error(
                    ErrorCode.RENDER_OUTPUT_NOT_ALLOWED,
                    "A candidate path is outside allowed source roots.",
                    {"path": str(path)},
                    "Use candidates rendered inside an allowed render root.",
                )
            if not path.is_file():
                return self._source_changed(path, "candidate file is missing")
            actual_sha256 = await asyncio.to_thread(self._sha256, path)
            if (
                actual_sha256 != candidate.rendered_sha256
                or candidate.measurement.source_sha256 != candidate.rendered_sha256
            ):
                return self._source_changed(path, "candidate fingerprint changed")
        return None

    def _source_changed(self, path: Path, reason: str) -> dict[str, Any]:
        return self._error(
            ErrorCode.MASTERING_SOURCE_CHANGED,
            "A compared candidate is unavailable or changed.",
            {"path": str(path), "reason": reason},
            "Re-render, remeasure, and compare the current candidates.",
        )

    @staticmethod
    def _cleanup(files: list[Path], directory: Path) -> None:
        for path in reversed(files):
            path.unlink(missing_ok=True)
        with suppress(OSError):
            directory.rmdir()

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _canonical_sha256(payload: dict[str, Any]) -> str:
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            default=str,
        ).encode()
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _error(
        code: ErrorCode,
        message: str,
        details: dict[str, Any],
        suggested_action: str,
    ) -> dict[str, Any]:
        return {
            "ok": False,
            "error": ErrorResponse(
                code=code,
                message=message,
                details=details,
                recoverable=True,
                suggested_action=suggested_action,
            ).model_dump(mode="json"),
            "warnings": [],
        }
