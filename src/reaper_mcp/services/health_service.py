"""Health check service."""

from typing import Any

from reaper_mcp import __version__
from reaper_mcp.bridge.base import BridgeClient
from reaper_mcp.errors import ErrorCode
from reaper_mcp.models.bridge import BridgeResponse, ErrorResponse


class HealthService:
    """Report Python server and REAPER bridge health."""

    def __init__(self, bridge_client: BridgeClient) -> None:
        self.bridge_client = bridge_client

    async def check(self) -> dict[str, Any]:
        """Call the bridge health command and normalize the tool response."""

        response = await self.bridge_client.execute("health_check")
        if response.ok:
            return {
                "ok": True,
                "status": "ok",
                "server": self._server_info(),
                "bridge": response.result or {},
                "warnings": response.warnings,
            }

        error = self._normalize_bridge_error(response)
        return {
            "ok": False,
            "status": "bridge_unavailable",
            "server": self._server_info(),
            "error": error.model_dump(mode="json"),
            "warnings": response.warnings,
        }

    def _normalize_bridge_error(self, response: BridgeResponse) -> ErrorResponse:
        if response.error and response.error.code == ErrorCode.COMMAND_TIMEOUT:
            return ErrorResponse(
                code=ErrorCode.BRIDGE_NOT_RUNNING,
                message="The REAPER Lua bridge is not running.",
                details=response.error.details,
                recoverable=True,
                suggested_action="Start lua/reaper_mcp_bridge.lua in REAPER.",
            )
        if response.error:
            return response.error
        return ErrorResponse(
            code=ErrorCode.REAPER_NOT_AVAILABLE,
            message="REAPER bridge health could not be determined.",
            recoverable=True,
            suggested_action="Start REAPER and run the Lua bridge.",
        )

    def _server_info(self) -> dict[str, str]:
        return {"name": "reaper-mcp", "version": __version__}
