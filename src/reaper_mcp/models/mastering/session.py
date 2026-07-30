"""Mastering handoff and source contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from reaper_mcp.models.audio_measurement import AudioMeasurementResult

MasteringWorkflowMode = Literal["current_project", "stereo_mix"]


class MasteringIntent(BaseModel):
    """Engineer-supplied direction without invented loudness targets."""

    model_config = ConfigDict(extra="forbid")

    desired_outcome: str = Field(min_length=1, max_length=1000)
    priorities: list[str] = Field(default_factory=list, max_length=12)
    reference_notes: list[str] = Field(default_factory=list, max_length=12)


class CreateMasteringSessionRequest(BaseModel):
    """Validated input for one mastering handoff."""

    model_config = ConfigDict(extra="forbid")

    source_path: str = Field(min_length=1)
    workflow_mode: MasteringWorkflowMode
    desired_outcome: str = Field(min_length=1, max_length=1000)
    priorities: list[str] = Field(default_factory=list, max_length=12)
    reference_notes: list[str] = Field(default_factory=list, max_length=12)
    normalization_targets_lufs: dict[str, float] = Field(default_factory=dict)


class MasteringProjectContext(BaseModel):
    """Fingerprint of the active project at current-project handoff."""

    model_config = ConfigDict(extra="forbid")

    project_path: str
    project_name: str
    state_change_count: int = Field(ge=0)
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class MasteringSource(BaseModel):
    """Approved audio source and immutable measurement evidence."""

    model_config = ConfigDict(extra="forbid")

    workflow_mode: MasteringWorkflowMode
    measurement: AudioMeasurementResult
    project_context: MasteringProjectContext | None = None

    @model_validator(mode="after")
    def require_matching_project_context(self) -> MasteringSource:
        """Bind project context only to a current-project handoff."""

        if self.workflow_mode == "current_project" and self.project_context is None:
            raise ValueError("current_project sources require project_context.")
        if self.workflow_mode == "stereo_mix" and self.project_context is not None:
            raise ValueError("stereo_mix sources cannot include project_context.")
        return self


class MasteringSession(BaseModel):
    """Read-only handoff from an approved mix into mastering."""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(pattern=r"^ms_[0-9a-f]{24}$")
    state: Literal["measured"] = "measured"
    source: MasteringSource
    intent: MasteringIntent
