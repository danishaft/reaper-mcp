"""Typed audio-analysis results."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class AudioAnalysisResult(BaseModel):
    """Measured properties of one PCM WAV file."""

    model_config = ConfigDict(extra="forbid")

    path: Path
    format: str = "wav_pcm"
    channels: int = Field(gt=0)
    sample_rate: int = Field(gt=0)
    frame_count: int = Field(ge=0)
    duration_seconds: float = Field(ge=0.0)
    peak_dbfs: float
    rms_dbfs: float
    clipping_samples: int = Field(ge=0)
    dc_offset: float
    stereo_correlation: float | None = Field(default=None, ge=-1.0, le=1.0)
    spectral_centroid_hz: float | None = Field(default=None, ge=0.0)
    unsupported_metrics: list[str] = Field(default_factory=list)


class TakeLoudnessResult(BaseModel):
    """Non-mutating loudness result for one media take."""

    model_config = ConfigDict(extra="forbid")

    take_guid: str = Field(min_length=1)
    calculation_status: int
    source_path: Path | None = None
    analysis: AudioAnalysisResult | None = None
    lufs_i: float | None = None
    normalization_adjustment_db: float | None = None
    render_stats: str = ""
    render_stats_summary: str = ""
