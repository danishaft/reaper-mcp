"""Read-only diagnostics service."""

from typing import Any

from reaper_mcp.bridge.base import BridgeClient


class DiagnosticsService:
    """Expose read-only bridge diagnostics."""

    def __init__(self, bridge_client: BridgeClient) -> None:
        self.bridge_client = bridge_client

    async def get_reaper_version(self) -> dict[str, Any]:
        """Return REAPER version information from the Lua bridge."""

        return await self._read_bridge_command("get_reaper_version")

    async def get_project_info(self) -> dict[str, Any]:
        """Return basic active project information from REAPER."""

        return await self._read_bridge_command("get_project_info")

    async def get_bridge_status(self) -> dict[str, Any]:
        """Return Lua bridge runtime and file transport diagnostics."""

        return await self._read_bridge_command("get_bridge_status")

    async def _read_bridge_command(self, command: str) -> dict[str, Any]:
        response = await self.bridge_client.execute(command)
        if response.ok:
            return {
                "ok": True,
                "result": response.result or {},
                "warnings": response.warnings,
            }

        return {
            "ok": False,
            "error": response.error.model_dump(mode="json") if response.error else None,
            "warnings": response.warnings,
        }
