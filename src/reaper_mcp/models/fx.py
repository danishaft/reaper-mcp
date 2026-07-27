"""Typed FX models."""

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TrackFxRequest(BaseModel):
    """Input for listing FX on one track."""

    model_config = ConfigDict(extra="forbid")

    track_guid: str = Field(min_length=1)


class TakeFxRequest(BaseModel):
    """Input for listing FX on one media take."""

    model_config = ConfigDict(extra="forbid")

    take_guid: str = Field(min_length=1)


class TakeFxIdentity(BaseModel):
    """Guarded identity for mutating one take FX slot."""

    model_config = ConfigDict(extra="forbid")

    take_guid: str = Field(min_length=1)
    index: int = Field(ge=0)
    expected_name: str = Field(min_length=1)
    expected_guid: str | None = None


class TakeFxSnapshot(BaseModel):
    """Read-only FX state for one media take FX slot."""

    model_config = ConfigDict(extra="forbid")

    identity: str = Field(min_length=1)
    take_guid: str = Field(min_length=1)
    index: int = Field(ge=0)
    name: str = Field(min_length=1)
    enabled: bool = True
    offline: bool = False
    guid: str | None = None


class TakeFxList(BaseModel):
    """Read-only list of FX on one media take."""

    model_config = ConfigDict(extra="forbid")

    take_guid: str = Field(min_length=1)
    fx: list[TakeFxSnapshot] = Field(default_factory=list)
    fx_count: int = 0


class AddTakeFxResult(TakeFxList):
    """Result returned after adding one take FX slot."""

    added_fx: TakeFxSnapshot
    changes_applied: bool = True


class RemoveTakeFxResult(TakeFxList):
    """Result returned after removing one take FX slot."""

    removed_fx_identity: str = Field(min_length=1)
    changes_applied: bool = True


class SetTakeFxEnabledResult(TakeFxList):
    """Result returned after changing one take FX enabled state."""

    updated_fx: TakeFxSnapshot
    changes_applied: bool = True


class AddTakeFxRequest(BaseModel):
    """Input for adding one FX to a media take."""

    model_config = ConfigDict(extra="forbid")

    take_guid: str = Field(min_length=1)
    fx_identifier: str = Field(min_length=1)
    index: int | None = Field(default=None, ge=0)
    enabled: bool = True


class RemoveTakeFxRequest(BaseModel):
    """Input for removing one guarded take FX slot."""

    model_config = ConfigDict(extra="forbid")

    fx_identity: TakeFxIdentity


class SetTakeFxEnabledRequest(BaseModel):
    """Input for changing one guarded take FX enabled state."""

    model_config = ConfigDict(extra="forbid")

    fx_identity: TakeFxIdentity
    enabled: bool


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


class FxPresetSnapshot(BaseModel):
    """Current preset state for one guarded FX slot."""

    model_config = ConfigDict(extra="forbid")

    fx_identity: FxIdentity
    preset_name: str = ""


class FxPresetResult(FxPresetSnapshot):
    """Result returned after reading or setting an FX preset."""

    changes_applied: bool = False


class FxPresetBankSnapshot(BaseModel):
    """Current preset index and count for one guarded FX slot."""

    model_config = ConfigDict(extra="forbid")

    fx_identity: FxIdentity
    preset_index: int
    preset_count: int = Field(ge=0)
    preset_name: str = ""


class FxPresetBankResult(FxPresetBankSnapshot):
    """Result returned after reading or changing an FX preset index."""

    changes_applied: bool = False


class SetFxPresetIndexRequest(BaseModel):
    """Input for selecting a factory or user preset by index."""

    model_config = ConfigDict(extra="forbid")

    fx_identity: FxIdentity
    preset_index: int = Field(ge=-2)


class NavigateFxPresetsRequest(BaseModel):
    """Input for moving within an FX preset bank."""

    model_config = ConfigDict(extra="forbid")

    fx_identity: FxIdentity
    direction: int

    @model_validator(mode="after")
    def require_non_zero_direction(self) -> "NavigateFxPresetsRequest":
        if self.direction == 0:
            raise ValueError("direction must not be zero")
        return self


class MoveFxResult(TrackFxList):
    """Result returned after moving one FX in a chain."""

    moved_fx: FxSnapshot
    changes_applied: bool = True


class CopyFxChainResult(TrackFxList):
    """Result returned after copying a complete FX chain."""

    source_track_guid: str = Field(min_length=1)
    changes_applied: bool = True


class MoveFxRequest(BaseModel):
    """Input for moving one guarded FX slot."""

    model_config = ConfigDict(extra="forbid")

    fx_identity: FxIdentity
    destination_index: int = Field(ge=0)


class SetFxPresetRequest(BaseModel):
    """Input for setting one guarded FX preset."""

    model_config = ConfigDict(extra="forbid")

    fx_identity: FxIdentity
    preset_name: str = Field(min_length=1, max_length=200)


class CopyFxChainRequest(BaseModel):
    """Input for copying one track FX chain to another track."""

    model_config = ConfigDict(extra="forbid")

    source_track_guid: str = Field(min_length=1)
    destination_track_guid: str = Field(min_length=1)
    replace_destination: bool = False
