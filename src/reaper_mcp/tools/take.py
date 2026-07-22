"""MCP media take and comping tool registration."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from reaper_mcp.services.take_service import TakeService


def register_take_tools(server: FastMCP, service: TakeService) -> None:
    """Register stable-GUID take management tools."""

    @server.tool(name="list_item_takes")
    async def list_item_takes(item_guid: str) -> dict[str, Any]:
        """Return every take on one item, including the active take GUID."""

        return await service.list_item_takes(item_guid)

    @server.tool(name="add_empty_take")
    async def add_empty_take(item_guid: str, name: str = "Take") -> dict[str, Any]:
        """Add and activate one named empty take in a single undo action."""

        return await service.add_empty_take(item_guid, name)

    @server.tool(name="set_active_take")
    async def set_active_take(take_guid: str) -> dict[str, Any]:
        """Make one GUID-addressed take active in its parent item."""

        return await service.set_active_take(take_guid)

    @server.tool(name="rename_take")
    async def rename_take(take_guid: str, name: str) -> dict[str, Any]:
        """Rename one take by stable GUID."""

        return await service.rename_take(take_guid, name)

    @server.tool(name="set_take_volume")
    async def set_take_volume(take_guid: str, volume: float) -> dict[str, Any]:
        """Set take linear gain from 0.0 to 4.0 by stable GUID."""

        return await service.set_take_volume(take_guid, volume)

    @server.tool(name="set_take_pan")
    async def set_take_pan(take_guid: str, pan: float) -> dict[str, Any]:
        """Set take pan from -1.0 left to 1.0 right by stable GUID."""

        return await service.set_take_pan(take_guid, pan)

    @server.tool(name="set_take_pitch")
    async def set_take_pitch(take_guid: str, semitones: float) -> dict[str, Any]:
        """Set take pitch adjustment in semitones by stable GUID."""

        return await service.set_take_pitch(take_guid, semitones)

    @server.tool(name="set_take_playback_rate")
    async def set_take_playback_rate(
        take_guid: str,
        playback_rate: float,
        preserve_pitch: bool = True,
    ) -> dict[str, Any]:
        """Set take playback rate and explicit pitch-preservation behavior."""

        return await service.set_take_playback_rate(
            take_guid, playback_rate, preserve_pitch
        )

    @server.tool(name="crop_to_active_take")
    async def crop_to_active_take(
        item_guid: str,
        expected_active_take_guid: str,
        expected_take_count: int,
    ) -> dict[str, Any]:
        """Remove inactive takes after checking the active GUID and take count."""

        return await service.crop_to_active_take(
            item_guid, expected_active_take_guid, expected_take_count
        )
