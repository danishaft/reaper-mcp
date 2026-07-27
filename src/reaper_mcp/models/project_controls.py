"""Typed project control models."""

from pydantic import BaseModel, ConfigDict, Field


class GridSnapshot(BaseModel):
    """Current project grid and snap state."""

    model_config = ConfigDict(extra="forbid")

    division: float = Field(gt=0.0)
    swing: float = Field(ge=-1.0, le=1.0)
    swing_mode: int = Field(ge=0)
    snap_enabled: bool


class SetGridRequest(BaseModel):
    """Input for setting project grid and snap state."""

    model_config = ConfigDict(extra="forbid")

    division: float = Field(gt=0.0, le=64.0)
    swing: float = Field(default=0.0, ge=-1.0, le=1.0)
    swing_mode: int = Field(default=0, ge=0, le=2)
    snap_enabled: bool = True


class ProjectControlResult(BaseModel):
    """Result returned after a project control command."""

    model_config = ConfigDict(extra="forbid")

    action: str
    changes_applied: bool = True
    grid: GridSnapshot | None = None
    metronome_enabled: bool | None = None
    playback_rate: float | None = Field(default=None, gt=0.0)
