"""Typed tempo and time signature models."""

from typing import ClassVar, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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


class TempoMarkerSnapshot(BaseModel):
    """Read-only tempo-map marker state."""

    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=0)
    fingerprint: str = Field(min_length=1)
    position_seconds: float = Field(ge=0.0)
    position_qn: float = Field(ge=0.0)
    bpm: float = Field(gt=0.0)
    numerator: int = Field(ge=1, le=32)
    denominator: int = Field(ge=1, le=64)
    linear: bool = False

    @field_validator("denominator")
    @classmethod
    def require_supported_denominator(cls, denominator: int) -> int:
        if denominator not in ALLOWED_TIME_SIGNATURE_DENOMINATORS:
            raise ValueError("unsupported tempo-marker denominator")
        return denominator


class TempoMarkerList(BaseModel):
    """Read-only tempo-map marker list."""

    model_config = ConfigDict(extra="forbid")

    markers: list[TempoMarkerSnapshot] = Field(default_factory=list)
    marker_count: int = 0

    @model_validator(mode="after")
    def validate_marker_count(self) -> Self:
        if self.marker_count != len(self.markers):
            raise ValueError("marker_count must equal the number of markers")
        return self


class TempoMarkerInput(BaseModel):
    """Input for creating or updating one tempo-map marker."""

    model_config = ConfigDict(extra="forbid")

    position_seconds: float = Field(ge=0.0)
    bpm: float = Field(ge=20.0, le=400.0)
    numerator: int = Field(default=4, ge=1, le=32)
    denominator: int = Field(default=4, ge=1, le=64)
    linear: bool = False

    @field_validator("denominator")
    @classmethod
    def require_supported_denominator(cls, denominator: int) -> int:
        if denominator not in ALLOWED_TIME_SIGNATURE_DENOMINATORS:
            raise ValueError("unsupported tempo-marker denominator")
        return denominator


class TempoMarkerIdentity(BaseModel):
    """Guarded identity for one tempo-map marker."""

    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=0)
    expected_fingerprint: str = Field(min_length=1)


class TempoMarkerMutationResult(TempoMarkerList):
    """Result returned after changing a tempo-map marker."""

    marker: TempoMarkerSnapshot | None = None
    deleted_marker_index: int | None = None
    changes_applied: bool = True
