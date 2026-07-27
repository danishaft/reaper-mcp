"""Typed track-template models."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from reaper_mcp.models.project import TrackSnapshot


class TrackTemplateSnapshot(BaseModel):
    """One track template file."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    path: Path


class TrackTemplateList(BaseModel):
    """Available track templates."""

    model_config = ConfigDict(extra="forbid")

    templates: list[TrackTemplateSnapshot] = Field(default_factory=list)
    template_count: int = 0


class TrackTemplateMutationResult(BaseModel):
    """Result returned after applying or saving a track template."""

    model_config = ConfigDict(extra="forbid")

    template_path: Path
    track: TrackSnapshot | None = None
    track_count: int = 0
    changes_applied: bool = True
