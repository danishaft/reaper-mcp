"""Typed tempo and time signature models."""

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

ALLOWED_TIME_SIGNATURE_DENOMINATORS = {1, 2, 4, 8, 16, 32, 64}


class TempoState(BaseModel):
    """Project tempo at the start of the project."""

    model_config = ConfigDict(extra="forbid")

    bpm: float = Field(gt=0.0)


class TimeSignatureState(BaseModel):
    """Project time signature at the start of the project."""

    model_config = ConfigDict(extra="forbid")

    allowed_denominators: ClassVar[set[int]] = ALLOWED_TIME_SIGNATURE_DENOMINATORS

    numerator: int = Field(ge=1, le=32)
    denominator: int = Field(ge=1, le=64)

    @field_validator("denominator")
    @classmethod
    def require_power_of_two_denominator(cls, denominator: int) -> int:
        if denominator not in cls.allowed_denominators:
            msg = "denominator must be one of 1, 2, 4, 8, 16, 32, or 64"
            raise ValueError(msg)
        return denominator


class TempoResult(BaseModel):
    """Stable tempo result shape."""

    model_config = ConfigDict(extra="forbid")

    tempo: TempoState


class SetTempoRequest(BaseModel):
    """Input for setting project tempo."""

    model_config = ConfigDict(extra="forbid")

    bpm: float = Field(ge=20.0, le=400.0)


class SetTempoResult(TempoResult):
    """Result returned after setting project tempo."""

    changes_applied: bool = True


class TimeSignatureResult(BaseModel):
    """Stable time signature result shape."""

    model_config = ConfigDict(extra="forbid")

    time_signature: TimeSignatureState
    tempo: TempoState


class SetTimeSignatureRequest(BaseModel):
    """Input for setting project time signature."""

    model_config = ConfigDict(extra="forbid")

    allowed_denominators: ClassVar[set[int]] = ALLOWED_TIME_SIGNATURE_DENOMINATORS

    numerator: int = Field(ge=1, le=32)
    denominator: int = Field(ge=1, le=64)

    @field_validator("denominator")
    @classmethod
    def require_power_of_two_denominator(cls, denominator: int) -> int:
        if denominator not in cls.allowed_denominators:
            msg = "denominator must be one of 1, 2, 4, 8, 16, 32, or 64"
            raise ValueError(msg)
        return denominator


class SetTimeSignatureResult(TimeSignatureResult):
    """Result returned after setting project time signature."""

    changes_applied: bool = True
