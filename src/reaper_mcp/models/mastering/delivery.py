"""Final mastering delivery and QC contracts."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from reaper_mcp.models.audio_measurement import AudioMeasurementResult
from reaper_mcp.models.audio_program_analysis import AudioProgramAnalysisResult
from reaper_mcp.models.mastering.candidate import ApprovedMasteringCandidate

DeliveryBitDepth = Literal[16, 24, "32_float"]
DeliveryDitherPolicy = Literal["auto", "none", "triangular"]


class DeliverySpecification(BaseModel):
    """One deterministic audio artifact requested from an approved candidate."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    output_path: Path
    sample_rate_hz: int = Field(ge=8_000, le=384_000)
    bit_depth: DeliveryBitDepth
    channels: Literal[1, 2] = 2
    dither: DeliveryDitherPolicy = "auto"
    true_peak_ceiling_dbtp: float | None = Field(default=None, le=0.0)
    integrated_lufs_min: float | None = None
    integrated_lufs_max: float | None = None
    maximum_absolute_dc_offset: float = Field(default=0.001, ge=0.0, le=1.0)
    maximum_leading_silence_seconds: float | None = Field(default=None, ge=0.0)
    maximum_trailing_silence_seconds: float | None = Field(default=None, ge=0.0)
    metadata: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_loudness_bounds(self) -> DeliverySpecification:
        """Keep loudness bounds ordered and metadata deterministic."""

        if (
            self.integrated_lufs_min is not None
            and self.integrated_lufs_max is not None
            and self.integrated_lufs_min > self.integrated_lufs_max
        ):
            raise ValueError("integrated_lufs_min must be <= integrated_lufs_max.")
        for key, value in self.metadata.items():
            if not re.fullmatch(r"[A-Za-z0-9_.-]+", key):
                raise ValueError(f"Unsupported metadata key: {key}")
            if not value or len(value) > 1_000:
                raise ValueError("Metadata values must contain 1 to 1000 characters.")
            if key.lower() == "isrc" and not re.fullmatch(
                r"[A-Z]{2}[A-Z0-9]{3}\d{7}",
                value,
            ):
                raise ValueError(
                    "ISRC metadata must use the 12-character CCXXXYYNNNNN form."
                )
        return self


class DeliveryQcCheck(BaseModel):
    """One final-file verification with expected and observed facts."""

    model_config = ConfigDict(extra="forbid")

    name: str
    passed: bool
    expected: str
    actual: str


class DeliveryArtifact(BaseModel):
    """Published final audio file and its measured QC evidence."""

    model_config = ConfigDict(extra="forbid")

    specification: DeliverySpecification
    applied_dither: Literal["none", "triangular"]
    path: Path
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(gt=0)
    measurement: AudioMeasurementResult
    program_analysis: AudioProgramAnalysisResult
    qc_checks: list[DeliveryQcCheck] = Field(min_length=1)
    qc_passed: Literal[True]


class DeliveryBackendInfo(BaseModel):
    """Transcoder evidence attached to the delivery manifest."""

    model_config = ConfigDict(extra="forbid")

    name: str
    executable_path: Path
    version: str


class CreateDeliveryRequest(BaseModel):
    """Validated final delivery transaction."""

    model_config = ConfigDict(extra="forbid")

    approval: ApprovedMasteringCandidate
    specifications: list[DeliverySpecification] = Field(min_length=1, max_length=20)
    manifest_path: Path
    summary_path: Path

    @model_validator(mode="after")
    def require_unique_paths(self) -> CreateDeliveryRequest:
        """Prevent two artifacts or records from targeting one file."""

        paths = [
            *(specification.output_path for specification in self.specifications),
            self.manifest_path,
            self.summary_path,
        ]
        if len(set(paths)) != len(paths):
            raise ValueError("Delivery output and manifest paths must be unique.")
        return self


class DeliveryManifest(BaseModel):
    """Machine-readable delivery record rooted in human approval evidence."""

    model_config = ConfigDict(extra="forbid")

    manifest_id: str = Field(pattern=r"^dm_[0-9a-f]{24}$")
    approval_id: str
    candidate_id: str
    approved_by: str
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rendered_candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    backend: DeliveryBackendInfo
    artifacts: list[DeliveryArtifact] = Field(min_length=1)
    manifest_path: Path
    summary_path: Path
