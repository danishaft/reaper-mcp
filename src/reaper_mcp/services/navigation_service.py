"""Project navigation and save service."""

from pathlib import Path
from typing import Any

from pydantic import ValidationError

from reaper_mcp.bridge.base import BridgeClient
from reaper_mcp.errors import ErrorCode
from reaper_mcp.models.navigation import (
    ProjectNavigationResult,
    ProjectNavigationSnapshot,
    SaveProjectAsRequest,
    SetEditCursorRequest,
    SetTimelineRangeRequest,
)
from reaper_mcp.services._bridge_result import (
    bridge_error,
    invalid_payload,
    validation_error,
)


class NavigationService:
    """Expose cursor, selection, loop, and project save operations."""

    def __init__(
        self,
        bridge_client: BridgeClient,
        allowed_project_roots: list[Path] | None = None,
    ) -> None:
        self.bridge_client = bridge_client
        self.allowed_project_roots = [
            root.expanduser().resolve() for root in (allowed_project_roots or [])
        ]

    async def get_project_navigation(self) -> dict[str, Any]:
        response = await self.bridge_client.execute("get_project_navigation")
        if not response.ok:
            return bridge_error(response)
        try:
            result = ProjectNavigationSnapshot.model_validate(response.result or {})
        except ValidationError as exc:
            return invalid_payload(response, exc, "project navigation")
        return {
            "ok": True,
            **result.model_dump(mode="json"),
            "warnings": response.warnings,
        }

    async def set_edit_cursor(
        self,
        position_seconds: float,
        move_view: bool = True,
        seek_playback: bool = False,
    ) -> dict[str, Any]:
        try:
            request = SetEditCursorRequest(
                position_seconds=position_seconds,
                move_view=move_view,
                seek_playback=seek_playback,
            )
        except ValidationError as exc:
            return self._validation_error(exc)
        return await self._change("set_edit_cursor", request.model_dump(mode="json"))

    async def set_time_selection(
        self, start_seconds: float, end_seconds: float
    ) -> dict[str, Any]:
        return await self._set_range("set_time_selection", start_seconds, end_seconds)

    async def clear_time_selection(self) -> dict[str, Any]:
        return await self._change("clear_time_selection")

    async def set_loop_points(
        self, start_seconds: float, end_seconds: float
    ) -> dict[str, Any]:
        return await self._set_range("set_loop_points", start_seconds, end_seconds)

    async def set_loop_enabled(self, enabled: bool) -> dict[str, Any]:
        return await self._change("set_loop_enabled", {"enabled": enabled})

    async def save_project(self) -> dict[str, Any]:
        return await self._change("save_project")

    async def save_project_as(
        self, project_path: str, overwrite: bool = False
    ) -> dict[str, Any]:
        try:
            request = SaveProjectAsRequest(
                project_path=Path(project_path).expanduser().resolve(strict=False),
                overwrite=overwrite,
            )
        except ValidationError as exc:
            return self._validation_error(exc)
        path = request.project_path
        if path.suffix.lower() != ".rpp":
            return self._path_error(path, "Project paths must use the .rpp suffix.")
        if not self._is_allowed(path):
            return self._path_error(path, "The project path is outside allowed roots.")
        if not path.parent.is_dir():
            return self._path_error(
                path, "The project parent directory does not exist."
            )
        if path.exists() and not request.overwrite:
            return self._path_error(path, "The project path already exists.")
        return await self._change(
            "save_project_as",
            {"project_path": str(path), "overwrite": request.overwrite},
        )

    async def _set_range(
        self, command: str, start_seconds: float, end_seconds: float
    ) -> dict[str, Any]:
        try:
            request = SetTimelineRangeRequest(
                start_seconds=start_seconds, end_seconds=end_seconds
            )
        except ValidationError as exc:
            return self._validation_error(exc)
        return await self._change(command, request.model_dump(mode="json"))

    async def _change(
        self, command: str, args: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        response = await self.bridge_client.execute(command, args=args)
        if not response.ok:
            return bridge_error(response)
        try:
            result = ProjectNavigationResult.model_validate(response.result or {})
        except ValidationError as exc:
            return invalid_payload(response, exc, "project navigation result")
        return {
            "ok": True,
            **result.model_dump(mode="json"),
            "warnings": response.warnings,
        }

    def _is_allowed(self, path: Path) -> bool:
        return any(path.is_relative_to(root) for root in self.allowed_project_roots)

    def _validation_error(self, exc: ValidationError) -> dict[str, Any]:
        return validation_error(
            exc,
            ErrorCode.INVALID_NAVIGATION_REQUEST,
            "The project navigation request is invalid.",
            "Check timeline positions and project path values.",
        )

    def _path_error(self, path: Path, message: str) -> dict[str, Any]:
        return {
            "ok": False,
            "error": {
                "code": ErrorCode.PROJECT_PATH_NOT_ALLOWED,
                "message": message,
                "details": {"project_path": str(path)},
                "recoverable": True,
                "suggested_action": (
                    "Choose a .rpp path inside REAPER_MCP_ALLOWED_PROJECT_ROOTS."
                ),
            },
            "warnings": [],
        }
