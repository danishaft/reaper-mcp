"""Typed contracts for provider-backed vocal pitch correction."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from reaper_mcp.models.fx import FxIdentity, FxParameterSnapshot, FxSnapshot

VocalTuningProviderId = Literal["reaper_take_pitch", "reatune", "x42_autotune"]
VocalTuningMode = Literal["transparent_repair", "creative_effect"]
VocalTuningControlMode = Literal[
    "segment_pitch",
    "plugin_parameters",
    "plugin_preset",
    "plugin_ui_only",
]
VocalTuningScale = Literal["major", "natural_minor", "chromatic"]


class VocalTuningProviderCapability(BaseModel):
    """Observed availability and verified controls for one tuning provider."""

    model_config = ConfigDict(extra="forbid")

    provider_id: VocalTuningProviderId
    display_name: str = Field(min_length=1)
    installed: bool
    control_mode: VocalTuningControlMode
    supports_analysis: bool
    supports_preview: bool
    supports_apply: bool
    supported_modes: list[VocalTuningMode] = Field(default_factory=list)
    reason: str = Field(min_length=1)


class PitchCorrectionSegment(BaseModel):
    """One engineer-reviewed static pitch correction in project time."""

    model_config = ConfigDict(extra="forbid")

    segment_id: str = Field(min_length=1, max_length=120)
    start_seconds: float = Field(ge=0.0)
    end_seconds: float = Field(gt=0.0)
    correction_cents: float = Field(ge=-200.0, le=200.0)
    observed_note_midi: int | None = Field(default=None, ge=0, le=127)
    target_note_midi: int | None = Field(default=None, ge=0, le=127)
    preserve_vibrato: bool = True
    rationale: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_range_and_change(self) -> Self:
        """Reject empty ranges and pitch no-ops."""

        if self.end_seconds <= self.start_seconds:
            raise ValueError("end_seconds must be greater than start_seconds")
        if abs(self.correction_cents) < 0.000001:
            raise ValueError("correction_cents must not be zero")
        return self


class PreviewVocalTuningPlanRequest(BaseModel):
    """Validated input for a complete vocal-tuning preview."""

    model_config = ConfigDict(extra="forbid")

    provider_id: VocalTuningProviderId
    mode: VocalTuningMode
    track_guid: str = Field(min_length=1)
    item_guid: str = Field(min_length=1)
    take_guid: str = Field(min_length=1)
    corrections: list[PitchCorrectionSegment] = Field(min_length=1, max_length=512)

    @model_validator(mode="after")
    def validate_correction_order(self) -> Self:
        """Require unique, chronological, non-overlapping corrections."""

        segment_ids: set[str] = set()
        previous_end: float | None = None
        for correction in self.corrections:
            if correction.segment_id in segment_ids:
                raise ValueError("segment_id values must be unique")
            if previous_end is not None and correction.start_seconds < previous_end:
                raise ValueError(
                    "corrections must be chronological and must not overlap"
                )
            segment_ids.add(correction.segment_id)
            previous_end = correction.end_seconds
        return self


class VocalTuningContext(BaseModel):
    """Observed project, item, and take state bound to one tuning plan."""

    model_config = ConfigDict(extra="forbid")

    project_path: str
    project_name: str
    state_change_count: int = Field(ge=0)
    track_guid: str = Field(min_length=1)
    item_guid: str = Field(min_length=1)
    item_name: str = ""
    item_position_seconds: float = Field(ge=0.0)
    item_length_seconds: float = Field(gt=0.0)
    take_guid: str = Field(min_length=1)
    take_name: str = ""
    take_count: int = Field(ge=1)
    take_pitch_semitones: float = Field(ge=-80.0, le=80.0)


class VocalTuningPlan(BaseModel):
    """Immutable correction plan that requires its exact approval hash."""

    model_config = ConfigDict(extra="forbid")

    plan_id: str = Field(pattern=r"^vtp_[0-9a-f]{24}$")
    approval_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider_id: VocalTuningProviderId
    mode: VocalTuningMode
    context: VocalTuningContext
    context_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    corrections: list[PitchCorrectionSegment] = Field(min_length=1, max_length=512)
    warnings: list[str] = Field(default_factory=list)


class AppliedPitchCorrectionSegment(BaseModel):
    """Observed REAPER segment after one approved correction."""

    model_config = ConfigDict(extra="forbid")

    segment_id: str = Field(min_length=1)
    item_guid: str = Field(min_length=1)
    take_guid: str = Field(min_length=1)
    start_seconds: float = Field(ge=0.0)
    end_seconds: float = Field(gt=0.0)
    correction_cents: float = Field(ge=-200.0, le=200.0)
    result_pitch_semitones: float = Field(ge=-80.0, le=80.0)


class VocalTuningPlanApplication(BaseModel):
    """Observed result of one approved, undoable tuning transaction."""

    model_config = ConfigDict(extra="forbid")

    approval_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider_id: VocalTuningProviderId
    applied_correction_count: int = Field(gt=0)
    segments: list[AppliedPitchCorrectionSegment] = Field(min_length=1)
    changes_applied: bool

    @model_validator(mode="after")
    def validate_correction_count(self) -> Self:
        """Keep the reported count consistent with observed segments."""

        if self.applied_correction_count != len(self.segments):
            raise ValueError("applied_correction_count must match segments")
        return self


class PreviewVocalTuningPresetPlanRequest(BaseModel):
    """Validated input for recalling an engineer-authored tuning preset."""

    model_config = ConfigDict(extra="forbid")

    provider_id: VocalTuningProviderId
    mode: VocalTuningMode
    track_guid: str = Field(min_length=1)
    preset_name: str = Field(min_length=1, max_length=200)
    insert_index: Literal[0] = 0


class VocalTuningPresetContext(BaseModel):
    """Observed project, track, and FX state bound to one preset plan."""

    model_config = ConfigDict(extra="forbid")

    project_path: str
    project_name: str
    state_change_count: int = Field(ge=0)
    track_guid: str = Field(min_length=1)
    track_name: str = ""
    installed_fx_identifier: str = Field(min_length=1)
    insert_index: Literal[0] = 0
    existing_fx_identity: FxIdentity | None = None
    existing_preset_name: str | None = None

    @model_validator(mode="after")
    def validate_existing_fx_state(self) -> Self:
        """Keep the guarded FX identity and rollback preset paired."""

        has_identity = self.existing_fx_identity is not None
        has_preset = self.existing_preset_name is not None
        if has_identity != has_preset:
            raise ValueError(
                "existing_fx_identity and existing_preset_name must be paired"
            )
        return self


class VocalTuningPresetPlan(BaseModel):
    """Immutable preset-recall plan requiring its exact approval hash."""

    model_config = ConfigDict(extra="forbid")

    plan_id: str = Field(pattern=r"^vtp_[0-9a-f]{24}$")
    approval_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider_id: VocalTuningProviderId
    mode: VocalTuningMode
    context: VocalTuningPresetContext
    context_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    preset_name: str = Field(min_length=1, max_length=200)
    warnings: list[str] = Field(default_factory=list)


class VocalTuningPresetPlanApplication(BaseModel):
    """Verified result of one approved tuning-preset transaction."""

    model_config = ConfigDict(extra="forbid")

    approval_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider_id: VocalTuningProviderId
    track_guid: str = Field(min_length=1)
    track_name: str = ""
    fx: FxSnapshot
    preset_name: str = Field(min_length=1)
    preset_index: int
    preset_count: int = Field(ge=0)
    inserted: bool
    changes_applied: bool


class X42AutoTuneSettings(BaseModel):
    """Musical and correction controls exposed by x42 Auto Tune."""

    model_config = ConfigDict(extra="forbid")

    root_pitch_class: int = Field(ge=0, le=11)
    scale: VocalTuningScale
    correction_amount: float = Field(ge=0.0, le=1.0)
    smoothing_seconds: float = Field(ge=0.02, le=0.5)
    bias: float = Field(ge=0.0, le=1.0)
    tuning_hz: float = Field(default=440.0, ge=400.0, le=480.0)
    fast_correction: bool = False
    wet: float = Field(default=1.0, ge=0.0, le=1.0)


class PreviewVocalTuningPluginPlanRequest(BaseModel):
    """Validated input for an automatable tuning-plugin plan."""

    model_config = ConfigDict(extra="forbid")

    provider_id: VocalTuningProviderId
    mode: VocalTuningMode
    track_guid: str = Field(min_length=1)
    settings: X42AutoTuneSettings
    insert_index: Literal[0] = 0


class VocalTuningParameterState(BaseModel):
    """One guarded plugin parameter and its normalized value."""

    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=0)
    name: str = Field(min_length=1)
    normalized_value: float = Field(ge=0.0, le=1.0)


class VocalTuningPluginContext(BaseModel):
    """Observed project, track, FX, and restorable parameter state."""

    model_config = ConfigDict(extra="forbid")

    project_path: str
    project_name: str
    state_change_count: int = Field(ge=0)
    track_guid: str = Field(min_length=1)
    track_name: str = ""
    installed_fx_identifier: str = Field(min_length=1)
    insert_index: Literal[0] = 0
    existing_fx_identity: FxIdentity | None = None
    existing_fx_enabled: bool | None = None
    current_parameters: list[VocalTuningParameterState] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_existing_fx_state(self) -> Self:
        """Require a complete rollback snapshot for an existing instance."""

        has_identity = self.existing_fx_identity is not None
        has_enabled = self.existing_fx_enabled is not None
        has_parameters = bool(self.current_parameters)
        if has_identity != has_enabled or has_identity != has_parameters:
            raise ValueError(
                "existing FX identity, enabled state, and parameters must be paired"
            )
        return self


class VocalTuningPluginPlan(BaseModel):
    """Immutable automatable-plugin plan requiring exact approval."""

    model_config = ConfigDict(extra="forbid")

    plan_id: str = Field(pattern=r"^vtp_[0-9a-f]{24}$")
    approval_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider_id: VocalTuningProviderId
    mode: VocalTuningMode
    context: VocalTuningPluginContext
    context_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    settings: X42AutoTuneSettings
    target_parameters: list[VocalTuningParameterState] = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)


class VocalTuningPluginPlanApplication(BaseModel):
    """Verified result of one automatable tuning-plugin transaction."""

    model_config = ConfigDict(extra="forbid")

    approval_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider_id: VocalTuningProviderId
    track_guid: str = Field(min_length=1)
    track_name: str = ""
    fx: FxSnapshot
    parameters: list[FxParameterSnapshot] = Field(min_length=1)
    inserted: bool
    changes_applied: bool
