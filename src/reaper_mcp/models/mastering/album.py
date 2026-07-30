"""Multi-song mastering sequence and approval contracts."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from reaper_mcp.models.audio_measurement import AudioMeasurementResult
from reaper_mcp.models.audio_program_analysis import AudioProgramAnalysisResult
from reaper_mcp.models.mastering.candidate import ApprovedMasteringCandidate

AlbumSequenceMode = Literal["continuous", "gapless", "explicit_gaps"]


class AlbumMetadata(BaseModel):
    """Release-level metadata used for manifests and CD-Text preview."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    artist: str = Field(min_length=1, max_length=200)
    catalog_number: str | None = Field(default=None, max_length=100)
    upc_ean: str | None = Field(default=None, pattern=r"^(?:\d{12}|\d{13})$")


class AlbumTrackMetadata(BaseModel):
    """Track-level identity and optional PQ identifier."""

    model_config = ConfigDict(extra="forbid")

    sequence_number: int = Field(ge=1, le=99)
    title: str = Field(min_length=1, max_length=200)
    artist: str = Field(min_length=1, max_length=200)
    isrc: str | None = Field(
        default=None,
        pattern=r"^[A-Z]{2}[A-Z0-9]{3}\d{7}$",
    )


class AlbumTrackIntent(BaseModel):
    """One approved song plus sequence, gap, fade, and note intent."""

    model_config = ConfigDict(extra="forbid")

    approval: ApprovedMasteringCandidate
    metadata: AlbumTrackMetadata
    gap_before_seconds: float = Field(default=0.0, ge=0.0, le=60.0)
    fade_in_seconds: float = Field(default=0.0, ge=0.0, le=60.0)
    fade_out_seconds: float = Field(default=0.0, ge=0.0, le=60.0)
    notes: list[str] = Field(default_factory=list, max_length=20)


class AlbumContinuityLimits(BaseModel):
    """Optional engineer-defined flags; no artistic target is assumed."""

    model_config = ConfigDict(extra="forbid")

    maximum_adjacent_loudness_delta_lu: float | None = Field(
        default=None, ge=0.0, le=30.0
    )
    maximum_adjacent_plr_delta_db: float | None = Field(default=None, ge=0.0, le=30.0)
    maximum_adjacent_band_balance_delta_db: float | None = Field(
        default=None, ge=0.0, le=30.0
    )


class CreateMasteringAlbumRequest(BaseModel):
    """Validated ordered album built only from approved candidates."""

    model_config = ConfigDict(extra="forbid")

    metadata: AlbumMetadata
    sequence_mode: AlbumSequenceMode
    tracks: list[AlbumTrackIntent] = Field(min_length=2, max_length=99)
    continuity_limits: AlbumContinuityLimits = Field(
        default_factory=AlbumContinuityLimits
    )
    project_path: Path
    manifest_path: Path
    pq_preview_requested: bool = True

    @model_validator(mode="after")
    def validate_sequence(self) -> CreateMasteringAlbumRequest:
        """Require unique ordered approvals and mode-compatible gaps."""

        expected_sequence = list(range(1, len(self.tracks) + 1))
        actual_sequence = [track.metadata.sequence_number for track in self.tracks]
        if actual_sequence != expected_sequence:
            raise ValueError("Album tracks must be numbered consecutively from 1.")
        approval_ids = [track.approval.approval_id for track in self.tracks]
        candidate_ids = [track.approval.candidate.candidate_id for track in self.tracks]
        if len(set(approval_ids)) != len(approval_ids):
            raise ValueError("Album approval IDs must be unique.")
        if len(set(candidate_ids)) != len(candidate_ids):
            raise ValueError("Album candidates must be unique.")
        if self.sequence_mode in {"continuous", "gapless"} and any(
            track.gap_before_seconds > 0.0 for track in self.tracks
        ):
            raise ValueError(
                "Continuous and gapless sequences cannot insert track gaps."
            )
        return self


class AlbumSequenceAsset(BaseModel):
    """One float sequence asset preserving an approved song fingerprint."""

    model_config = ConfigDict(extra="forbid")

    sequence_number: int
    candidate_id: str
    approval_id: str
    source_path: Path
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    asset_path: Path
    asset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    asset_start_seconds: float = Field(ge=0.0)
    index_start_seconds: float = Field(ge=0.0)
    program_end_seconds: float = Field(gt=0.0)
    gap_before_seconds: float = Field(ge=0.0)
    fade_in_seconds: float = Field(ge=0.0)
    fade_out_seconds: float = Field(ge=0.0)
    measurement: AudioMeasurementResult
    program_analysis: AudioProgramAnalysisResult


class AlbumTransitionAnalysis(BaseModel):
    """Measured deltas from the previous song, without an invented preference."""

    model_config = ConfigDict(extra="forbid")

    from_sequence_number: int = Field(ge=1)
    to_sequence_number: int = Field(ge=2)
    gap_seconds: float = Field(ge=0.0)
    integrated_loudness_delta_lu: float
    true_peak_delta_db: float | None = None
    plr_delta_db: float | None = None
    band_balance_deltas_db: dict[str, float]
    continuity_flags: list[str] = Field(default_factory=list)


class AlbumPqTrack(BaseModel):
    """PQ/CD-Text preview evidence; this is not a DDP image."""

    model_config = ConfigDict(extra="forbid")

    sequence_number: int
    index_01_frames: int = Field(ge=0)
    index_01_seconds: float = Field(ge=0.0)
    pregap_frames: int = Field(ge=0)
    title: str
    performer: str
    isrc: str | None = None


class MasteringAlbumProject(BaseModel):
    """Verified album audition project and continuity evidence."""

    model_config = ConfigDict(extra="forbid")

    album_id: str = Field(pattern=r"^al_[0-9a-f]{24}$")
    state: Literal["prepared"] = "prepared"
    metadata: AlbumMetadata
    sequence_mode: AlbumSequenceMode
    project_path: Path
    project_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_path: Path
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    asset_directory: Path
    assets: list[AlbumSequenceAsset] = Field(min_length=2, max_length=99)
    transitions: list[AlbumTransitionAnalysis] = Field(min_length=1)
    pq_preview: list[AlbumPqTrack] = Field(default_factory=list)
    total_duration_seconds: float = Field(gt=0.0)
    median_integrated_lufs: float
    integrated_loudness_span_lu: float = Field(ge=0.0)
    sample_rate_hz: int = Field(gt=0)
    channel_layout: str
    interactive_project_untouched: Literal[True] = True
    ddp_available: Literal[False] = False
    backend_name: str
    backend_executable: Path
    backend_version: str
    reaper_executable: Path
    warnings: list[str] = Field(default_factory=list)


class ApproveMasteringAlbumRequest(BaseModel):
    """Explicit engineer listening evidence for a prepared album sequence."""

    model_config = ConfigDict(extra="forbid")

    album: MasteringAlbumProject
    approved_by: str = Field(min_length=1, max_length=200)
    judgment_notes: list[str] = Field(min_length=1, max_length=30)
    listening_confirmed: Literal[True]


class ApprovedMasteringAlbum(BaseModel):
    """Human-approved album sequence; DDP still requires a separate gate."""

    model_config = ConfigDict(extra="forbid")

    album_approval_id: str = Field(pattern=r"^aa_[0-9a-f]{24}$")
    state: Literal["approved"] = "approved"
    album: MasteringAlbumProject
    album_id: str
    album_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approved_by: str
    judgment_notes: list[str]
    listening_confirmed: Literal[True]
    ddp_available: Literal[False] = False
