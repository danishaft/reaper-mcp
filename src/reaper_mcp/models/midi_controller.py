"""Typed MIDI controller-event models."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from reaper_mcp.models.position import MusicalPosition

ControllerEventType = Literal[
    "cc",
    "pitch_bend",
    "channel_pressure",
    "program_change",
]


class MidiControllerInput(BaseModel):
    """Input for one MIDI controller event."""

    model_config = ConfigDict(extra="forbid")

    position: MusicalPosition
    event_type: ControllerEventType = "cc"
    controller: int | None = Field(default=None, ge=0, le=127)
    value: int = Field(ge=0, le=16383)
    channel: int = Field(default=0, ge=0, le=15)
    selected: bool = False
    muted: bool = False

    @model_validator(mode="after")
    def validate_event_shape(self) -> Self:
        if self.event_type == "cc" and self.controller is None:
            raise ValueError("controller is required for cc events")
        if self.event_type == "cc" and self.value > 127:
            raise ValueError("cc values must be between 0 and 127")
        if self.event_type in {"channel_pressure", "program_change"}:
            if self.value > 127:
                raise ValueError(f"{self.event_type} values must be between 0 and 127")
            if self.controller is not None:
                raise ValueError(f"controller is not valid for {self.event_type}")
        if self.event_type == "pitch_bend" and self.controller is not None:
            raise ValueError("controller is not valid for pitch_bend")
        return self


class MidiControllerSnapshot(BaseModel):
    """Read-only MIDI controller event with a guarded identity."""

    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=0)
    fingerprint: str = Field(min_length=1)
    position_ppq: float
    position_qn: float
    event_type: ControllerEventType
    controller: int | None = Field(default=None, ge=0, le=127)
    value: int = Field(ge=0, le=16383)
    channel: int = Field(ge=0, le=15)
    selected: bool = False
    muted: bool = False


class MidiControllerList(BaseModel):
    """Read-only MIDI controller events in one take."""

    model_config = ConfigDict(extra="forbid")

    take_guid: str = Field(min_length=1)
    events: list[MidiControllerSnapshot] = Field(default_factory=list)
    event_count: int = 0

    @model_validator(mode="after")
    def validate_event_count(self) -> Self:
        if self.event_count != len(self.events):
            raise ValueError("event_count must equal the number of events")
        return self


class MidiControllerIdentity(BaseModel):
    """Identity guard for one controller event."""

    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=0)
    expected_fingerprint: str = Field(min_length=1)


class AddMidiControllersResult(MidiControllerList):
    """Result returned after inserting controller events."""

    inserted_events: list[MidiControllerSnapshot] = Field(default_factory=list)
    inserted_count: int = 0
    changes_applied: bool = True


class UpdateMidiControllerResult(MidiControllerList):
    """Result returned after updating one controller event."""

    updated_event: MidiControllerSnapshot
    changes_applied: bool = True


class DeleteMidiControllersResult(MidiControllerList):
    """Result returned after deleting controller events."""

    deleted_count: int = 0
    changes_applied: bool = True
