"""Typed track freeze models."""

from pydantic import BaseModel, ConfigDict, Field

from reaper_mcp.models.project import TrackSnapshot


class TrackFreezeState(BaseModel):
    """Read-only freeze state for one track."""

    model_config = ConfigDict(extra="forbid")

    track_guid: str = Field(min_length=1)
    frozen: bool
    freeze_count: int = Field(ge=0)
    track: TrackSnapshot


class TrackFreezeResult(BaseModel):
    """Result returned after freezing or unfreezing one track."""

    model_config = ConfigDict(extra="forbid")

    state: TrackFreezeState
    selection_restored: bool
    may_create_media_files: bool = True
    changes_applied: bool = True
