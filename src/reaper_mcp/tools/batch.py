"""MCP batch mutation tool registration."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from reaper_mcp.services.batch_service import BatchService


def register_batch_tools(server: FastMCP, service: BatchService) -> None:
    """Register atomic batch tools."""

    @server.tool(
        name="batch_update_tracks",
        description=(
            "Apply multiple track property changes in one preflighted undo block."
        ),
    )
    async def batch_update_tracks(
        changes: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return await service.update_tracks(changes)
