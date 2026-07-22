"""Musical position and conversion models."""

from pydantic import BaseModel, ConfigDict, Field


class MusicalPosition(BaseModel):
    """One-based musical position."""

    model_config = ConfigDict(extra="forbid")

    measure: int = Field(ge=1)
    beat: float = Field(default=1.0, ge=1.0)


class MusicalLength(BaseModel):
    """Musical duration in beats."""

    model_config = ConfigDict(extra="forbid")

    beats: float = Field(gt=0.0)


class PositionConversion(BaseModel):
    """Resolved position in musical, time, and PPQ units."""

    model_config = ConfigDict(extra="forbid")

    start: MusicalPosition
    length: MusicalLength
    start_qn: float
    end_qn: float
    start_seconds: float
    end_seconds: float
    start_ppq: float | None = None
    end_ppq: float | None = None


def musical_position_to_qn(
    position: MusicalPosition,
    beats_per_measure: float,
) -> float:
    """Convert a measure and beat position into project quarter-note position."""

    return ((position.measure - 1) * beats_per_measure) + (position.beat - 1)


def musical_range_to_qn(
    position: MusicalPosition,
    length: MusicalLength,
    beats_per_measure: float,
) -> tuple[float, float]:
    """Convert a musical range into start and end quarter-note positions."""

    start_qn = musical_position_to_qn(position, beats_per_measure)
    return start_qn, start_qn + length.beats
