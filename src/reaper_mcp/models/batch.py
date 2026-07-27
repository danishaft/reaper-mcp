"""Typed batch mutation models."""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from reaper_mcp.models.project import TrackSnapshot


class TrackBatchChange(BaseModel):
    """One guarded set of optional track changes."""

    model_config = ConfigDict(extra="forbid")

    track_guid: str = Field(min_length=1)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    color: int | None = Field(default=None, ge=0)
    muted: bool | None = None
    soloed: bool | None = None
    armed: bool | None = None
    volume: float | None = Field(default=None, ge=0.0, le=4.0)
    pan: float | None = Field(default=None, ge=-1.0, le=1.0)

    @model_validator(mode="after")
    def require_change(self) -> Self:
        if all(
            value is None
            for value in (
                self.name,
                self.color,
                self.muted,
                self.soloed,
                self.armed,
                self.volume,
                self.pan,
            )
        ):
            raise ValueError("each track change must set at least one property")
        return self


class BatchTrackUpdateResult(BaseModel):
    """Result returned after one atomic track update batch."""

    model_config = ConfigDict(extra="forbid")

    tracks: list[TrackSnapshot] = Field(default_factory=list)
    track_count: int = 0
    changes_applied: bool = True
