"""Transport control service."""

from typing import Any

from pydantic import ValidationError

from reaper_mcp.bridge.base import BridgeClient
from reaper_mcp.errors import ErrorCode
from reaper_mcp.models.bridge import BridgeResponse, CommandOptions, ErrorResponse
from reaper_mcp.models.transport import TransportActionResult


class TransportService:
    """Expose REAPER transport controls."""

    def __init__(self, bridge_client: BridgeClient) -> None:
        self.bridge_client = bridge_client

    async def play(self) -> dict[str, Any]:
        """Start playback."""

        return await self._execute_transport_command("play")

    async def stop(self) -> dict[str, Any]:
        """Stop playback when REAPER is not actively recording."""

        return await self._execute_transport_command("stop")

    async def stop_recording(self) -> dict[str, Any]:
        """Stop an active recording."""

        return await self._execute_transport_command(
            "stop_recording",
            options=CommandOptions(
                mutates_project=True,
                undo_label="Stop recording",
            ),
        )

    async def pause(self) -> dict[str, Any]:
        """Pause transport."""

        return await self._execute_transport_command("pause")

    async def record(self) -> dict[str, Any]:
        """Start recording."""

        return await self._execute_transport_command(
            "record",
            options=CommandOptions(
                mutates_project=True,
                undo_label="Record",
            ),
        )

    async def _execute_transport_command(
        self,
        command: str,
        options: CommandOptions | None = None,
    ) -> dict[str, Any]:
        response = await self.bridge_client.execute(command, options=options)
        if not response.ok:
            return self._error_result(response)

        try:
            result = TransportActionResult.model_validate(response.result or {})
        except ValidationError as exc:
            return {
                "ok": False,
                "error": ErrorResponse(
                    code=ErrorCode.INVALID_BRIDGE_RESPONSE,
                    message="The Lua bridge returned an invalid transport payload.",
                    details={"errors": exc.errors()},
                    recoverable=True,
                    suggested_action="Restart the Lua bridge and retry the command.",
                ).model_dump(mode="json"),
                "warnings": response.warnings,
            }

        return {
            "ok": True,
            "action": result.action,
            "transport": result.transport.model_dump(mode="json"),
            "may_create_media_items": result.may_create_media_items,
            "warnings": response.warnings,
        }

    def _error_result(self, response: BridgeResponse) -> dict[str, Any]:
        return {
            "ok": False,
            "error": response.error.model_dump(mode="json") if response.error else None,
            "warnings": response.warnings,
        }
