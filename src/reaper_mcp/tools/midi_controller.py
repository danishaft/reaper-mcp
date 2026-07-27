"""MCP MIDI controller-event tool registration."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from reaper_mcp.services.midi_controller_service import MidiControllerService


def register_midi_controller_tools(
    server: FastMCP, service: MidiControllerService
) -> None:
    """Register guarded MIDI controller-event tools."""

    @server.tool(
        name="list_midi_controller_events",
        description="List MIDI CC, pitch-bend, aftertouch, and program-change events.",
    )
    async def list_midi_controller_events(take_guid: str) -> dict[str, Any]:
        return await service.list_events(take_guid)

    @server.tool(
        name="add_midi_controller_events",
        description="Add MIDI controller events in one undoable batch.",
    )
    async def add_midi_controller_events(
        take_guid: str, events: list[dict[str, Any]]
    ) -> dict[str, Any]:
        return await service.add_events(take_guid, events)

    @server.tool(
        name="update_midi_controller_event",
        description="Update one guarded MIDI controller event in one undo block.",
    )
    async def update_midi_controller_event(
        take_guid: str,
        index: int,
        expected_fingerprint: str,
        event: dict[str, Any],
    ) -> dict[str, Any]:
        return await service.update_event(take_guid, index, expected_fingerprint, event)

    @server.tool(
        name="delete_midi_controller_events",
        description="Delete guarded MIDI controller events in one undoable batch.",
    )
    async def delete_midi_controller_events(
        take_guid: str, events: list[dict[str, Any]]
    ) -> dict[str, Any]:
        return await service.delete_events(take_guid, events)
