"""Create an isolated stereo mastering project in a child REAPER process."""

from __future__ import annotations

import asyncio
import hashlib
import shutil
import time
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from reaper_mcp.errors import ErrorCode
from reaper_mcp.models.bridge import ErrorResponse
from reaper_mcp.models.mastering import (
    CreateStereoMasteringProjectRequest,
    StereoMasteringProject,
)
from reaper_mcp.services._bridge_result import validation_error


class MasteringProjectService:
    """Build one RPP without changing the interactive REAPER instance."""

    def __init__(
        self,
        *,
        allowed_project_roots: list[Path] | None = None,
        reaper_executable: Path | None = None,
        timeout_seconds: float = 60.0,
        poll_interval_seconds: float = 0.1,
    ) -> None:
        self.allowed_project_roots = [
            root.expanduser().resolve() for root in (allowed_project_roots or [])
        ]
        self.reaper_executable = (
            reaper_executable.expanduser().resolve(strict=False)
            if reaper_executable
            else None
        )
        self.timeout_seconds = timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds

    async def create_stereo_project(
        self,
        session: dict[str, Any],
        project_path: str,
    ) -> dict[str, Any]:
        """Create and verify a new isolated RPP for an approved stereo mix."""

        try:
            request = CreateStereoMasteringProjectRequest(
                session=session,
                project_path=Path(project_path).expanduser().resolve(strict=False),
            )
        except ValidationError as exc:
            return validation_error(
                exc,
                ErrorCode.INVALID_MASTERING_REQUEST,
                "The stereo mastering project request is invalid.",
                "Use a current stereo_mix session and a new approved .rpp path.",
            )
        path_error = self._validate_project_path(request.project_path)
        if path_error is not None:
            return path_error
        executable = self._resolve_reaper_executable()
        if executable is None:
            return self._error(
                ErrorCode.RENDER_EXECUTABLE_NOT_FOUND,
                "The REAPER executable was not found.",
                {"configured_executable": str(self.reaper_executable or "")},
                "Set REAPER_MCP_REAPER_EXECUTABLE to the REAPER binary.",
            )

        source_path = request.session.source.measurement.path
        expected_source_sha256 = request.session.source.measurement.source_sha256
        try:
            source_sha256 = await asyncio.to_thread(self._sha256, source_path)
        except OSError as exc:
            return self._source_error(source_path, str(exc))
        if source_sha256 != expected_source_sha256:
            return self._source_error(source_path, "source fingerprint changed")

        created = await self._run_reaper(
            executable,
            [source_path],
            request.project_path,
        )
        if not created["ok"]:
            request.project_path.unlink(missing_ok=True)
            return created
        source_sha256_after = await asyncio.to_thread(self._sha256, source_path)
        if source_sha256_after != source_sha256:
            request.project_path.unlink(missing_ok=True)
            return self._source_error(
                source_path, "source changed during project creation"
            )

        project = StereoMasteringProject(
            session_id=request.session.session_id,
            project_path=request.project_path,
            project_sha256=await asyncio.to_thread(self._sha256, request.project_path),
            source_path=source_path,
            source_sha256=source_sha256,
            size_bytes=request.project_path.stat().st_size,
            reaper_executable=executable,
        )
        return {
            "ok": True,
            "project": project.model_dump(mode="json"),
            "warnings": [],
        }

    async def create_media_sequence_project(
        self,
        media_paths: list[Path],
        project_path: Path,
    ) -> dict[str, Any]:
        """Create a new isolated RPP containing media in the supplied order."""

        path_error = self._validate_project_path(project_path)
        if path_error is not None:
            return path_error
        if not media_paths or any(not path.is_file() for path in media_paths):
            return self._project_failure(
                project_path,
                "Every ordered media source must be an existing file.",
            )
        executable = self._resolve_reaper_executable()
        if executable is None:
            return self._error(
                ErrorCode.RENDER_EXECUTABLE_NOT_FOUND,
                "The REAPER executable was not found.",
                {"configured_executable": str(self.reaper_executable or "")},
                "Set REAPER_MCP_REAPER_EXECUTABLE to the REAPER binary.",
            )
        created = await self._run_reaper(executable, media_paths, project_path)
        if not created["ok"]:
            project_path.unlink(missing_ok=True)
            return created
        return {
            "ok": True,
            "project": {
                "project_path": str(project_path),
                "project_sha256": await asyncio.to_thread(self._sha256, project_path),
                "size_bytes": project_path.stat().st_size,
                "media_paths": [str(path) for path in media_paths],
                "reaper_executable": str(executable),
            },
            "warnings": [],
        }

    def validate_project_destination(self, project_path: Path) -> dict[str, Any] | None:
        """Validate a child-project destination before preparing related assets."""

        return self._validate_project_path(project_path)

    async def _run_reaper(
        self,
        executable: Path,
        source_paths: list[Path],
        project_path: Path,
    ) -> dict[str, Any]:
        try:
            process = await asyncio.create_subprocess_exec(
                str(executable),
                "-newinst",
                "-nosplash",
                "-new",
                *(str(path) for path in source_paths),
                "-saveas",
                str(project_path),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except OSError as exc:
            return self._project_failure(project_path, str(exc))

        deadline = time.monotonic() + self.timeout_seconds
        stable_observations = 0
        previous_size = -1
        try:
            while time.monotonic() < deadline:
                if project_path.is_file():
                    size = project_path.stat().st_size
                    stable_observations = (
                        stable_observations + 1
                        if size > 0 and size == previous_size
                        else 0
                    )
                    previous_size = size
                    if stable_observations >= 2 and self._is_rpp(project_path):
                        return {"ok": True}
                if process.returncode is not None:
                    break
                await asyncio.sleep(self.poll_interval_seconds)
            return self._project_failure(
                project_path,
                "REAPER did not produce a stable valid RPP before timeout.",
            )
        finally:
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), 5.0)
                except TimeoutError:
                    process.kill()
                    await process.wait()

    def _validate_project_path(self, path: Path) -> dict[str, Any] | None:
        if path.suffix.lower() != ".rpp":
            return self._path_error(path, "Mastering project paths must use .rpp.")
        if not any(path.is_relative_to(root) for root in self.allowed_project_roots):
            return self._path_error(path, "The project path is outside allowed roots.")
        if not path.parent.is_dir():
            return self._path_error(
                path, "The project parent directory does not exist."
            )
        if path.exists():
            return self._path_error(path, "The project path already exists.")
        return None

    def _resolve_reaper_executable(self) -> Path | None:
        if self.reaper_executable is not None:
            return self.reaper_executable if self.reaper_executable.is_file() else None
        discovered = shutil.which("reaper")
        return Path(discovered).resolve() if discovered else None

    @staticmethod
    def _is_rpp(path: Path) -> bool:
        try:
            with path.open("rb") as project:
                return project.read(64).lstrip().startswith(b"<REAPER_PROJECT")
        except OSError:
            return False

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()

    def _project_failure(self, path: Path, reason: str) -> dict[str, Any]:
        return self._error(
            ErrorCode.MASTERING_PROJECT_CREATION_FAILED,
            "The isolated mastering project could not be created.",
            {"project_path": str(path), "reason": reason},
            "Check REAPER, the approved source, destination, and timeout.",
        )

    def _source_error(self, path: Path, reason: str) -> dict[str, Any]:
        return self._error(
            ErrorCode.MASTERING_SOURCE_CHANGED,
            "The approved mastering source is unavailable or changed.",
            {"source_path": str(path), "reason": reason},
            "Restore the approved source or create a new mastering session.",
        )

    def _path_error(self, path: Path, message: str) -> dict[str, Any]:
        return self._error(
            ErrorCode.PROJECT_PATH_NOT_ALLOWED,
            message,
            {"project_path": str(path)},
            "Choose a new .rpp path inside REAPER_MCP_ALLOWED_PROJECT_ROOTS.",
        )

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
