"""MCP tools for guarded REAPER fixed-lane playback selection."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from reaper_mcp.services.fixed_lane_service import FixedLaneService


def register_fixed_lane_tools(server: FastMCP, service: FixedLaneService) -> None:
    """Register fixed-lane inspection and whole-lane selection tools."""

    @server.tool(name="list_fixed_lanes")
    async def list_fixed_lanes(track_guid: str) -> dict[str, Any]:
        """Inspect lane names, playback states, items, and the current layout guard."""

        return await service.list_fixed_lanes(track_guid)

    @server.tool(name="select_fixed_lane")
    async def select_fixed_lane(
        track_guid: str,
        lane_index: int,
        expected_layout_fingerprint: str,
    ) -> dict[str, Any]:
        """Play one whole lane exclusively after verifying the observed layout."""

        return await service.select_fixed_lane(
            track_guid, lane_index, expected_layout_fingerprint
        )
