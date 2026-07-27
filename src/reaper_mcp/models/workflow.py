"""Typed contracts for high-level music workflows."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from reaper_mcp.models.arrangement import RegionSnapshot
from reaper_mcp.models.media import MediaItemSnapshot
from reaper_mcp.models.project import TrackSnapshot

SongStarterMode = Literal["major", "minor"]
SongStarterRole = Literal["drums", "bass", "chords", "lead"]
MidiPatternType = Literal["chord_progression", "arpeggio"]


class CreateSongStarterRequest(BaseModel):
    """Input for creating one deterministic four-part MIDI song starter."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="Song Starter", min_length=1, max_length=100)
    start_measure: int = Field(default=1, ge=1, le=9999)
    bars: int = Field(default=8, ge=4, le=32, multiple_of=4)
    root_note: int = Field(default=60, ge=48, le=72)
    mode: SongStarterMode = "major"

    @field_validator("name")
    @classmethod
    def require_visible_name(cls, value: str) -> str:
        """Reject names that contain only whitespace."""

        normalized = value.strip()
        if not normalized:
            msg = "Song starter name must contain a visible character."
            raise ValueError(msg)
        return normalized


class CreateMidiPatternRequest(BaseModel):
    """Input for creating a bounded musical MIDI pattern on an existing track."""

    model_config = ConfigDict(extra="forbid")

    track_guid: str = Field(min_length=1)
    pattern: MidiPatternType
    start_measure: int = Field(default=1, ge=1, le=9999)
    bars: int = Field(default=8, ge=1, le=64)
    root_note: int = Field(default=60, ge=36, le=84)
    mode: SongStarterMode = "major"
    subdivision_beats: float = Field(default=0.5, ge=0.25, le=2.0)

    @model_validator(mode="after")
    def require_supported_subdivision(self) -> "CreateMidiPatternRequest":
        if self.subdivision_beats not in {0.25, 0.5, 1.0, 2.0}:
            raise ValueError("subdivision_beats must be 0.25, 0.5, 1.0, or 2.0")
        return self


class CreateMidiPatternResult(BaseModel):
    """Result returned after creating one musical MIDI pattern."""

    model_config = ConfigDict(extra="forbid")

    pattern: MidiPatternType
    track_guid: str = Field(min_length=1)
    item: MediaItemSnapshot
    note_count: int = Field(ge=1)
    start_measure: int = Field(ge=1)
    bars: int = Field(ge=1)
    changes_applied: bool = True


class SongStarterPart(BaseModel):
    """One created song-starter part and its stable REAPER identities."""

    model_config = ConfigDict(extra="forbid")

    role: SongStarterRole
    track: TrackSnapshot
    item: MediaItemSnapshot
    note_count: int = Field(ge=1)

    @model_validator(mode="after")
    def require_matching_track(self) -> "SongStarterPart":
        if self.item.track_guid != self.track.guid:
            msg = "Song starter item track GUID must match its track GUID."
            raise ValueError(msg)
        return self


class CreateSongStarterResult(BaseModel):
    """Result returned after creating a complete song starter."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    start_measure: int = Field(ge=1)
    bars: int = Field(ge=4)
    root_note: int = Field(ge=0, le=127)
    mode: SongStarterMode
    start_qn: float = Field(ge=0.0)
    end_qn: float = Field(gt=0.0)
    start_seconds: float = Field(ge=0.0)
    end_seconds: float = Field(gt=0.0)
    parts: list[SongStarterPart] = Field(min_length=4, max_length=4)
    region: RegionSnapshot
    total_note_count: int = Field(ge=4)
    selection_restored: bool
    changes_applied: bool = True

    @model_validator(mode="after")
    def require_complete_consistent_result(self) -> "CreateSongStarterResult":
        expected_roles = {"drums", "bass", "chords", "lead"}
        if {part.role for part in self.parts} != expected_roles:
            msg = "Song starter result must contain each required part exactly once."
            raise ValueError(msg)
        if self.end_qn <= self.start_qn or self.end_seconds <= self.start_seconds:
            msg = "Song starter end positions must be after start positions."
            raise ValueError(msg)
        if self.total_note_count != sum(part.note_count for part in self.parts):
            msg = "Song starter total note count must equal the sum of its parts."
            raise ValueError(msg)
        if not self.selection_restored:
            msg = "Song starter result must confirm prior track selection restoration."
            raise ValueError(msg)
        return self
