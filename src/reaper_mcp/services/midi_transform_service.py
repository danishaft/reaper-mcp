"""Guarded MIDI note transformation service."""

import math
from typing import Any

from pydantic import ValidationError

from reaper_mcp.bridge.base import BridgeClient
from reaper_mcp.errors import ErrorCode
from reaper_mcp.models.bridge import BridgeResponse, CommandOptions, ErrorResponse
from reaper_mcp.models.midi_transform import (
    HumanizeMidiNotesBridgeRequest,
    HumanizeMidiNotesRequest,
    MidiTransformResult,
    MidiTransformTargetRequest,
    NudgeMidiNotesRequest,
    QuantizeMidiNotesRequest,
    RemoveMidiNoteOverlapsRequest,
    ScaleDirection,
    ScaleMode,
    ShapeMidiNoteVelocitiesRequest,
    SnapMidiNotesToScaleRequest,
    TransposeMidiNotesRequest,
)


class MidiTransformService:
    """Apply deterministic transforms to explicitly guarded MIDI notes."""

    def __init__(self, bridge_client: BridgeClient) -> None:
        self.bridge_client = bridge_client

    async def transpose_midi_notes(
        self,
        take_guid: str,
        notes: list[dict[str, Any]],
        semitones: int,
    ) -> dict[str, Any]:
        """Transpose guarded notes without clamping out-of-range pitches."""

        return await self._validate_and_execute(
            TransposeMidiNotesRequest,
            {"take_guid": take_guid, "notes": notes, "semitones": semitones},
            "transpose_midi_notes",
            "Transpose MIDI notes",
        )

    async def nudge_midi_notes(
        self,
        take_guid: str,
        notes: list[dict[str, Any]],
        offset_beats: float,
    ) -> dict[str, Any]:
        """Shift guarded notes in project beats while preserving duration."""

        return await self._validate_and_execute(
            NudgeMidiNotesRequest,
            {
                "take_guid": take_guid,
                "notes": notes,
                "offset_beats": offset_beats,
            },
            "nudge_midi_notes",
            "Nudge MIDI notes",
        )

    async def quantize_midi_notes(
        self,
        take_guid: str,
        notes: list[dict[str, Any]],
        grid_beats: float,
        strength: float = 1.0,
        swing: float = 0.0,
    ) -> dict[str, Any]:
        """Quantize guarded note onsets to the project beat grid."""

        return await self._validate_and_execute(
            QuantizeMidiNotesRequest,
            {
                "take_guid": take_guid,
                "notes": notes,
                "grid_beats": grid_beats,
                "strength": strength,
                "swing": swing,
            },
            "quantize_midi_notes",
            "Quantize MIDI notes",
        )

    async def humanize_midi_notes(
        self,
        take_guid: str,
        notes: list[dict[str, Any]],
        max_timing_offset_beats: float = 0.02,
        max_velocity_offset: int = 8,
        seed: int = 0,
    ) -> dict[str, Any]:
        """Humanize guarded notes with reproducible bounded offsets."""

        try:
            request = HumanizeMidiNotesRequest(
                take_guid=take_guid,
                notes=notes,
                max_timing_offset_beats=max_timing_offset_beats,
                max_velocity_offset=max_velocity_offset,
                seed=seed,
            )
            timing_offsets, velocity_offsets = self._humanize_offsets(request)
            bridge_request = HumanizeMidiNotesBridgeRequest(
                **request.model_dump(mode="python"),
                timing_offsets=timing_offsets,
                velocity_offsets=velocity_offsets,
            )
        except ValidationError as exc:
            return self._validation_error_result(exc)
        return await self._execute(
            bridge_request,
            "humanize_midi_notes",
            "Humanize MIDI notes",
        )

    async def snap_midi_notes_to_scale(
        self,
        take_guid: str,
        notes: list[dict[str, Any]],
        root_pitch_class: int,
        scale: ScaleMode = "major",
        direction: ScaleDirection = "nearest",
    ) -> dict[str, Any]:
        """Move guarded notes onto a named pitch-class scale."""

        return await self._validate_and_execute(
            SnapMidiNotesToScaleRequest,
            {
                "take_guid": take_guid,
                "notes": notes,
                "root_pitch_class": root_pitch_class,
                "scale": scale,
                "direction": direction,
            },
            "snap_midi_notes_to_scale",
            "Snap MIDI notes to scale",
        )

    async def shape_midi_note_velocities(
        self,
        take_guid: str,
        notes: list[dict[str, Any]],
        factor: float = 1.0,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Scale and offset guarded note velocities with MIDI-safe clamping."""

        return await self._validate_and_execute(
            ShapeMidiNoteVelocitiesRequest,
            {
                "take_guid": take_guid,
                "notes": notes,
                "factor": factor,
                "offset": offset,
            },
            "shape_midi_note_velocities",
            "Shape MIDI note velocities",
        )

    async def remove_midi_note_overlaps(
        self,
        take_guid: str,
        notes: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Trim overlaps among guarded notes that share pitch and channel."""

        return await self._validate_and_execute(
            RemoveMidiNoteOverlapsRequest,
            {"take_guid": take_guid, "notes": notes},
            "remove_midi_note_overlaps",
            "Remove MIDI note overlaps",
        )

    async def _validate_and_execute(
        self,
        request_type: type[MidiTransformTargetRequest],
        request_data: dict[str, Any],
        command: str,
        undo_label: str,
    ) -> dict[str, Any]:
        try:
            request = request_type.model_validate(request_data)
        except ValidationError as exc:
            return self._validation_error_result(exc)
        return await self._execute(request, command, undo_label)

    async def _execute(
        self,
        request: MidiTransformTargetRequest,
        command: str,
        undo_label: str,
    ) -> dict[str, Any]:
        response = await self.bridge_client.execute(
            command,
            args=request.model_dump(mode="json"),
            options=CommandOptions(mutates_project=True, undo_label=undo_label),
        )
        if not response.ok:
            return self._error_result(response)
        try:
            result = MidiTransformResult.model_validate(response.result or {})
        except ValidationError as exc:
            return self._invalid_payload_result(response, exc)
        return {
            "ok": True,
            "take_guid": result.take_guid,
            "notes": [note.model_dump(mode="json") for note in result.notes],
            "note_count": result.note_count,
            "transformed_count": result.transformed_count,
            "changes_applied": result.changes_applied,
            "warnings": response.warnings,
        }

    @staticmethod
    def _humanize_offsets(
        request: HumanizeMidiNotesRequest,
    ) -> tuple[list[float], list[int]]:
        state = (request.seed % 2_147_483_646) + 1

        def next_unit() -> float:
            nonlocal state
            state = (state * 48_271) % 2_147_483_647
            return state / 2_147_483_647

        timing_offsets: list[float] = []
        velocity_offsets: list[int] = []
        for _ in request.notes:
            timing_unit = next_unit() + next_unit() - 1.0
            velocity_unit = next_unit() + next_unit() - 1.0
            timing_offsets.append(
                round(timing_unit * request.max_timing_offset_beats, 6)
            )
            velocity_offset = velocity_unit * request.max_velocity_offset
            velocity_offsets.append(
                math.floor(velocity_offset + 0.5)
                if velocity_offset >= 0
                else math.ceil(velocity_offset - 0.5)
            )
        return timing_offsets, velocity_offsets

    @staticmethod
    def _error_result(response: BridgeResponse) -> dict[str, Any]:
        return {
            "ok": False,
            "error": response.error.model_dump(mode="json") if response.error else None,
            "warnings": response.warnings,
        }

    def _invalid_payload_result(
        self, response: BridgeResponse, exc: ValidationError
    ) -> dict[str, Any]:
        return {
            "ok": False,
            "error": ErrorResponse(
                code=ErrorCode.INVALID_BRIDGE_RESPONSE,
                message="The Lua bridge returned an invalid MIDI transform payload.",
                details={"errors": self._json_safe_validation_errors(exc)},
                recoverable=True,
                suggested_action="Restart the Lua bridge and retry the transform.",
            ).model_dump(mode="json"),
            "warnings": response.warnings,
        }

    def _validation_error_result(self, exc: ValidationError) -> dict[str, Any]:
        return {
            "ok": False,
            "error": ErrorResponse(
                code=ErrorCode.INVALID_MIDI_NOTE_REQUEST,
                message="The MIDI transform request is invalid.",
                details={"errors": self._json_safe_validation_errors(exc)},
                recoverable=True,
                suggested_action=(
                    "Refresh MIDI notes and check the transform parameters."
                ),
            ).model_dump(mode="json"),
            "warnings": [],
        }

    @staticmethod
    def _json_safe_validation_errors(exc: ValidationError) -> list[dict[str, Any]]:
        return [
            {key: value for key, value in error.items() if key != "ctx"}
            for error in exc.errors()
        ]
