"""Typed media take and comping models."""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ManagedTakeSnapshot(BaseModel):
    """One media take addressed by stable REAPER GUID."""

    model_config = ConfigDict(extra="forbid")

    guid: str = Field(min_length=1)
    item_guid: str = Field(min_length=1)
    index: int = Field(ge=0)
    name: str = ""
    is_active: bool
    is_midi: bool
    volume: float = Field(ge=0.0)
    pan: float = Field(ge=-1.0, le=1.0)
    pitch_semitones: float
    playback_rate: float = Field(gt=0.0)
    start_offset_seconds: float = Field(ge=0.0)
    preserve_pitch: bool


class TakeList(BaseModel):
    """All takes on one media item."""

    model_config = ConfigDict(extra="forbid")

    item_guid: str = Field(min_length=1)
    takes: list[ManagedTakeSnapshot] = Field(default_factory=list)
    take_count: int = Field(ge=0)
    active_take_guid: str | None = None

    @model_validator(mode="after")
    def validate_take_state(self) -> Self:
        if self.take_count != len(self.takes):
            raise ValueError("take_count must equal the number of takes")
        active = [take.guid for take in self.takes if take.is_active]
        if len(active) > 1:
            raise ValueError("only one take can be active")
        if active != ([self.active_take_guid] if self.active_take_guid else []):
            raise ValueError("active_take_guid must match the active take")
        return self


class TakeMutationResult(TakeList):
    """Take list returned after one take mutation."""

    changed_take: ManagedTakeSnapshot | None = None
    changes_applied: bool = True


class AddEmptyTakeRequest(BaseModel):
    """Input for adding one empty take to an item."""

    model_config = ConfigDict(extra="forbid")

    item_guid: str = Field(min_length=1)
    name: str = Field(default="Take", min_length=1, max_length=200)


class TakeGuidRequest(BaseModel):
    """Input targeting one take GUID."""

    model_config = ConfigDict(extra="forbid")

    take_guid: str = Field(min_length=1)


class RenameTakeRequest(TakeGuidRequest):
    """Input for renaming one take."""

    name: str = Field(min_length=1, max_length=200)


class SetTakePropertyRequest(TakeGuidRequest):
    """Bridge input for one allowlisted take property update."""

    property: str = Field(min_length=1)
    value: float
    preserve_pitch: bool | None = None


class CropToActiveTakeRequest(BaseModel):
    """Guarded input for removing all inactive takes from one item."""

    model_config = ConfigDict(extra="forbid")

    item_guid: str = Field(min_length=1)
    expected_active_take_guid: str = Field(min_length=1)
    expected_take_count: int = Field(ge=2)
