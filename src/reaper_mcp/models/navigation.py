"""Typed project navigation and save models."""

from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TimelineRange(BaseModel):
    """One optional timeline range in seconds."""

    model_config = ConfigDict(extra="forbid")

    start_seconds: float = Field(ge=0.0)
    end_seconds: float = Field(ge=0.0)
    length_seconds: float = Field(ge=0.0)
    is_set: bool

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if self.end_seconds < self.start_seconds:
            raise ValueError("end_seconds must not precede start_seconds")
        if abs(self.length_seconds - (self.end_seconds - self.start_seconds)) > 1e-6:
            raise ValueError("length_seconds must match the range bounds")
        if self.is_set != (self.end_seconds > self.start_seconds):
            raise ValueError("is_set must match the range bounds")
        return self


class ProjectNavigationSnapshot(BaseModel):
    """Cursor, selection, loop, and save state for the active project."""

    model_config = ConfigDict(extra="forbid")

    project_path: str | None = None
    dirty: bool
    edit_cursor_seconds: float = Field(ge=0.0)
    time_selection: TimelineRange
    loop_points: TimelineRange
    loop_enabled: bool


class ProjectNavigationResult(ProjectNavigationSnapshot):
    """Navigation state returned after one state change or save."""

    changes_applied: bool = False
    saved: bool = False


class SetTimelineRangeRequest(BaseModel):
    """Input for setting a non-empty timeline range."""

    model_config = ConfigDict(extra="forbid")

    start_seconds: float = Field(ge=0.0)
    end_seconds: float = Field(gt=0.0)

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if self.end_seconds <= self.start_seconds:
            raise ValueError("end_seconds must be greater than start_seconds")
        return self


class SetEditCursorRequest(BaseModel):
    """Input for moving the project edit cursor."""

    model_config = ConfigDict(extra="forbid")

    position_seconds: float = Field(ge=0.0)
    move_view: bool = True
    seek_playback: bool = False


class SaveProjectAsRequest(BaseModel):
    """Validated project destination."""

    model_config = ConfigDict(extra="forbid")

    project_path: Path
    overwrite: bool = False
