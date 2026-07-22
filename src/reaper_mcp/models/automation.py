"""Typed track automation envelope models."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

AutomationMode = Literal[
    "trim_read",
    "read",
    "touch",
    "write",
    "latch",
    "latch_preview",
]
EnvelopeType = Literal[
    "volume",
    "pan",
    "mute",
    "pre_fx_volume",
    "pre_fx_pan",
    "trim_volume",
]


class EnvelopePointSnapshot(BaseModel):
    """One guarded point on a track envelope."""

    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=0)
    fingerprint: str = Field(min_length=1)
    time_seconds: float = Field(ge=0.0)
    value: float
    shape: int = Field(ge=0, le=5)
    tension: float = Field(ge=-1.0, le=1.0)
    selected: bool = False
    formatted_value: str = ""


class EnvelopeSnapshot(BaseModel):
    """One track envelope with stable REAPER identity."""

    model_config = ConfigDict(extra="forbid")

    guid: str = Field(min_length=1)
    track_guid: str = Field(min_length=1)
    index: int = Field(ge=0)
    name: str = Field(min_length=1)
    point_count: int = Field(ge=0)


class EnvelopeList(BaseModel):
    """Track envelopes in REAPER order."""

    model_config = ConfigDict(extra="forbid")

    track_guid: str = Field(min_length=1)
    envelopes: list[EnvelopeSnapshot] = Field(default_factory=list)
    envelope_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_count(self) -> Self:
        if self.envelope_count != len(self.envelopes):
            raise ValueError("envelope_count must equal the number of envelopes")
        return self


class EnsureEnvelopeResult(BaseModel):
    """Envelope returned after ensuring one built-in track envelope exists."""

    model_config = ConfigDict(extra="forbid")

    envelope: EnvelopeSnapshot
    created: bool
    changes_applied: bool


class EnvelopePointList(BaseModel):
    """Envelope points in timeline order."""

    model_config = ConfigDict(extra="forbid")

    envelope: EnvelopeSnapshot
    points: list[EnvelopePointSnapshot] = Field(default_factory=list)
    point_count: int = Field(ge=0)
    changes_applied: bool = False

    @model_validator(mode="after")
    def validate_count(self) -> Self:
        if self.point_count != len(self.points):
            raise ValueError("point_count must equal the number of points")
        return self


class EnvelopeIdentity(BaseModel):
    """Stable identity for one track envelope."""

    model_config = ConfigDict(extra="forbid")

    track_guid: str = Field(min_length=1)
    envelope_guid: str = Field(min_length=1)


class EnvelopePointIdentity(BaseModel):
    """Index and fingerprint guard for one envelope point."""

    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=0)
    expected_fingerprint: str = Field(min_length=1)


class EnvelopePointInput(BaseModel):
    """Values for one new envelope point."""

    model_config = ConfigDict(extra="forbid")

    time_seconds: float = Field(ge=0.0)
    value: float
    shape: int = Field(default=0, ge=0, le=5)
    tension: float = Field(default=0.0, ge=-1.0, le=1.0)
    selected: bool = False


class AddEnvelopePointsRequest(BaseModel):
    """Input for one atomic envelope point insertion batch."""

    model_config = ConfigDict(extra="forbid")

    envelope_identity: EnvelopeIdentity
    points: list[EnvelopePointInput] = Field(min_length=1, max_length=4096)

    @model_validator(mode="after")
    def require_unique_times(self) -> Self:
        times = [point.time_seconds for point in self.points]
        if len(set(times)) != len(times):
            raise ValueError("points must not contain duplicate times")
        return self


class UpdateEnvelopePointRequest(BaseModel):
    """Input for changing one guarded envelope point."""

    model_config = ConfigDict(extra="forbid")

    envelope_identity: EnvelopeIdentity
    point_identity: EnvelopePointIdentity
    time_seconds: float | None = Field(default=None, ge=0.0)
    value: float | None = None
    shape: int | None = Field(default=None, ge=0, le=5)
    tension: float | None = Field(default=None, ge=-1.0, le=1.0)
    selected: bool | None = None

    @model_validator(mode="after")
    def require_change(self) -> Self:
        values = (
            self.time_seconds,
            self.value,
            self.shape,
            self.tension,
            self.selected,
        )
        if all(value is None for value in values):
            raise ValueError("at least one envelope point property must be provided")
        return self


class DeleteEnvelopePointsRequest(BaseModel):
    """Input for deleting guarded envelope points."""

    model_config = ConfigDict(extra="forbid")

    envelope_identity: EnvelopeIdentity
    points: list[EnvelopePointIdentity] = Field(min_length=1, max_length=4096)

    @model_validator(mode="after")
    def require_unique_indexes(self) -> Self:
        indexes = [point.index for point in self.points]
        if len(set(indexes)) != len(indexes):
            raise ValueError("points must not contain duplicate indexes")
        return self


class DeleteEnvelopePointRangeRequest(BaseModel):
    """Input for deleting all envelope points in a half-open range."""

    model_config = ConfigDict(extra="forbid")

    envelope_identity: EnvelopeIdentity
    start_seconds: float = Field(ge=0.0)
    end_seconds: float = Field(gt=0.0)

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if self.end_seconds <= self.start_seconds:
            raise ValueError("end_seconds must be greater than start_seconds")
        return self


class TrackAutomationModeResult(BaseModel):
    """Current automation mode for one track."""

    model_config = ConfigDict(extra="forbid")

    track_guid: str = Field(min_length=1)
    mode: AutomationMode
    changes_applied: bool = False


class SetTrackAutomationModeRequest(BaseModel):
    """Input for changing one track's automation mode."""

    model_config = ConfigDict(extra="forbid")

    track_guid: str = Field(min_length=1)
    mode: AutomationMode
