"""Typed media item and take models."""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from reaper_mcp.models.position import (
    MusicalLength,
    MusicalPosition,
    PositionConversion,
)


class TakeSnapshot(BaseModel):
    """Read-only take state using REAPER's stable take GUID."""

    model_config = ConfigDict(extra="forbid")

    guid: str = Field(min_length=1)
    name: str = ""
    is_midi: bool = False


class MediaItemSnapshot(BaseModel):
    """Read-only media item state using REAPER's stable item GUID."""

    model_config = ConfigDict(extra="forbid")

    guid: str = Field(min_length=1)
    track_guid: str = Field(min_length=1)
    name: str = ""
    position_seconds: float
    length_seconds: float
    start_qn: float
    end_qn: float
    selected: bool = False
    muted: bool = False
    gain: float = Field(default=1.0, ge=0.0)
    fade_in_seconds: float = Field(default=0.0, ge=0.0)
    fade_out_seconds: float = Field(default=0.0, ge=0.0)
    take_count: int = 0
    active_take: TakeSnapshot | None = None


class MediaItemList(BaseModel):
    """Read-only list of media items."""

    model_config = ConfigDict(extra="forbid")

    items: list[MediaItemSnapshot] = Field(default_factory=list)
    item_count: int = 0


class CreateMidiItemRequest(BaseModel):
    """Input for creating one empty MIDI item."""

    model_config = ConfigDict(extra="forbid")

    track_guid: str = Field(min_length=1)
    start: MusicalPosition
    length: MusicalLength
    name: str = Field(default="MIDI item", min_length=1, max_length=200)


class CreateMidiItemResult(BaseModel):
    """Result returned after creating one MIDI item."""

    model_config = ConfigDict(extra="forbid")

    item: MediaItemSnapshot
    position: PositionConversion
    changes_applied: bool = True


class InsertAudioItemRequest(BaseModel):
    """Input for inserting one audio file as a media item."""

    model_config = ConfigDict(extra="forbid")

    track_guid: str = Field(min_length=1)
    source_path: str = Field(min_length=1)
    start: MusicalPosition
    name: str | None = Field(default=None, min_length=1, max_length=200)


class InsertAudioItemResult(BaseModel):
    """Result returned after inserting one audio media item."""

    model_config = ConfigDict(extra="forbid")

    item: MediaItemSnapshot
    position: PositionConversion
    changes_applied: bool = True


class MediaItemGuidRequest(BaseModel):
    """Input for commands targeting one media item by stable GUID."""

    model_config = ConfigDict(extra="forbid")

    item_guid: str = Field(min_length=1)


class MoveMediaItemRequest(MediaItemGuidRequest):
    """Input for moving one media item to a musical position."""

    start: MusicalPosition


class ResizeMediaItemRequest(MediaItemGuidRequest):
    """Input for setting one media item's musical length."""

    length: MusicalLength


class SplitMediaItemRequest(MediaItemGuidRequest):
    """Input for splitting one media item at a musical position."""

    split_at: MusicalPosition


class SetMediaItemMuteRequest(MediaItemGuidRequest):
    """Input for setting one media item's mute state."""

    muted: bool


class SetMediaItemGainRequest(MediaItemGuidRequest):
    """Input for setting one media item's linear gain."""

    gain: float = Field(ge=0.0, le=4.0)


class SetMediaItemFadeRequest(MediaItemGuidRequest):
    """Input for setting one media item's manual fade length."""

    length_seconds: float = Field(ge=0.0, le=3600.0)


class MediaItemMutationResult(BaseModel):
    """Result returned after changing one media item."""

    model_config = ConfigDict(extra="forbid")

    item: MediaItemSnapshot
    changes_applied: bool = True


class DuplicateMediaItemResult(MediaItemMutationResult):
    """Result returned after duplicating one media item."""

    source_item_guid: str = Field(min_length=1)
    selection_restored: bool


class SplitMediaItemResult(BaseModel):
    """Result returned after splitting one media item."""

    model_config = ConfigDict(extra="forbid")

    left_item: MediaItemSnapshot
    right_item: MediaItemSnapshot
    changes_applied: bool = True


class DeleteMediaItemResult(BaseModel):
    """Result returned after deleting one media item."""

    model_config = ConfigDict(extra="forbid")

    deleted_item_guid: str = Field(min_length=1)
    item_count: int = Field(ge=0)
    changes_applied: bool = True


class MidiNoteInput(BaseModel):
    """Input for inserting one MIDI note."""

    model_config = ConfigDict(extra="forbid")

    start: MusicalPosition
    length: MusicalLength
    pitch: int = Field(ge=0, le=127)
    velocity: int = Field(default=96, ge=1, le=127)
    channel: int = Field(default=0, ge=0, le=15)
    selected: bool = False
    muted: bool = False


class MidiNoteSnapshot(BaseModel):
    """Read-only MIDI note state within a take."""

    model_config = ConfigDict(extra="forbid")

    index: int
    fingerprint: str = Field(min_length=1)
    selected: bool = False
    muted: bool = False
    start_ppq: float
    end_ppq: float
    start_qn: float
    end_qn: float
    channel: int
    pitch: int
    velocity: int


class MidiNoteList(BaseModel):
    """Read-only list of MIDI notes in one take."""

    model_config = ConfigDict(extra="forbid")

    take_guid: str = Field(min_length=1)
    notes: list[MidiNoteSnapshot] = Field(default_factory=list)
    note_count: int = 0

    @model_validator(mode="after")
    def validate_note_count(self) -> Self:
        """Keep the declared note count aligned with the returned snapshots."""

        if self.note_count != len(self.notes):
            raise ValueError("note_count must equal the number of notes")
        return self


class AddMidiNotesRequest(BaseModel):
    """Input for batch MIDI note insertion."""

    model_config = ConfigDict(extra="forbid")

    take_guid: str = Field(min_length=1)
    notes: list[MidiNoteInput] = Field(min_length=1)


class AddMidiNoteRequest(BaseModel):
    """Input for single MIDI note insertion."""

    model_config = ConfigDict(extra="forbid")

    take_guid: str = Field(min_length=1)
    note: MidiNoteInput


class AddMidiNotesResult(MidiNoteList):
    """Result returned after batch MIDI note insertion."""

    inserted_count: int
    inserted_notes: list[MidiNoteSnapshot] = Field(default_factory=list)
    changes_applied: bool = True

    @model_validator(mode="after")
    def validate_inserted_count(self) -> Self:
        """Keep the declared insertion count aligned with inserted snapshots."""

        if self.inserted_count != len(self.inserted_notes):
            raise ValueError("inserted_count must equal the number of inserted notes")
        return self


class AddMidiNoteResult(MidiNoteList):
    """Result returned after single MIDI note insertion."""

    inserted_note: MidiNoteSnapshot
    changes_applied: bool = True


class MidiNoteIdentity(BaseModel):
    """Identity guard for mutating one MIDI note."""

    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=0)
    expected_fingerprint: str = Field(min_length=1)


class UpdateMidiNoteRequest(BaseModel):
    """Input for replacing one MIDI note."""

    model_config = ConfigDict(extra="forbid")

    take_guid: str = Field(min_length=1)
    note: MidiNoteInput
    note_identity: MidiNoteIdentity


class UpdateMidiNoteResult(MidiNoteList):
    """Result returned after updating one MIDI note."""

    updated_note: MidiNoteSnapshot
    changes_applied: bool = True


class DeleteMidiNotesRequest(BaseModel):
    """Input for deleting MIDI notes by guarded note index."""

    model_config = ConfigDict(extra="forbid")

    take_guid: str = Field(min_length=1)
    notes: list[MidiNoteIdentity] = Field(min_length=1)

    @model_validator(mode="after")
    def require_unique_note_indices(self) -> Self:
        indexes = [note.index for note in self.notes]
        if len(set(indexes)) != len(indexes):
            raise ValueError("notes must not contain duplicate indexes")
        return self


class DeleteMidiNotesResult(MidiNoteList):
    """Result returned after deleting MIDI notes."""

    deleted_count: int
    changes_applied: bool = True
