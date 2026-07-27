"""Project control service."""

from typing import Any

from pydantic import ValidationError

from reaper_mcp.bridge.base import BridgeClient
from reaper_mcp.errors import ErrorCode
from reaper_mcp.models.bridge import BridgeResponse, ErrorResponse
from reaper_mcp.models.project_controls import (
    ProjectControlResult,
    SetGridRequest,
)


class ProjectControlsService:
    """Expose undo, redo, grid, metronome, and playback-rate controls."""

    def __init__(self, bridge_client: BridgeClient) -> None:
        self.bridge_client = bridge_client

    async def undo(self) -> dict[str, Any]:
        return await self._execute("undo")

    async def redo(self) -> dict[str, Any]:
        return await self._execute("redo")

    async def get_grid(self) -> dict[str, Any]:
        return await self._execute("get_grid")

    async def set_grid(
        self,
        division: float,
        swing: float = 0.0,
        swing_mode: int = 0,
        snap_enabled: bool = True,
    ) -> dict[str, Any]:
        try:
            request = SetGridRequest(
                division=division,
                swing=swing,
                swing_mode=swing_mode,
                snap_enabled=snap_enabled,
            )
        except ValidationError as exc:
            return self._validation_error(exc)
        return await self._execute("set_grid", request.model_dump(mode="json"))

    async def get_metronome(self) -> dict[str, Any]:
        return await self._execute("get_metronome")

    async def set_metronome(self, enabled: bool) -> dict[str, Any]:
        return await self._execute("set_metronome", {"enabled": enabled})

    async def get_playback_rate(self) -> dict[str, Any]:
        return await self._execute("get_playback_rate")

    async def set_playback_rate(self, rate: float) -> dict[str, Any]:
        if rate <= 0.0 or rate > 4.0:
            return self._validation_message("playback rate must be between 0 and 4")
        return await self._execute("set_playback_rate", {"rate": rate})

    async def _execute(
        self, command: str, args: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        response = await self.bridge_client.execute(command, args=args)
        if not response.ok:
            return self._error_result(response)
        try:
            result = ProjectControlResult.model_validate(response.result or {})
        except ValidationError as exc:
            return {
                "ok": False,
                "error": ErrorResponse(
                    code=ErrorCode.INVALID_BRIDGE_RESPONSE,
                    message=(
                        "The Lua bridge returned an invalid project-control payload."
                    ),
                    details={"errors": exc.errors(include_context=False)},
                    recoverable=True,
                    suggested_action="Restart the Lua bridge and retry the command.",
                ).model_dump(mode="json"),
                "warnings": response.warnings,
            }
        return {
            "ok": True,
            **result.model_dump(mode="json", exclude_none=True),
            "warnings": response.warnings,
        }

    def _error_result(self, response: BridgeResponse) -> dict[str, Any]:
        return {
            "ok": False,
            "error": response.error.model_dump(mode="json") if response.error else None,
            "warnings": response.warnings,
        }

    def _validation_error(self, exc: ValidationError) -> dict[str, Any]:
        return self._validation_message(str(exc))

    def _validation_message(self, message: str) -> dict[str, Any]:
        return {
            "ok": False,
            "error": ErrorResponse(
                code=ErrorCode.INVALID_NAVIGATION_REQUEST,
                message="The project-control request is invalid.",
                details={"message": message},
                recoverable=True,
                suggested_action=(
                    "Check grid, snap, metronome, and playback-rate values."
                ),
            ).model_dump(mode="json"),
            "warnings": [],
        }
