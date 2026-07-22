"""MCP tempo and time signature tool registration."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from reaper_mcp.services.tempo_service import TempoService


def register_tempo_tools(server: FastMCP, service: TempoService) -> None:
    """Register REAPER tempo and time signature MCP tools."""

    @server.tool(
        name="get_tempo",
        description=(
            "Return the effective project tempo at the project start. "
            "This tool does not change the REAPER project."
        ),
    )
    async def get_tempo() -> dict[str, Any]:
        return await service.get_tempo()

    @server.tool(
        name="set_tempo",
        description=(
            "Set the project tempo in BPM. "
            "This mutates the project in one named undo block."
        ),
    )
    async def set_tempo(bpm: float) -> dict[str, Any]:
        return await service.set_tempo(bpm=bpm)

    @server.tool(
        name="get_time_signature",
        description=(
            "Return the effective project time signature at the project start. "
            "This tool does not change the REAPER project."
        ),
    )
    async def get_time_signature() -> dict[str, Any]:
        return await service.get_time_signature()

    @server.tool(
        name="set_time_signature",
        description=(
            "Set the project time signature at the project start. "
            "This mutates the project in one named undo block."
        ),
    )
    async def set_time_signature(
        numerator: int,
        denominator: int,
    ) -> dict[str, Any]:
        return await service.set_time_signature(
            numerator=numerator,
            denominator=denominator,
        )
