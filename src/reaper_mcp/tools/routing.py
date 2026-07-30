"""MCP track routing tool registration."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from reaper_mcp.services.routing_service import RoutingService


def register_routing_tools(server: FastMCP, service: RoutingService) -> None:
    """Register guarded track send tools."""

    @server.tool(
        name="list_track_sends",
        description=(
            "Return track sends with guarded source, slot, and destination identity."
        ),
    )
    async def list_track_sends(source_track_guid: str) -> dict[str, Any]:
        return await service.list_track_sends(source_track_guid)

    @server.tool(
        name="create_track_send",
        description=(
            "Create a send between stable source and destination track GUIDs. "
            "This mutates the project in one named undo block."
        ),
    )
    async def create_track_send(
        source_track_guid: str,
        destination_track_guid: str,
        volume: float = 1.0,
        pan: float = 0.0,
        muted: bool = False,
    ) -> dict[str, Any]:
        return await service.create_track_send(
            source_track_guid,
            destination_track_guid,
            volume,
            pan,
            muted,
        )

    @server.tool(
        name="set_track_send",
        description=(
            "Set send volume, pan, or mute after checking its expected "
            "destination GUID. This mutates the project in one named undo block."
        ),
    )
    async def set_track_send(
        source_track_guid: str,
        send_index: int,
        expected_destination_track_guid: str,
        volume: float | None = None,
        pan: float | None = None,
        muted: bool | None = None,
    ) -> dict[str, Any]:
        return await service.set_track_send(
            source_track_guid,
            send_index,
            expected_destination_track_guid,
            volume=volume,
            pan=pan,
            muted=muted,
        )

    @server.tool(
        name="remove_track_send",
        description=(
            "Remove a send after checking its expected destination GUID. "
            "This mutates the project in one named undo block."
        ),
    )
    async def remove_track_send(
        source_track_guid: str,
        send_index: int,
        expected_destination_track_guid: str,
    ) -> dict[str, Any]:
        return await service.remove_track_send(
            source_track_guid,
            send_index,
            expected_destination_track_guid,
        )

    @server.tool(
        name="setup_sidechain",
        description=(
            "Create a guarded source-to-destination sidechain send on channels "
            "3/4 in one named undo block."
        ),
    )
    async def setup_sidechain(
        source_track_guid: str,
        destination_track_guid: str,
        amount: float = 1.0,
    ) -> dict[str, Any]:
        return await service.setup_sidechain(
            source_track_guid, destination_track_guid, amount
        )

    @server.tool(
        name="configure_reference_track",
        description=(
            "Route one track directly to a stereo hardware output and disable "
            "its master send so reference audio bypasses master-bus FX. The "
            "track fader, pan, mute, and solo still control auditioning. This "
            "mutates the project in one named undo block."
        ),
    )
    async def configure_reference_track(
        track_guid: str,
        hardware_output_pair: int = 1,
        volume: float = 1.0,
        pan: float = 0.0,
    ) -> dict[str, Any]:
        return await service.configure_reference_track(
            track_guid,
            hardware_output_pair,
            volume,
            pan,
        )
