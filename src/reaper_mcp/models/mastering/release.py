"""Mastering version-set and codec-preview contracts."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from reaper_mcp.models.audio_measurement import AudioMeasurementResult
from reaper_mcp.models.audio_program_analysis import AudioProgramAnalysisResult
from reaper_mcp.models.mastering.candidate import ApprovedMasteringCandidate

MasteringVersionRole = Literal[
    "main",
    "clean",
    "explicit",
    "instrumental",
    "radio",
    "acapella",
    "other",
]


class MasteringVersionEntry(BaseModel):
    """One separately rendered and approved release version."""

    model_config = ConfigDict(extra="forbid")

    role: MasteringVersionRole
    label: str = Field(min_length=1, max_length=200)
    approval: ApprovedMasteringCandidate
    notes: list[str] = Field(default_factory=list, max_length=20)


class CreateMasteringVersionSetRequest(BaseModel):
    """Explicit approved sources grouped for coordinated delivery."""

    model_config = ConfigDict(extra="forbid")

    release_name: str = Field(min_length=1, max_length=200)
    entries: list[MasteringVersionEntry] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def require_unique_versions(self) -> CreateMasteringVersionSetRequest:
        """Require one main version and no reused approval or role."""

        roles = [entry.role for entry in self.entries]
        if roles.count("main") != 1:
            raise ValueError("A version set requires exactly one main version.")
        if len(set(roles)) != len(roles):
            raise ValueError("Version roles must be unique.")
        approval_ids = [entry.approval.approval_id for entry in self.entries]
        candidate_ids = [
            entry.approval.candidate.candidate_id for entry in self.entries
        ]
        if len(set(approval_ids)) != len(approval_ids):
            raise ValueError("Version approval IDs must be unique.")
        if len(set(candidate_ids)) != len(candidate_ids):
            raise ValueError("Version candidate IDs must be unique.")
        return self


class MasteringVersionSet(BaseModel):
    """Tamper-evident catalog of independently approved release versions."""

    model_config = ConfigDict(extra="forbid")

    version_set_id: str = Field(pattern=r"^vs_[0-9a-f]{24}$")
    release_name: str
    entries: list[MasteringVersionEntry] = Field(min_length=1, max_length=20)


CodecPreviewFormat = Literal["aac", "mp3", "opus"]


class CodecPreviewSpecification(BaseModel):
    """One lossy encode/decode preview; never a master deliverable."""

    model_config = ConfigDict(extra="forbid")

    format: CodecPreviewFormat
    encoded_path: Path
    decoded_wav_path: Path
    bitrate_kbps: int = Field(ge=32, le=512)
    sample_rate_hz: int | None = Field(default=None, ge=32_000, le=192_000)
    channels: Literal[1, 2] = 2

    @model_validator(mode="after")
    def validate_extensions(self) -> CodecPreviewSpecification:
        """Keep preview containers explicit."""

        expected_suffix = {
            "aac": ".m4a",
            "mp3": ".mp3",
            "opus": ".opus",
        }[self.format]
        if self.encoded_path.suffix.lower() != expected_suffix:
            raise ValueError(
                f"{self.format} previews require {expected_suffix} output."
            )
        if self.decoded_wav_path.suffix.lower() != ".wav":
            raise ValueError("Decoded codec previews require .wav output.")
        if self.encoded_path == self.decoded_wav_path:
            raise ValueError("Encoded and decoded preview paths must differ.")
        if self.format == "mp3" and self.bitrate_kbps > 320:
            raise ValueError("MP3 preview bitrate cannot exceed 320 kbps.")
        if (
            self.format == "opus"
            and self.sample_rate_hz is not None
            and self.sample_rate_hz != 48_000
        ):
            raise ValueError("Opus preview sample rate is unsupported.")
        return self


class CreateMasteringCodecPreviewRequest(BaseModel):
    """Approved candidate and one explicit lossy preview specification."""

    model_config = ConfigDict(extra="forbid")

    approval: ApprovedMasteringCandidate
    specification: CodecPreviewSpecification


class CodecPreviewDelta(BaseModel):
    """Decoded-minus-approved measurements for review, not preference."""

    model_config = ConfigDict(extra="forbid")

    integrated_loudness_delta_lu: float | None = None
    sample_peak_delta_db: float | None = None
    true_peak_delta_db: float | None = None
    band_balance_deltas_db: dict[str, float]


class MasteringCodecPreview(BaseModel):
    """Measured lossy preview and decoded audition evidence."""

    model_config = ConfigDict(extra="forbid")

    preview_id: str = Field(pattern=r"^cp_[0-9a-f]{24}$")
    state: Literal["measured_preview"] = "measured_preview"
    approval_id: str
    candidate_id: str
    specification: CodecPreviewSpecification
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    encoded_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    encoded_size_bytes: int = Field(gt=0)
    decoded_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    decoded_size_bytes: int = Field(gt=0)
    backend_name: str
    encoder_name: str
    backend_executable: Path
    backend_version: str
    resolved_sample_rate_hz: int = Field(gt=0)
    measurement: AudioMeasurementResult
    program_analysis: AudioProgramAnalysisResult
    delta: CodecPreviewDelta
    source_integrity_verified: Literal[True] = True
