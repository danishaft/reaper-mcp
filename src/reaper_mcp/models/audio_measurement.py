"""Typed full-program audio measurement contracts."""

from __future__ import annotations

import math
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class AudioMeasurementRequest(BaseModel):
    """Request standards-based analysis for an approved local audio file."""

    model_config = ConfigDict(extra="forbid")

    audio_path: Path
    start_seconds: float = Field(default=0.0, ge=0.0)
    end_seconds: float | None = Field(default=None, gt=0.0)
    normalization_targets_lufs: dict[str, float] = Field(default_factory=dict)

    @field_validator("normalization_targets_lufs")
    @classmethod
    def validate_normalization_targets(
        cls, targets: dict[str, float]
    ) -> dict[str, float]:
        """Reject unnamed or nonsensical playback simulations."""

        validated: dict[str, float] = {}
        for raw_name, target in targets.items():
            name = raw_name.strip()
            if not name:
                raise ValueError("Normalization target names cannot be empty.")
            if not math.isfinite(target) or not -70.0 <= target <= 0.0:
                raise ValueError(
                    "Normalization targets must be finite values from -70 to 0 LUFS."
                )
            validated[name] = target
        return validated

    @model_validator(mode="after")
    def validate_bounds(self) -> AudioMeasurementRequest:
        """Require a non-empty forward measurement interval."""

        if self.end_seconds is not None and self.end_seconds <= self.start_seconds:
            raise ValueError("end_seconds must be greater than start_seconds.")
        return self


class AudioMeasurementBounds(BaseModel):
    """Requested bounds and the duration observed by the meter."""

    model_config = ConfigDict(extra="forbid")

    start_seconds: float = Field(ge=0.0)
    end_seconds: float | None = Field(default=None, gt=0.0)
    measured_duration_seconds: float = Field(ge=0.0)


class AudioMeasurementBackendInfo(BaseModel):
    """Backend identity included with every measurement."""

    model_config = ConfigDict(extra="forbid")

    name: str
    executable_path: Path
    version: str


class LoudnessMeasurement(BaseModel):
    """EBU R128 loudness values with explicit units in field names."""

    model_config = ConfigDict(extra="forbid")

    integrated_lufs: float | None = None
    momentary_max_lufs: float | None = None
    short_term_max_lufs: float | None = None
    loudness_range_lu: float | None = Field(default=None, ge=0.0)
    integrated_threshold_lufs: float | None = None
    range_threshold_lufs: float | None = None
    range_low_lufs: float | None = None
    range_high_lufs: float | None = None


class PeakMeasurement(BaseModel):
    """Sample and reconstructed true peaks kept as different measurements."""

    model_config = ConfigDict(extra="forbid")

    sample_peak_dbfs: float | None = None
    true_peak_dbtp: float | None = None


class DynamicsMeasurement(BaseModel):
    """Derived program dynamics without inventing an artistic target."""

    model_config = ConfigDict(extra="forbid")

    peak_to_loudness_ratio_db: float | None = None


class StereoMeasurement(BaseModel):
    """Channel layout and stereo phase behavior observed by FFmpeg."""

    model_config = ConfigDict(extra="forbid")

    channel_layout: str | None = None
    phase_correlation_mean: float | None = Field(default=None, ge=-1.0, le=1.0)
    phase_correlation_minimum: float | None = Field(default=None, ge=-1.0, le=1.0)


class AudioMeasurementQuality(BaseModel):
    """Machine checks about completeness and source integrity."""

    model_config = ConfigDict(extra="forbid")

    complete_loudness_metrics: bool
    sample_peak_available: bool
    true_peak_available: bool
    loudness_range_stable: bool
    source_integrity_verified: bool


class AudioTechnicalProperties(BaseModel):
    """Input stream properties reported by the configured FFmpeg backend."""

    model_config = ConfigDict(extra="forbid")

    codec: str | None = None
    sample_rate_hz: int | None = Field(default=None, gt=0)
    channel_layout: str | None = None
    sample_format: str | None = None
    effective_bit_depth: int | None = Field(default=None, gt=0)


class PlaybackNormalizationSimulation(BaseModel):
    """Non-destructive playback gain for one caller-supplied target."""

    model_config = ConfigDict(extra="forbid")

    name: str
    target_lufs: float
    gain_adjustment_db: float
    predicted_true_peak_dbtp: float | None = None


class AudioMeasurementResult(BaseModel):
    """Complete typed result for one measured source and interval."""

    model_config = ConfigDict(extra="forbid")

    path: Path
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    standard: str
    backend: AudioMeasurementBackendInfo
    bounds: AudioMeasurementBounds
    loudness: LoudnessMeasurement
    peaks: PeakMeasurement
    dynamics: DynamicsMeasurement
    stereo: StereoMeasurement
    quality: AudioMeasurementQuality
    technical: AudioTechnicalProperties = Field(
        default_factory=AudioTechnicalProperties
    )
    normalization_simulations: list[PlaybackNormalizationSimulation] = Field(
        default_factory=list
    )
    warnings: list[str] = Field(default_factory=list)
