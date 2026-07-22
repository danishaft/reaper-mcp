"""MCP track automation tool registration."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from reaper_mcp.models.automation import AutomationMode, EnvelopeType
from reaper_mcp.services.automation_service import AutomationService


def register_automation_tools(server: FastMCP, service: AutomationService) -> None:
    """Register guarded track envelope and automation mode tools."""

    @server.tool(name="list_track_envelopes")
    async def list_track_envelopes(track_guid: str) -> dict[str, Any]:
        """Return existing track envelopes with stable envelope GUIDs."""

        return await service.list_track_envelopes(track_guid)

    @server.tool(name="ensure_track_envelope")
    async def ensure_track_envelope(
        track_guid: str, envelope_type: EnvelopeType
    ) -> dict[str, Any]:
        """Create or return one supported built-in track envelope."""

        return await service.ensure_track_envelope(track_guid, envelope_type)

    @server.tool(name="get_envelope_points")
    async def get_envelope_points(
        track_guid: str, envelope_guid: str
    ) -> dict[str, Any]:
        """Return guarded points for one track envelope."""

        return await service.get_envelope_points(track_guid, envelope_guid)

    @server.tool(name="add_envelope_points")
    async def add_envelope_points(
        track_guid: str,
        envelope_guid: str,
        points: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Insert an envelope point batch in one sorted undo transaction."""

        return await service.add_envelope_points(track_guid, envelope_guid, points)

    @server.tool(name="update_envelope_point")
    async def update_envelope_point(
        track_guid: str,
        envelope_guid: str,
        point_index: int,
        expected_fingerprint: str,
        time_seconds: float | None = None,
        value: float | None = None,
        shape: int | None = None,
        tension: float | None = None,
        selected: bool | None = None,
    ) -> dict[str, Any]:
        """Update one envelope point after checking its current fingerprint."""

        return await service.update_envelope_point(
            track_guid,
            envelope_guid,
            point_index,
            expected_fingerprint,
            time_seconds=time_seconds,
            value=value,
            shape=shape,
            tension=tension,
            selected=selected,
        )

    @server.tool(name="delete_envelope_points")
    async def delete_envelope_points(
        track_guid: str,
        envelope_guid: str,
        points: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Delete explicitly guarded envelope points in one undo transaction."""

        return await service.delete_envelope_points(track_guid, envelope_guid, points)

    @server.tool(name="delete_envelope_points_in_range")
    async def delete_envelope_points_in_range(
        track_guid: str,
        envelope_guid: str,
        start_seconds: float,
        end_seconds: float,
    ) -> dict[str, Any]:
        """Delete envelope points in a validated half-open timeline range."""

        return await service.delete_envelope_points_in_range(
            track_guid, envelope_guid, start_seconds, end_seconds
        )

    @server.tool(name="get_track_automation_mode")
    async def get_track_automation_mode(track_guid: str) -> dict[str, Any]:
        """Return one track's automation mode without changing it."""

        return await service.get_track_automation_mode(track_guid)

    @server.tool(name="set_track_automation_mode")
    async def set_track_automation_mode(
        track_guid: str, mode: AutomationMode
    ) -> dict[str, Any]:
        """Set one track's automation mode in a named undo transaction."""

        return await service.set_track_automation_mode(track_guid, mode)
