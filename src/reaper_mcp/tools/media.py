"""MCP media item tool registration."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from reaper_mcp.services.media_service import MediaService


def register_media_tools(server: FastMCP, service: MediaService) -> None:
    """Register media item MCP tools."""

    @server.tool(
        name="list_media_items",
        description=(
            "Return media items with stable item and take GUIDs. "
            "This tool does not change the REAPER project."
        ),
    )
    async def list_media_items() -> dict[str, Any]:
        return await service.list_media_items()

    @server.tool(
        name="create_midi_item",
        description=(
            "Create one empty MIDI item on a track using measure, beat, and "
            "length in beats. This mutates the project in one named undo block."
        ),
    )
    async def create_midi_item(
        track_guid: str,
        measure: int = 1,
        beat: float = 1.0,
        length_beats: float = 4.0,
        name: str = "MIDI item",
    ) -> dict[str, Any]:
        return await service.create_midi_item(
            track_guid=track_guid,
            measure=measure,
            beat=beat,
            length_beats=length_beats,
            name=name,
        )

    @server.tool(
        name="insert_audio_item",
        description=(
            "Insert one local audio file as a media item on a track using "
            "measure and beat. This mutates the project in one named undo block."
        ),
    )
    async def insert_audio_item(
        track_guid: str,
        source_path: str,
        measure: int = 1,
        beat: float = 1.0,
        name: str | None = None,
    ) -> dict[str, Any]:
        return await service.insert_audio_item(
            track_guid=track_guid,
            source_path=source_path,
            measure=measure,
            beat=beat,
            name=name,
        )

    @server.tool(
        name="move_media_item",
        description=(
            "Move one media item by stable item GUID to a measure and beat. "
            "This mutates the project in one named undo block."
        ),
    )
    async def move_media_item(
        item_guid: str,
        measure: int,
        beat: float = 1.0,
    ) -> dict[str, Any]:
        return await service.move_media_item(item_guid, measure, beat)

    @server.tool(
        name="resize_media_item",
        description=(
            "Set one media item's length in beats by stable item GUID. "
            "This mutates the project in one named undo block."
        ),
    )
    async def resize_media_item(
        item_guid: str,
        length_beats: float,
    ) -> dict[str, Any]:
        return await service.resize_media_item(item_guid, length_beats)

    @server.tool(
        name="duplicate_media_item",
        description=(
            "Duplicate one media item by stable item GUID and preserve the prior "
            "item selection. This mutates the project in one named undo block."
        ),
    )
    async def duplicate_media_item(item_guid: str) -> dict[str, Any]:
        return await service.duplicate_media_item(item_guid)

    @server.tool(
        name="split_media_item",
        description=(
            "Split one media item by stable item GUID at an absolute measure and "
            "beat. This mutates the project in one named undo block."
        ),
    )
    async def split_media_item(
        item_guid: str,
        measure: int,
        beat: float = 1.0,
    ) -> dict[str, Any]:
        return await service.split_media_item(item_guid, measure, beat)

    @server.tool(
        name="set_media_item_mute",
        description=(
            "Set one media item's mute state by stable item GUID. "
            "This mutates the project in one named undo block."
        ),
    )
    async def set_media_item_mute(item_guid: str, muted: bool) -> dict[str, Any]:
        return await service.set_media_item_mute(item_guid, muted)

    @server.tool(
        name="set_media_item_gain",
        description=(
            "Set one media item's linear gain from 0.0 to 4.0 by stable item "
            "GUID. This mutates the project in one named undo block."
        ),
    )
    async def set_media_item_gain(item_guid: str, gain: float) -> dict[str, Any]:
        return await service.set_media_item_gain(item_guid, gain)

    @server.tool(
        name="set_media_item_fade_in",
        description=(
            "Set one media item's manual fade-in length in seconds by stable "
            "item GUID. This mutates the project in one named undo block."
        ),
    )
    async def set_media_item_fade_in(
        item_guid: str, length_seconds: float
    ) -> dict[str, Any]:
        return await service.set_media_item_fade_in(item_guid, length_seconds)

    @server.tool(
        name="set_media_item_fade_out",
        description=(
            "Set one media item's manual fade-out length in seconds by stable "
            "item GUID. This mutates the project in one named undo block."
        ),
    )
    async def set_media_item_fade_out(
        item_guid: str, length_seconds: float
    ) -> dict[str, Any]:
        return await service.set_media_item_fade_out(item_guid, length_seconds)

    @server.tool(
        name="delete_media_item",
        description=(
            "Delete one media item by stable item GUID. "
            "This mutates the project in one named undo block."
        ),
    )
    async def delete_media_item(item_guid: str) -> dict[str, Any]:
        return await service.delete_media_item(item_guid)

    @server.tool(
        name="get_midi_notes",
        description=(
            "Return MIDI notes from one MIDI take by stable take GUID. "
            "This tool does not change the REAPER project."
        ),
    )
    async def get_midi_notes(take_guid: str) -> dict[str, Any]:
        return await service.get_midi_notes(take_guid=take_guid)

    @server.tool(
        name="add_midi_note",
        description=(
            "Insert one MIDI note into a MIDI take by stable take GUID. "
            "This mutates the project in one named undo block."
        ),
    )
    async def add_midi_note(
        take_guid: str,
        note: dict[str, Any],
    ) -> dict[str, Any]:
        return await service.add_midi_note(take_guid=take_guid, note=note)

    @server.tool(
        name="add_midi_notes",
        description=(
            "Insert multiple MIDI notes into one MIDI take by stable take GUID. "
            "This mutates the project in one named undo block."
        ),
    )
    async def add_midi_notes(
        take_guid: str,
        notes: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return await service.add_midi_notes(take_guid=take_guid, notes=notes)

    @server.tool(
        name="update_midi_note",
        description=(
            "Replace one MIDI note by note index after checking its expected "
            "fingerprint. This mutates the project in one named undo block."
        ),
    )
    async def update_midi_note(
        take_guid: str,
        note_index: int,
        expected_fingerprint: str,
        note: dict[str, Any],
    ) -> dict[str, Any]:
        return await service.update_midi_note(
            take_guid=take_guid,
            note_index=note_index,
            expected_fingerprint=expected_fingerprint,
            note=note,
        )

    @server.tool(
        name="delete_midi_notes",
        description=(
            "Delete MIDI notes by note index after checking each expected "
            "fingerprint. This mutates the project in one named undo block."
        ),
    )
    async def delete_midi_notes(
        take_guid: str,
        notes: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return await service.delete_midi_notes(take_guid=take_guid, notes=notes)
