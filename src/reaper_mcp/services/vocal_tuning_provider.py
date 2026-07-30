"""Provider registry for verified vocal-tuning control paths."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from reaper_mcp.models.vocal_tuning import (
    VocalTuningParameterState,
    VocalTuningPlan,
    VocalTuningPluginPlan,
    VocalTuningPresetPlan,
    VocalTuningProviderCapability,
    VocalTuningProviderId,
    X42AutoTuneSettings,
)


class VocalTuningProvider(Protocol):
    """Define the provider behavior used by the tuning workflow."""

    provider_id: VocalTuningProviderId

    def capability(
        self, available_fx: Sequence[Mapping[str, Any]]
    ) -> VocalTuningProviderCapability:
        """Return observed provider availability and verified controls."""

    def build_apply_args(
        self,
        plan: VocalTuningPlan,
        approval_hash: str,
    ) -> tuple[str, dict[str, Any]] | None:
        """Return the bridge command and arguments for an approved plan."""

    def resolve_fx_identifier(
        self, available_fx: Sequence[Mapping[str, Any]]
    ) -> str | None:
        """Return the exact installed FX identifier used by this provider."""

    def build_preset_apply_args(
        self,
        plan: VocalTuningPresetPlan,
        approval_hash: str,
    ) -> tuple[str, dict[str, Any]] | None:
        """Return the bridge command and arguments for an approved preset plan."""

    def parameter_targets(
        self, settings: X42AutoTuneSettings
    ) -> list[VocalTuningParameterState] | None:
        """Return the verified parameter targets for an automatable provider."""

    def build_plugin_apply_args(
        self,
        plan: VocalTuningPluginPlan,
        approval_hash: str,
    ) -> tuple[str, dict[str, Any]] | None:
        """Return the bridge command and arguments for an approved plugin plan."""


class ReaperTakePitchProvider:
    """Apply static note-segment offsets through stable REAPER take APIs."""

    provider_id: VocalTuningProviderId = "reaper_take_pitch"

    def capability(
        self, available_fx: Sequence[Mapping[str, Any]]
    ) -> VocalTuningProviderCapability:
        del available_fx
        return VocalTuningProviderCapability(
            provider_id=self.provider_id,
            display_name="REAPER take pitch",
            installed=True,
            control_mode="segment_pitch",
            supports_analysis=False,
            supports_preview=True,
            supports_apply=True,
            supported_modes=["transparent_repair", "creative_effect"],
            reason=(
                "Uses stable item splitting and take D_PITCH controls. It applies "
                "supplied note corrections but does not detect notes."
            ),
        )

    def build_apply_args(
        self,
        plan: VocalTuningPlan,
        approval_hash: str,
    ) -> tuple[str, dict[str, Any]]:
        return (
            "apply_vocal_tuning_plan",
            {
                "approval_hash": approval_hash,
                "provider_id": self.provider_id,
                "context": plan.context.model_dump(mode="json"),
                "corrections": [
                    correction.model_dump(mode="json")
                    for correction in plan.corrections
                ],
            },
        )

    def resolve_fx_identifier(self, available_fx: Sequence[Mapping[str, Any]]) -> None:
        del available_fx
        return None

    def build_preset_apply_args(
        self,
        plan: VocalTuningPresetPlan,
        approval_hash: str,
    ) -> None:
        del plan, approval_hash
        return None

    def parameter_targets(
        self, settings: X42AutoTuneSettings
    ) -> list[VocalTuningParameterState] | None:
        del settings
        return None

    def build_plugin_apply_args(
        self,
        plan: VocalTuningPluginPlan,
        approval_hash: str,
    ) -> None:
        del plan, approval_hash
        return None


class ReaTuneProvider:
    """Recall verified engineer-authored ReaTune presets without opaque state edits."""

    provider_id: VocalTuningProviderId = "reatune"

    def capability(
        self, available_fx: Sequence[Mapping[str, Any]]
    ) -> VocalTuningProviderCapability:
        installed = self.resolve_fx_identifier(available_fx) is not None
        reason = (
            "ReaTune is installed. MCP can insert it first in the chain and recall "
            "an engineer-authored named preset, but cannot edit or inspect the "
            "preset's hidden key, scale, attack, or manual-correction state."
            if installed
            else "ReaTune was not found in REAPER's installed FX list."
        )
        return VocalTuningProviderCapability(
            provider_id=self.provider_id,
            display_name="ReaTune",
            installed=installed,
            control_mode="plugin_preset" if installed else "plugin_ui_only",
            supports_analysis=False,
            supports_preview=installed,
            supports_apply=installed,
            supported_modes=(
                ["transparent_repair", "creative_effect"] if installed else []
            ),
            reason=reason,
        )

    def build_apply_args(
        self,
        plan: VocalTuningPlan,
        approval_hash: str,
    ) -> None:
        del plan, approval_hash
        return None

    def resolve_fx_identifier(
        self, available_fx: Sequence[Mapping[str, Any]]
    ) -> str | None:
        for fx in available_fx:
            if (
                "reatune"
                in f"{fx.get('name', '')} {fx.get('identifier', '')}".casefold()
            ):
                identifier = fx.get("identifier")
                if isinstance(identifier, str) and identifier:
                    return identifier
                name = fx.get("name")
                if isinstance(name, str) and name:
                    return name
        return None

    def build_preset_apply_args(
        self,
        plan: VocalTuningPresetPlan,
        approval_hash: str,
    ) -> tuple[str, dict[str, Any]]:
        return (
            "apply_vocal_tuning_preset_plan",
            {
                "approval_hash": approval_hash,
                "provider_id": self.provider_id,
                "context": plan.context.model_dump(mode="json"),
                "preset_name": plan.preset_name,
            },
        )

    def parameter_targets(
        self, settings: X42AutoTuneSettings
    ) -> list[VocalTuningParameterState] | None:
        del settings
        return None

    def build_plugin_apply_args(
        self,
        plan: VocalTuningPluginPlan,
        approval_hash: str,
    ) -> None:
        del plan, approval_hash
        return None


class X42AutoTuneProvider:
    """Control x42 Auto Tune through its documented LV2 parameter ports."""

    provider_id: VocalTuningProviderId = "x42_autotune"
    plugin_uri = "http://gareus.org/oss/lv2/fat1"
    _scale_intervals = {
        "major": (0, 2, 4, 5, 7, 9, 11),
        "natural_minor": (0, 2, 3, 5, 7, 8, 10),
        "chromatic": tuple(range(12)),
    }

    def capability(
        self, available_fx: Sequence[Mapping[str, Any]]
    ) -> VocalTuningProviderCapability:
        installed = self.resolve_fx_identifier(available_fx) is not None
        return VocalTuningProviderCapability(
            provider_id=self.provider_id,
            display_name="x42 Auto Tune",
            installed=installed,
            control_mode="plugin_parameters" if installed else "plugin_ui_only",
            supports_analysis=False,
            supports_preview=installed,
            supports_apply=installed,
            supported_modes=(
                ["transparent_repair", "creative_effect"] if installed else []
            ),
            reason=(
                "Uses the official LV2 controls for scale notes, correction, "
                "smoothing, bias, tuning, wet state, and bypass."
                if installed
                else "x42 Auto Tune was not found in REAPER's installed FX list."
            ),
        )

    def build_apply_args(
        self,
        plan: VocalTuningPlan,
        approval_hash: str,
    ) -> None:
        del plan, approval_hash
        return None

    def resolve_fx_identifier(
        self, available_fx: Sequence[Mapping[str, Any]]
    ) -> str | None:
        for fx in available_fx:
            if fx.get("identifier") == self.plugin_uri:
                return self.plugin_uri
        return None

    def build_preset_apply_args(
        self,
        plan: VocalTuningPresetPlan,
        approval_hash: str,
    ) -> None:
        del plan, approval_hash
        return None

    def parameter_targets(
        self, settings: X42AutoTuneSettings
    ) -> list[VocalTuningParameterState]:
        enabled_notes = {
            (settings.root_pitch_class + interval) % 12
            for interval in self._scale_intervals[settings.scale]
        }
        targets = [
            VocalTuningParameterState(index=0, name="Mode", normalized_value=0.0),
            VocalTuningParameterState(
                index=1,
                name="Filter Channel",
                normalized_value=0.0,
            ),
            VocalTuningParameterState(
                index=2,
                name="Tuning",
                normalized_value=(settings.tuning_hz - 400.0) / 80.0,
            ),
            VocalTuningParameterState(
                index=3,
                name="Bias",
                normalized_value=settings.bias,
            ),
            VocalTuningParameterState(
                index=4,
                name="Filter",
                normalized_value=(settings.smoothing_seconds - 0.02) / 0.48,
            ),
            VocalTuningParameterState(
                index=5,
                name="Correction",
                normalized_value=settings.correction_amount,
            ),
            VocalTuningParameterState(
                index=6,
                name="Offset",
                normalized_value=0.5,
            ),
            VocalTuningParameterState(
                index=7,
                name="Pitch Bend Range",
                normalized_value=2.0 / 7.0,
            ),
            VocalTuningParameterState(
                index=8,
                name="Fast Correction",
                normalized_value=1.0 if settings.fast_correction else 0.0,
            ),
        ]
        note_names = (
            "C",
            "C#",
            "D",
            "D#",
            "E",
            "F",
            "F#",
            "G",
            "G#",
            "A",
            "A#",
            "B",
        )
        targets.extend(
            VocalTuningParameterState(
                index=9 + pitch_class,
                name=note_name,
                normalized_value=1.0 if pitch_class in enabled_notes else 0.0,
            )
            for pitch_class, note_name in enumerate(note_names)
        )
        targets.extend(
            (
                VocalTuningParameterState(
                    index=25,
                    name="Bypass",
                    normalized_value=0.0,
                ),
                VocalTuningParameterState(
                    index=26,
                    name="Wet",
                    normalized_value=settings.wet,
                ),
                VocalTuningParameterState(
                    index=27,
                    name="Delta",
                    normalized_value=0.0,
                ),
            )
        )
        return targets

    def build_plugin_apply_args(
        self,
        plan: VocalTuningPluginPlan,
        approval_hash: str,
    ) -> tuple[str, dict[str, Any]]:
        return (
            "apply_vocal_tuning_plugin_plan",
            {
                "approval_hash": approval_hash,
                "provider_id": self.provider_id,
                "context": plan.context.model_dump(mode="json"),
                "target_parameters": [
                    parameter.model_dump(mode="json")
                    for parameter in plan.target_parameters
                ],
            },
        )


class VocalTuningProviderRegistry:
    """Resolve tuning providers without leaking provider logic into MCP tools."""

    def __init__(
        self,
        providers: Sequence[VocalTuningProvider] | None = None,
    ) -> None:
        resolved = providers or (
            ReaperTakePitchProvider(),
            ReaTuneProvider(),
            X42AutoTuneProvider(),
        )
        self._providers = {provider.provider_id: provider for provider in resolved}

    def get(self, provider_id: VocalTuningProviderId) -> VocalTuningProvider:
        """Return one known provider."""

        return self._providers[provider_id]

    def capabilities(
        self, available_fx: Sequence[Mapping[str, Any]]
    ) -> list[VocalTuningProviderCapability]:
        """Return capabilities in stable provider-ID order."""

        return [
            self._providers[provider_id].capability(available_fx)
            for provider_id in sorted(self._providers)
        ]
