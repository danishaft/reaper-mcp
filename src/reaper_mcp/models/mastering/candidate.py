"""Mastering candidate, comparison, audition, and approval contracts."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from reaper_mcp.models.audio_measurement import AudioMeasurementResult
from reaper_mcp.models.mastering.plan import (
    MasteringPlan,
    VerifiedMasteringPlanApplication,
)
from reaper_mcp.models.render import RenderProjectResult


class CreateMasteringCandidateRequest(BaseModel):
    """Validated render request for one applied mastering plan."""

    model_config = ConfigDict(extra="forbid")

    plan: MasteringPlan
    application: VerifiedMasteringPlanApplication
    output_path: Path
    label: str = Field(min_length=1, max_length=100)
    engineer_notes: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def require_matching_application(self) -> CreateMasteringCandidateRequest:
        """Bind candidate creation to the exact applied plan."""

        if self.application.approval_hash != self.plan.approval_hash:
            raise ValueError("Application approval hash does not match the plan.")
        if self.application.master_track_guid != self.plan.master_track_guid:
            raise ValueError("Application master track does not match the plan.")
        if self.application.applied_operation_count != len(self.plan.operations):
            raise ValueError("Application operation count does not match the plan.")
        if not self.application.changes_applied:
            raise ValueError("Application must report changes_applied.")
        return self


class MasteringCandidate(BaseModel):
    """Measured candidate derived from one exact source, plan, and render."""

    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(pattern=r"^mc_[0-9a-f]{24}$")
    state: Literal["verified"] = "verified"
    label: str
    plan_id: str
    approval_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    master_chain_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    render: RenderProjectResult
    rendered_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    measurement: AudioMeasurementResult
    engineer_notes: list[str] = Field(default_factory=list)
    approval_state: Literal["pending"] = "pending"


class CandidateComparisonEntry(BaseModel):
    """Non-destructive audition gain for one measured candidate."""

    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    label: str
    rendered_path: Path
    integrated_lufs: float = Field(ge=-120.0, le=0.0)
    audition_gain_db: float = Field(ge=-120.0, le=0.0)
    predicted_true_peak_dbtp: float | None = None


class MasteringCandidateComparison(BaseModel):
    """Loudness-matched comparison that does not claim a preference."""

    model_config = ConfigDict(extra="forbid")

    comparison_id: str = Field(pattern=r"^cmp_[0-9a-f]{24}$")
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    method: Literal["integrated_lufs_attenuation_only"]
    reference_lufs: float = Field(ge=-120.0, le=0.0)
    entries: list[CandidateComparisonEntry] = Field(min_length=2, max_length=2)
    warnings: list[str] = Field(default_factory=list)


class CreateMasteringAuditionRequest(BaseModel):
    """Two exact candidates and one measured comparison for isolated audition."""

    model_config = ConfigDict(extra="forbid")

    candidates: tuple[MasteringCandidate, MasteringCandidate]
    comparison: MasteringCandidateComparison
    project_path: Path
    blind_labels: bool = True
    excerpt_start_seconds: float = Field(default=0.0, ge=0.0)
    excerpt_duration_seconds: float | None = Field(default=None, gt=0.0)

    @model_validator(mode="after")
    def require_matching_candidates(self) -> CreateMasteringAuditionRequest:
        """Bind paths, identities, and formats to the measured comparison."""

        candidate_by_id = {
            candidate.candidate_id: candidate for candidate in self.candidates
        }
        if len(candidate_by_id) != 2:
            raise ValueError("Two different mastering candidates are required.")
        if set(candidate_by_id) != {
            entry.candidate_id for entry in self.comparison.entries
        }:
            raise ValueError("Candidates must exactly match the comparison.")
        if any(
            candidate.source_sha256 != self.comparison.source_sha256
            for candidate in self.candidates
        ):
            raise ValueError("Candidates and comparison must use the same source.")
        for entry in self.comparison.entries:
            candidate = candidate_by_id[entry.candidate_id]
            if Path(candidate.render.primary_output_path) != entry.rendered_path:
                raise ValueError("Comparison path does not match its candidate.")
        formats = {
            (
                candidate.measurement.technical.sample_rate_hz,
                candidate.measurement.technical.channel_layout,
            )
            for candidate in self.candidates
        }
        if len(formats) != 1 or None in next(iter(formats)):
            raise ValueError(
                "Audition candidates require one matching known audio format."
            )
        return self


class MasteringAuditionAsset(BaseModel):
    """One gain-matched copy used only by the isolated audition project."""

    model_config = ConfigDict(extra="forbid")

    display_label: str
    candidate_id: str
    source_path: Path
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    audition_path: Path
    audition_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    audition_gain_db: float = Field(ge=-120.0, le=0.0)


class MasteringAuditionProject(BaseModel):
    """Verified child-created sequential A/B project."""

    model_config = ConfigDict(extra="forbid")

    audition_id: str = Field(pattern=r"^ma_[0-9a-f]{24}$")
    comparison_id: str
    project_path: Path
    project_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    asset_directory: Path
    assets: list[MasteringAuditionAsset] = Field(min_length=2, max_length=2)
    layout: Literal["sequential_a_then_b"] = "sequential_a_then_b"
    blind_labels: bool
    interactive_project_untouched: Literal[True] = True
    backend_name: str
    backend_executable: Path
    backend_version: str
    reaper_executable: Path


class ApproveMasteringCandidateRequest(BaseModel):
    """Explicit engineer judgment required before delivery."""

    model_config = ConfigDict(extra="forbid")

    candidate: MasteringCandidate
    comparison: MasteringCandidateComparison
    approved_by: str = Field(min_length=1, max_length=200)
    judgment_notes: list[str] = Field(min_length=1, max_length=20)
    listening_confirmed: Literal[True]

    @model_validator(mode="after")
    def require_candidate_in_comparison(self) -> ApproveMasteringCandidateRequest:
        """Reject approval evidence unrelated to this comparison."""

        candidate_ids = {entry.candidate_id for entry in self.comparison.entries}
        if self.candidate.candidate_id not in candidate_ids:
            raise ValueError("Approved candidate is not in the comparison.")
        if self.candidate.source_sha256 != self.comparison.source_sha256:
            raise ValueError("Candidate and comparison sources do not match.")
        return self


class ApprovedMasteringCandidate(BaseModel):
    """Delivery gate containing candidate and human listening evidence."""

    model_config = ConfigDict(extra="forbid")

    approval_id: str = Field(pattern=r"^ca_[0-9a-f]{24}$")
    state: Literal["approved"] = "approved"
    candidate: MasteringCandidate
    comparison_id: str
    approved_by: str
    judgment_notes: list[str]
    listening_confirmed: Literal[True]
