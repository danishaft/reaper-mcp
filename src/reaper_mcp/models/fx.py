"""Typed FX models."""

from pydantic import BaseModel, ConfigDict, Field


class TrackFxRequest(BaseModel):
    """Input for listing FX on one track."""

    model_config = ConfigDict(extra="forbid")

    track_guid: str = Field(min_length=1)


class FxSnapshot(BaseModel):
    """Read-only FX state for one track FX slot."""

    model_config = ConfigDict(extra="forbid")

    identity: str = Field(min_length=1)
    track_guid: str = Field(min_length=1)
    index: int = Field(ge=0)
    name: str = Field(min_length=1)
    enabled: bool = True
    offline: bool = False
    guid: str | None = None


class AvailableFxSnapshot(BaseModel):
    """Read-only installed FX entry."""

    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=0)
    name: str = Field(min_length=1)
    identifier: str = Field(min_length=1)


class AvailableFxList(BaseModel):
    """Read-only list of installed FX entries."""

    model_config = ConfigDict(extra="forbid")

    fx: list[AvailableFxSnapshot] = Field(default_factory=list)
    fx_count: int = 0


class FxIdentity(BaseModel):
    """Guarded identity for mutating one track FX slot."""

    model_config = ConfigDict(extra="forbid")

    track_guid: str = Field(min_length=1)
    index: int = Field(ge=0)
    expected_identity: str = Field(min_length=1)
    expected_name: str = Field(min_length=1)
    expected_guid: str | None = None


class TrackFxList(BaseModel):
    """Read-only list of FX on one track."""

    model_config = ConfigDict(extra="forbid")

    track_guid: str = Field(min_length=1)
    fx: list[FxSnapshot] = Field(default_factory=list)
    fx_count: int = 0


class FxParameterSnapshot(BaseModel):
    """Read-only FX parameter state."""

    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=0)
    name: str = Field(min_length=1)
    normalized_value: float = Field(ge=0.0, le=1.0)
    formatted_value: str = ""


class FxParameterList(BaseModel):
    """Read-only parameter list for one guarded FX slot."""

    model_config = ConfigDict(extra="forbid")

    fx_identity: FxIdentity
    parameters: list[FxParameterSnapshot] = Field(default_factory=list)
    parameter_count: int = 0


class AddFxRequest(BaseModel):
    """Input for adding one FX to a track."""

    model_config = ConfigDict(extra="forbid")

    track_guid: str = Field(min_length=1)
    fx_identifier: str = Field(min_length=1)
    index: int | None = Field(default=None, ge=0)
    enabled: bool = True


class AddFxResult(TrackFxList):
    """Result returned after adding one FX."""

    added_fx: FxSnapshot
    changes_applied: bool = True


class RemoveFxRequest(BaseModel):
    """Input for removing one guarded FX slot."""

    model_config = ConfigDict(extra="forbid")

    fx_identity: FxIdentity


class RemoveFxResult(TrackFxList):
    """Result returned after removing one FX."""

    removed_fx_identity: str = Field(min_length=1)
    changes_applied: bool = True


class SetFxEnabledRequest(BaseModel):
    """Input for changing one guarded FX enabled state."""

    model_config = ConfigDict(extra="forbid")

    fx_identity: FxIdentity
    enabled: bool


class SetFxEnabledResult(TrackFxList):
    """Result returned after changing one FX enabled state."""

    updated_fx: FxSnapshot
    changes_applied: bool = True


class GetFxParametersRequest(BaseModel):
    """Input for reading parameters from one guarded FX slot."""

    model_config = ConfigDict(extra="forbid")

    fx_identity: FxIdentity


class SetFxParameterRequest(BaseModel):
    """Input for changing one normalized FX parameter value."""

    model_config = ConfigDict(extra="forbid")

    fx_identity: FxIdentity
    parameter_index: int = Field(ge=0)
    normalized_value: float = Field(ge=0.0, le=1.0)


class SetFxParameterResult(FxParameterList):
    """Result returned after changing one FX parameter."""

    updated_parameter: FxParameterSnapshot
    changes_applied: bool = True
