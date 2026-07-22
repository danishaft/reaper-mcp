"""MCP health tool registration."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from reaper_mcp.services.health_service import HealthService


def register_health_tool(server: FastMCP, service: HealthService) -> None:
    """Register the `health_check` MCP tool."""

    @server.tool(
        name="health_check",
        description=(
            "Check the Python MCP server and REAPER Lua bridge. "
            "This tool does not change the REAPER project."
        ),
    )
    async def health_check() -> dict[str, Any]:
        return await service.check()
