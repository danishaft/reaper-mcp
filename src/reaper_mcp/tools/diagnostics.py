"""MCP diagnostics tool registration."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from reaper_mcp.services.diagnostics_service import DiagnosticsService


def register_diagnostics_tools(server: FastMCP, service: DiagnosticsService) -> None:
    """Register read-only diagnostic MCP tools."""

    @server.tool(
        name="get_reaper_version",
        description=(
            "Return the REAPER version reported by the Lua bridge. "
            "This tool does not change the REAPER project."
        ),
    )
    async def get_reaper_version() -> dict[str, Any]:
        return await service.get_reaper_version()

    @server.tool(
        name="get_project_info",
        description=(
            "Return basic information about the active REAPER project. "
            "This tool does not change the REAPER project."
        ),
    )
    async def get_project_info() -> dict[str, Any]:
        return await service.get_project_info()

    @server.tool(
        name="get_bridge_status",
        description=(
            "Return Lua bridge status and file transport diagnostics. "
            "This tool does not change the REAPER project."
        ),
    )
    async def get_bridge_status() -> dict[str, Any]:
        return await service.get_bridge_status()
