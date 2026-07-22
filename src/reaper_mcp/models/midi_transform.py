"""Typed MIDI note transformation models."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from reaper_mcp.models.media import MidiNoteIdentity, MidiNoteList

ScaleMode = Literal[
    "major",
    "natural_minor",
    "harmonic_minor",
    "dorian",
    "mixolydian",
    "major_pentatonic",
    "minor_pentatonic",
    "blues",
    "chromatic",
]
ScaleDirection = Literal["nearest", "up", "down"]


class MidiTransformTargetRequest(BaseModel):
    """Guarded MIDI notes targeted by one transform."""

    model_config = ConfigDict(extra="forbid")

    take_guid: str = Field(min_length=1)
    notes: list[MidiNoteIdentity] = Field(min_length=1, max_length=4096)

    @model_validator(mode="after")
    def require_unique_note_indices(self) -> Self:
        indexes = [note.index for note in self.notes]
        if len(set(indexes)) != len(indexes):
            raise ValueError("notes must not contain duplicate indexes")
        return self


class TransposeMidiNotesRequest(MidiTransformTargetRequest):
    """Input for transposing guarded MIDI notes."""

    semitones: int = Field(ge=-127, le=127)

    @model_validator(mode="after")
    def reject_noop(self) -> Self:
        if self.semitones == 0:
            raise ValueError("semitones must not be zero")
        return self


class NudgeMidiNotesRequest(MidiTransformTargetRequest):
    """Input for shifting guarded MIDI notes in project beats."""

    offset_beats: float = Field(ge=-64.0, le=64.0)

    @model_validator(mode="after")
    def reject_noop(self) -> Self:
        if self.offset_beats == 0:
            raise ValueError("offset_beats must not be zero")
        return self


class QuantizeMidiNotesRequest(MidiTransformTargetRequest):
    """Input for quantizing guarded MIDI note onsets."""

    grid_beats: float = Field(gt=0.0, le=16.0)
    strength: float = Field(default=1.0, gt=0.0, le=1.0)
    swing: float = Field(default=0.0, ge=0.0, le=1.0)


class HumanizeMidiNotesRequest(MidiTransformTargetRequest):
    """Input for deterministic MIDI timing and velocity humanization."""

    max_timing_offset_beats: float = Field(default=0.02, ge=0.0, le=1.0)
    max_velocity_offset: int = Field(default=8, ge=0, le=64)
    seed: int = Field(default=0, ge=-(2**31), le=(2**31) - 1)

    @model_validator(mode="after")
    def require_one_humanize_dimension(self) -> Self:
        if self.max_timing_offset_beats == 0 and self.max_velocity_offset == 0:
            raise ValueError("at least one humanize offset must be greater than zero")
        return self


class HumanizeMidiNotesBridgeRequest(HumanizeMidiNotesRequest):
    """Bridge payload with deterministic offsets generated in Python."""

    timing_offsets: list[float]
    velocity_offsets: list[int]

    @model_validator(mode="after")
    def require_one_offset_per_note(self) -> Self:
        note_count = len(self.notes)
        if len(self.timing_offsets) != note_count:
            raise ValueError("timing_offsets must match the note target count")
        if len(self.velocity_offsets) != note_count:
            raise ValueError("velocity_offsets must match the note target count")
        return self


class SnapMidiNotesToScaleRequest(MidiTransformTargetRequest):
    """Input for moving guarded MIDI notes onto a named scale."""

    root_pitch_class: int = Field(ge=0, le=11)
    scale: ScaleMode = "major"
    direction: ScaleDirection = "nearest"


class ShapeMidiNoteVelocitiesRequest(MidiTransformTargetRequest):
    """Input for scaling and offsetting guarded MIDI note velocities."""

    factor: float = Field(default=1.0, ge=0.0, le=4.0)
    offset: int = Field(default=0, ge=-127, le=127)

    @model_validator(mode="after")
    def reject_noop(self) -> Self:
        if self.factor == 1.0 and self.offset == 0:
            raise ValueError("factor and offset would not change velocities")
        return self


class RemoveMidiNoteOverlapsRequest(MidiTransformTargetRequest):
    """Input for trimming guarded same-pitch MIDI note overlaps."""


class MidiTransformResult(MidiNoteList):
    """Result returned after one MIDI note transformation."""

    transformed_count: int = Field(ge=1)
    changes_applied: bool = True
