"""Typed full-program technical and broad-band analysis."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from reaper_mcp.models.audio_measurement import AudioMeasurementBackendInfo


class FrequencyBandLevel(BaseModel):
    """One broad frequency band's program RMS and level-relative balance."""

    model_config = ConfigDict(extra="forbid")

    name: str
    low_hz: float = Field(ge=0.0)
    high_hz: float | None = Field(default=None, gt=0.0)
    rms_dbfs: float
    balance_to_full_range_db: float


class SilenceInterval(BaseModel):
    """One contiguous interval below the configured silence threshold."""

    model_config = ConfigDict(extra="forbid")

    start_seconds: float = Field(ge=0.0)
    end_seconds: float = Field(ge=0.0)
    duration_seconds: float = Field(ge=0.0)


class ProgramSilenceAnalysis(BaseModel):
    """Full-program silence and boundary facts."""

    model_config = ConfigDict(extra="forbid")

    threshold_dbfs: float
    minimum_duration_seconds: float = Field(gt=0.0)
    leading_silence_seconds: float = Field(ge=0.0)
    trailing_silence_seconds: float = Field(ge=0.0)
    total_silence_seconds: float = Field(ge=0.0)
    intervals: list[SilenceInterval] = Field(default_factory=list)


class AudioProgramAnalysisResult(BaseModel):
    """Source-integrity-checked technical and broad spectral program facts."""

    model_config = ConfigDict(extra="forbid")

    path: Path
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    backend: AudioMeasurementBackendInfo
    duration_seconds: float = Field(gt=0.0)
    sample_rate_hz: int = Field(gt=0)
    sample_count_per_channel: int = Field(gt=0)
    sample_peak_dbfs: float
    full_range_rms_dbfs: float
    maximum_absolute_dc_offset: float = Field(ge=0.0)
    clipping_detected: bool
    bands: list[FrequencyBandLevel] = Field(min_length=4, max_length=4)
    silence: ProgramSilenceAnalysis
    source_integrity_verified: bool
    warnings: list[str] = Field(default_factory=list)
