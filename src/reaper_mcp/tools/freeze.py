"""MCP track freeze tool registration."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from reaper_mcp.services.freeze_service import FreezeService


def register_freeze_tools(server: FastMCP, service: FreezeService) -> None:
    """Register verified track freeze tools."""

    @server.tool(
        name="get_track_freeze_state",
        description="Return one track's freeze count by stable track GUID.",
    )
    async def get_track_freeze_state(track_guid: str) -> dict[str, Any]:
        return await service.get_track_freeze_state(track_guid)

    @server.tool(
        name="freeze_track",
        description=(
            "Freeze one track to stereo by stable GUID and restore prior track "
            "selection. This may create media files and is one undoable action."
        ),
    )
    async def freeze_track(track_guid: str) -> dict[str, Any]:
        return await service.freeze_track(track_guid)

    @server.tool(
        name="unfreeze_track",
        description=(
            "Unfreeze one track by stable GUID and restore prior track selection. "
            "This mutates the project in one named undo block."
        ),
    )
    async def unfreeze_track(track_guid: str) -> dict[str, Any]:
        return await service.unfreeze_track(track_guid)
