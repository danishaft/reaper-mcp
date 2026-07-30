"""Mastering FX plan and isolated-project contracts."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from reaper_mcp.models.fx import FxIdentity, FxSnapshot
from reaper_mcp.models.mastering.session import MasteringSession


class SetMasteringFxParameter(BaseModel):
    """One exact, engineer-reviewed parameter change."""

    model_config = ConfigDict(extra="forbid", validate_by_name=True)

    action: Literal["set_parameter"] = Field(
        default="set_parameter",
        validation_alias="type",
    )
    fx_identity: FxIdentity
    parameter_index: int = Field(ge=0)
    expected_parameter_name: str = Field(min_length=1)
    normalized_value: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(min_length=1, max_length=500)
    expected_effect: str = Field(min_length=1, max_length=500)

    @model_validator(mode="before")
    @classmethod
    def normalize_public_type(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        if normalized.get("type") == "set_fx_parameter":
            normalized["type"] = "set_parameter"
        if normalized.get("action") == "set_fx_parameter":
            normalized["action"] = "set_parameter"
        return normalized


class SetMasteringFxEnabled(BaseModel):
    """One exact, engineer-reviewed FX enable or bypass change."""

    model_config = ConfigDict(extra="forbid", validate_by_name=True)

    action: Literal["set_enabled"] = Field(
        default="set_enabled",
        validation_alias="type",
    )
    fx_identity: FxIdentity
    enabled: bool
    rationale: str = Field(min_length=1, max_length=500)
    expected_effect: str = Field(min_length=1, max_length=500)

    @model_validator(mode="before")
    @classmethod
    def normalize_public_type(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        if normalized.get("type") == "set_fx_enabled":
            normalized["type"] = "set_enabled"
        if normalized.get("action") == "set_fx_enabled":
            normalized["action"] = "set_enabled"
        return normalized


MasteringFxOperation = SetMasteringFxParameter | SetMasteringFxEnabled


class PreviewMasteringPlanRequest(BaseModel):
    """Validated preview input with a complete measured session."""

    model_config = ConfigDict(extra="forbid")

    session: MasteringSession
    master_track_guid: str = Field(min_length=1)
    operations: list[MasteringFxOperation] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def reject_duplicate_targets(self) -> PreviewMasteringPlanRequest:
        """Prevent order-dependent duplicate writes inside one plan."""

        targets: set[tuple[str, str, int | None]] = set()
        for operation in self.operations:
            parameter_index = (
                operation.parameter_index
                if isinstance(operation, SetMasteringFxParameter)
                else None
            )
            target = (
                operation.fx_identity.expected_identity,
                operation.action,
                parameter_index,
            )
            if target in targets:
                raise ValueError("Mastering plans cannot write one target twice.")
            targets.add(target)
        return self


class MasteringPlan(BaseModel):
    """Immutable plan that must be approved by its exact hash."""

    model_config = ConfigDict(extra="forbid")

    plan_id: str = Field(pattern=r"^mp_[0-9a-f]{24}$")
    session: MasteringSession
    master_track_guid: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    project_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    master_chain_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    operations: list[MasteringFxOperation] = Field(min_length=1, max_length=64)
    warnings: list[str] = Field(default_factory=list)
    approval_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class MasteringPlanApplication(BaseModel):
    """Observed master chain after one approved transaction."""

    model_config = ConfigDict(extra="forbid")

    approval_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    master_track_guid: str = Field(min_length=1)
    applied_operation_count: int = Field(gt=0)
    fx: list[FxSnapshot]
    fx_count: int = Field(ge=0)
    changes_applied: bool


class VerifiedMasteringPlanApplication(MasteringPlanApplication):
    """Application evidence extended with the observed complete-chain hash."""

    master_chain_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CreateStereoMasteringProjectRequest(BaseModel):
    """Validated isolated-project creation request."""

    model_config = ConfigDict(extra="forbid")

    session: MasteringSession
    project_path: Path

    @model_validator(mode="after")
    def require_stereo_mix_session(self) -> CreateStereoMasteringProjectRequest:
        """Only immutable external stereo sources use this constructor."""

        if self.session.source.workflow_mode != "stereo_mix":
            raise ValueError("Isolated project creation requires a stereo_mix session.")
        return self


class StereoMasteringProject(BaseModel):
    """Verified RPP artifact created by a short-lived REAPER process."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    project_path: Path
    project_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_path: Path
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(gt=0)
    reaper_executable: Path
