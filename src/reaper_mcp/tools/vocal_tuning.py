"""MCP tool registration for guarded vocal pitch correction."""

from typing import Annotated, Any, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from reaper_mcp.models.vocal_tuning import (
    PitchCorrectionSegment,
    VocalTuningMode,
    VocalTuningPlan,
    VocalTuningPluginPlan,
    VocalTuningPresetPlan,
    VocalTuningProviderId,
    X42AutoTuneSettings,
)
from reaper_mcp.services.vocal_tuning_service import VocalTuningService


def register_vocal_tuning_tools(
    server: FastMCP,
    service: VocalTuningService,
) -> None:
    """Register provider discovery and approval-bound tuning tools."""

    @server.tool(
        name="list_vocal_tuning_providers",
        description=(
            "List detected vocal-tuning providers and only the controls verified "
            "safe for MCP use. Does not mutate REAPER."
        ),
    )
    async def list_vocal_tuning_providers() -> dict[str, Any]:
        return await service.list_providers()

    @server.tool(
        name="preview_vocal_tuning_plan",
        description=(
            "Validate explicit, absolute-time note corrections against one current "
            "single-take vocal item. Returns an approval hash and does not analyze "
            "pitch or mutate REAPER."
        ),
    )
    async def preview_vocal_tuning_plan(
        provider_id: VocalTuningProviderId,
        mode: VocalTuningMode,
        track_guid: str,
        item_guid: str,
        take_guid: str,
        corrections: list[PitchCorrectionSegment],
    ) -> dict[str, Any]:
        return await service.preview_plan(
            provider_id,
            mode,
            track_guid,
            item_guid,
            take_guid,
            [correction.model_dump(mode="json") for correction in corrections],
        )

    @server.tool(
        name="apply_vocal_tuning_plan",
        description=(
            "Revalidate and apply the exact approved vocal-tuning plan in one "
            "named undo transaction. The current provider splits note segments "
            "and applies static take-pitch offsets without detecting notes."
        ),
    )
    async def apply_vocal_tuning_plan(
        plan: VocalTuningPlan,
        approval_hash: str,
    ) -> dict[str, Any]:
        return await service.apply_plan(
            plan.model_dump(mode="json"),
            approval_hash,
        )

    @server.tool(
        name="preview_vocal_tuning_preset_plan",
        description=(
            "Preview insertion and named-preset recall for a verified tuning "
            "plugin provider. ReaTune presets must already be authored for the "
            "song. The tuner is required at FX index 0. Does not mutate REAPER."
        ),
    )
    async def preview_vocal_tuning_preset_plan(
        provider_id: VocalTuningProviderId,
        mode: VocalTuningMode,
        track_guid: str,
        preset_name: Annotated[str, Field(min_length=1, max_length=200)],
        insert_index: Literal[0] = 0,
    ) -> dict[str, Any]:
        return await service.preview_preset_plan(
            provider_id,
            mode,
            track_guid,
            preset_name,
            insert_index,
        )

    @server.tool(
        name="apply_vocal_tuning_preset_plan",
        description=(
            "Revalidate and apply an approved tuning-plugin preset plan in one "
            "named undo transaction. For ReaTune, inserts it first in the chain "
            "when absent, recalls the exact named preset, and verifies the recalled "
            "name without editing opaque plugin state."
        ),
    )
    async def apply_vocal_tuning_preset_plan(
        plan: VocalTuningPresetPlan,
        approval_hash: str,
    ) -> dict[str, Any]:
        return await service.apply_preset_plan(
            plan.model_dump(mode="json"),
            approval_hash,
        )

    @server.tool(
        name="preview_vocal_tuning_plugin_plan",
        description=(
            "Preview direct, verified parameter control of an installed tuning "
            "plugin. For x42 Auto Tune, binds the approved root, scale, correction, "
            "smoothing, bias, tuning, fast mode, and wet state to the current track "
            "and plug-in state. Requires FX index 0 and does not mutate REAPER."
        ),
    )
    async def preview_vocal_tuning_plugin_plan(
        provider_id: VocalTuningProviderId,
        mode: VocalTuningMode,
        track_guid: str,
        settings: X42AutoTuneSettings,
        insert_index: Literal[0] = 0,
    ) -> dict[str, Any]:
        return await service.preview_plugin_plan(
            provider_id,
            mode,
            track_guid,
            settings.model_dump(mode="json"),
            insert_index,
        )

    @server.tool(
        name="apply_vocal_tuning_plugin_plan",
        description=(
            "Revalidate and apply an approved tuning-plugin parameter plan in one "
            "named undo transaction. Inserts the verified plug-in first when absent, "
            "checks every controlled parameter by index and name, verifies resulting "
            "values, and rolls back the complete change if verification fails."
        ),
    )
    async def apply_vocal_tuning_plugin_plan(
        plan: VocalTuningPluginPlan,
        approval_hash: str,
    ) -> dict[str, Any]:
        return await service.apply_plugin_plan(
            plan.model_dump(mode="json"),
            approval_hash,
        )
