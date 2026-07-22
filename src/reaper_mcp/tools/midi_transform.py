"""MCP MIDI note transformation tool registration."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from reaper_mcp.models.midi_transform import ScaleDirection, ScaleMode
from reaper_mcp.services.midi_transform_service import MidiTransformService


def register_midi_transform_tools(
    server: FastMCP, service: MidiTransformService
) -> None:
    """Register guarded MIDI note transformation tools."""

    @server.tool(
        name="transpose_midi_notes",
        description=(
            "Transpose explicitly guarded MIDI notes by semitones. Out-of-range "
            "pitches are rejected before mutation."
        ),
    )
    async def transpose_midi_notes(
        take_guid: str,
        notes: list[dict[str, Any]],
        semitones: int,
    ) -> dict[str, Any]:
        return await service.transpose_midi_notes(take_guid, notes, semitones)

    @server.tool(
        name="nudge_midi_notes",
        description=(
            "Shift explicitly guarded MIDI notes by project beats while preserving "
            "duration. Notes cannot move before project start."
        ),
    )
    async def nudge_midi_notes(
        take_guid: str,
        notes: list[dict[str, Any]],
        offset_beats: float,
    ) -> dict[str, Any]:
        return await service.nudge_midi_notes(take_guid, notes, offset_beats)

    @server.tool(
        name="quantize_midi_notes",
        description=(
            "Quantize explicitly guarded MIDI note onsets to the project beat grid "
            "with strength and swing while preserving duration."
        ),
    )
    async def quantize_midi_notes(
        take_guid: str,
        notes: list[dict[str, Any]],
        grid_beats: float,
        strength: float = 1.0,
        swing: float = 0.0,
    ) -> dict[str, Any]:
        return await service.quantize_midi_notes(
            take_guid,
            notes,
            grid_beats,
            strength,
            swing,
        )

    @server.tool(
        name="humanize_midi_notes",
        description=(
            "Humanize explicitly guarded MIDI timing and velocity with bounded, "
            "deterministic offsets. The same seed and inputs produce the same plan."
        ),
    )
    async def humanize_midi_notes(
        take_guid: str,
        notes: list[dict[str, Any]],
        max_timing_offset_beats: float = 0.02,
        max_velocity_offset: int = 8,
        seed: int = 0,
    ) -> dict[str, Any]:
        return await service.humanize_midi_notes(
            take_guid,
            notes,
            max_timing_offset_beats,
            max_velocity_offset,
            seed,
        )

    @server.tool(
        name="snap_midi_notes_to_scale",
        description=(
            "Move explicitly guarded MIDI notes onto a named scale using nearest, "
            "upward, or downward pitch resolution."
        ),
    )
    async def snap_midi_notes_to_scale(
        take_guid: str,
        notes: list[dict[str, Any]],
        root_pitch_class: int,
        scale: ScaleMode = "major",
        direction: ScaleDirection = "nearest",
    ) -> dict[str, Any]:
        return await service.snap_midi_notes_to_scale(
            take_guid,
            notes,
            root_pitch_class,
            scale,
            direction,
        )

    @server.tool(
        name="shape_midi_note_velocities",
        description=(
            "Scale and offset explicitly guarded MIDI note velocities, clamped to "
            "the audible MIDI range from 1 to 127."
        ),
    )
    async def shape_midi_note_velocities(
        take_guid: str,
        notes: list[dict[str, Any]],
        factor: float = 1.0,
        offset: int = 0,
    ) -> dict[str, Any]:
        return await service.shape_midi_note_velocities(
            take_guid,
            notes,
            factor,
            offset,
        )

    @server.tool(
        name="remove_midi_note_overlaps",
        description=(
            "Trim overlaps among explicitly guarded MIDI notes sharing pitch and "
            "channel. Same-onset conflicts are rejected and no notes are deleted."
        ),
    )
    async def remove_midi_note_overlaps(
        take_guid: str,
        notes: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return await service.remove_midi_note_overlaps(take_guid, notes)
