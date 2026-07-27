"""MCP tempo-map tool registration."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from reaper_mcp.services.tempo_map_service import TempoMapService


def register_tempo_map_tools(server: FastMCP, service: TempoMapService) -> None:
    """Register guarded tempo-map tools."""

    @server.tool(name="list_tempo_markers", description="List tempo-map markers.")
    async def list_tempo_markers() -> dict[str, Any]:
        return await service.list_markers()

    @server.tool(
        name="create_tempo_marker",
        description="Create one tempo-map marker in one undo block.",
    )
    async def create_tempo_marker(
        position_seconds: float,
        bpm: float,
        numerator: int = 4,
        denominator: int = 4,
        linear: bool = False,
    ) -> dict[str, Any]:
        return await service.create_marker(
            position_seconds, bpm, numerator, denominator, linear
        )

    @server.tool(
        name="update_tempo_marker",
        description="Update one guarded tempo-map marker in one undo block.",
    )
    async def update_tempo_marker(
        index: int,
        expected_fingerprint: str,
        position_seconds: float,
        bpm: float,
        numerator: int = 4,
        denominator: int = 4,
        linear: bool = False,
    ) -> dict[str, Any]:
        return await service.update_marker(
            index,
            expected_fingerprint,
            position_seconds,
            bpm,
            numerator,
            denominator,
            linear,
        )

    @server.tool(
        name="delete_tempo_marker",
        description="Delete one guarded tempo-map marker in one undo block.",
    )
    async def delete_tempo_marker(
        index: int, expected_fingerprint: str
    ) -> dict[str, Any]:
        return await service.delete_marker(index, expected_fingerprint)
