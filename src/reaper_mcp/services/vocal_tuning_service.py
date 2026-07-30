"""Preview and apply explicit vocal pitch corrections against current REAPER state."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import ValidationError

from reaper_mcp.bridge.base import BridgeClient
from reaper_mcp.errors import ErrorCode
from reaper_mcp.models.bridge import CommandOptions, ErrorResponse
from reaper_mcp.models.vocal_tuning import (
    PreviewVocalTuningPlanRequest,
    PreviewVocalTuningPluginPlanRequest,
    PreviewVocalTuningPresetPlanRequest,
    VocalTuningContext,
    VocalTuningMode,
    VocalTuningParameterState,
    VocalTuningPlan,
    VocalTuningPlanApplication,
    VocalTuningPluginContext,
    VocalTuningPluginPlan,
    VocalTuningPluginPlanApplication,
    VocalTuningPresetContext,
    VocalTuningPresetPlan,
    VocalTuningPresetPlanApplication,
    VocalTuningProviderId,
)
from reaper_mcp.services._bridge_result import (
    bridge_error,
    invalid_payload,
    validation_error,
)
from reaper_mcp.services.fx_service import FxService
from reaper_mcp.services.media_service import MediaService
from reaper_mcp.services.project_service import ProjectService
from reaper_mcp.services.take_service import TakeService
from reaper_mcp.services.vocal_tuning_provider import VocalTuningProviderRegistry


class VocalTuningService:
    """Own provider discovery, approval hashes, and guarded tuning mutation."""

    def __init__(
        self,
        bridge_client: BridgeClient,
        project_service: ProjectService,
        media_service: MediaService,
        take_service: TakeService,
        fx_service: FxService,
        provider_registry: VocalTuningProviderRegistry | None = None,
    ) -> None:
        self.bridge_client = bridge_client
        self.project_service = project_service
        self.media_service = media_service
        self.take_service = take_service
        self.fx_service = fx_service
        self.provider_registry = provider_registry or VocalTuningProviderRegistry()

    async def list_providers(self) -> dict[str, Any]:
        """Return installed state and verified controls for tuning providers."""

        available_fx = await self.fx_service.list_available_fx()
        if not available_fx["ok"]:
            return available_fx
        providers = self.provider_registry.capabilities(available_fx["fx"])
        return {
            "ok": True,
            "providers": [provider.model_dump(mode="json") for provider in providers],
            "provider_count": len(providers),
            "warnings": available_fx["warnings"],
        }

    async def preview_plan(
        self,
        provider_id: VocalTuningProviderId,
        mode: VocalTuningMode,
        track_guid: str,
        item_guid: str,
        take_guid: str,
        corrections: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Return a non-mutating correction plan bound to current REAPER state."""

        try:
            request = PreviewVocalTuningPlanRequest(
                provider_id=provider_id,
                mode=mode,
                track_guid=track_guid,
                item_guid=item_guid,
                take_guid=take_guid,
                corrections=corrections,
            )
        except ValidationError as exc:
            return self._validation_error(exc)

        provider = self.provider_registry.get(request.provider_id)
        available_fx: list[dict[str, Any]] = []
        if request.provider_id != "reaper_take_pitch":
            fx_result = await self.fx_service.list_available_fx()
            if not fx_result["ok"]:
                return fx_result
            available_fx = fx_result["fx"]
        capability = provider.capability(available_fx)
        if (
            capability.control_mode != "segment_pitch"
            or not capability.supports_preview
            or request.mode not in capability.supported_modes
        ):
            return self._provider_unavailable(capability.model_dump(mode="json"))

        context_result = await self._current_context(request)
        if not context_result["ok"]:
            return context_result
        context = VocalTuningContext.model_validate(context_result["context"])
        range_error = self._validate_corrections_in_context(request, context)
        if range_error is not None:
            return range_error

        context_hash = self._canonical_sha256(context.model_dump(mode="json"))
        warnings = [
            "No pitch analysis was performed. Corrections are explicit engineer "
            "observations supplied to this plan.",
            "The current provider applies static offsets to split note segments; "
            "listen for note-boundary artifacts before accepting the result.",
        ]
        plan_payload = {
            "provider_id": request.provider_id,
            "mode": request.mode,
            "context": context.model_dump(mode="json"),
            "context_sha256": context_hash,
            "corrections": [
                correction.model_dump(mode="json") for correction in request.corrections
            ],
            "warnings": warnings,
        }
        approval_hash = self._canonical_sha256(plan_payload)
        plan = VocalTuningPlan(
            plan_id=f"vtp_{approval_hash[:24]}",
            approval_hash=approval_hash,
            **plan_payload,
        )
        return {
            "ok": True,
            "plan": plan.model_dump(mode="json"),
            "warnings": warnings,
        }

    async def apply_plan(
        self,
        plan: dict[str, Any],
        approval_hash: str,
    ) -> dict[str, Any]:
        """Revalidate and apply one exact plan in one named undo transaction."""

        try:
            accepted_plan = VocalTuningPlan.model_validate(plan)
        except ValidationError as exc:
            return self._validation_error(exc)
        if approval_hash != accepted_plan.approval_hash:
            return self._stale(
                "The supplied approval hash does not match the tuning plan.",
                {
                    "expected_approval_hash": accepted_plan.approval_hash,
                    "actual_approval_hash": approval_hash,
                },
            )

        refreshed = await self.preview_plan(
            accepted_plan.provider_id,
            accepted_plan.mode,
            accepted_plan.context.track_guid,
            accepted_plan.context.item_guid,
            accepted_plan.context.take_guid,
            [
                correction.model_dump(mode="json")
                for correction in accepted_plan.corrections
            ],
        )
        if not refreshed["ok"]:
            return refreshed
        current_hash = refreshed["plan"]["approval_hash"]
        if current_hash != accepted_plan.approval_hash:
            return self._stale(
                "The project, item, take, or corrections changed after preview.",
                {
                    "expected_approval_hash": accepted_plan.approval_hash,
                    "current_approval_hash": current_hash,
                },
            )

        provider = self.provider_registry.get(accepted_plan.provider_id)
        command = provider.build_apply_args(accepted_plan, approval_hash)
        if command is None:
            capability = provider.capability(())
            return self._provider_unavailable(capability.model_dump(mode="json"))
        command_name, args = command
        response = await self.bridge_client.execute(
            command_name,
            args=args,
            options=CommandOptions(
                mutates_project=True,
                undo_label="Apply approved vocal tuning plan",
            ),
        )
        if not response.ok:
            return bridge_error(response)
        try:
            application = VocalTuningPlanApplication.model_validate(
                response.result or {}
            )
        except ValidationError as exc:
            return invalid_payload(response, exc, "vocal tuning plan application")
        return {
            "ok": True,
            "application": application.model_dump(mode="json"),
            "warnings": response.warnings,
        }

    async def preview_preset_plan(
        self,
        provider_id: VocalTuningProviderId,
        mode: VocalTuningMode,
        track_guid: str,
        preset_name: str,
        insert_index: int = 0,
    ) -> dict[str, Any]:
        """Preview a guarded recall of an engineer-authored tuning preset."""

        try:
            request = PreviewVocalTuningPresetPlanRequest(
                provider_id=provider_id,
                mode=mode,
                track_guid=track_guid,
                preset_name=preset_name,
                insert_index=insert_index,
            )
        except ValidationError as exc:
            return self._validation_error(exc)

        fx_result = await self.fx_service.list_available_fx()
        if not fx_result["ok"]:
            return fx_result
        provider = self.provider_registry.get(request.provider_id)
        capability = provider.capability(fx_result["fx"])
        if (
            capability.control_mode != "plugin_preset"
            or not capability.supports_preview
            or request.mode not in capability.supported_modes
        ):
            return self._provider_unavailable(capability.model_dump(mode="json"))

        installed_identifier = provider.resolve_fx_identifier(fx_result["fx"])
        if installed_identifier is None:
            return self._provider_unavailable(capability.model_dump(mode="json"))
        context_result = await self._current_preset_context(
            request,
            installed_identifier,
        )
        if not context_result["ok"]:
            return context_result
        context = VocalTuningPresetContext.model_validate(context_result["context"])

        context_hash = self._canonical_sha256(context.model_dump(mode="json"))
        warnings = [
            "This plan recalls an engineer-authored ReaTune preset. It cannot "
            "inspect the preset's hidden key, scale, attack, algorithm, or manual "
            "correction data.",
            "REAPER can verify the recalled preset name, not its artistic result. "
            "Confirm the preset was authored for this song and approve it by "
            "listening in context.",
        ]
        plan_payload = {
            "provider_id": request.provider_id,
            "mode": request.mode,
            "context": context.model_dump(mode="json"),
            "context_sha256": context_hash,
            "preset_name": request.preset_name,
            "warnings": warnings,
        }
        approval_hash = self._canonical_sha256(plan_payload)
        plan = VocalTuningPresetPlan(
            plan_id=f"vtp_{approval_hash[:24]}",
            approval_hash=approval_hash,
            **plan_payload,
        )
        return {
            "ok": True,
            "plan": plan.model_dump(mode="json"),
            "warnings": [
                *fx_result["warnings"],
                *context_result["warnings"],
                *warnings,
            ],
        }

    async def apply_preset_plan(
        self,
        plan: dict[str, Any],
        approval_hash: str,
    ) -> dict[str, Any]:
        """Revalidate and recall one exact preset in one undo transaction."""

        try:
            accepted_plan = VocalTuningPresetPlan.model_validate(plan)
        except ValidationError as exc:
            return self._validation_error(exc)
        if approval_hash != accepted_plan.approval_hash:
            return self._stale(
                "The supplied approval hash does not match the tuning preset plan.",
                {
                    "expected_approval_hash": accepted_plan.approval_hash,
                    "actual_approval_hash": approval_hash,
                },
            )

        refreshed = await self.preview_preset_plan(
            accepted_plan.provider_id,
            accepted_plan.mode,
            accepted_plan.context.track_guid,
            accepted_plan.preset_name,
            accepted_plan.context.insert_index,
        )
        if not refreshed["ok"]:
            return refreshed
        current_hash = refreshed["plan"]["approval_hash"]
        if current_hash != accepted_plan.approval_hash:
            return self._stale(
                "The project, track, ReaTune instance, or current preset changed "
                "after preview.",
                {
                    "expected_approval_hash": accepted_plan.approval_hash,
                    "current_approval_hash": current_hash,
                },
            )

        provider = self.provider_registry.get(accepted_plan.provider_id)
        command = provider.build_preset_apply_args(accepted_plan, approval_hash)
        if command is None:
            capability = provider.capability(())
            return self._provider_unavailable(capability.model_dump(mode="json"))
        command_name, args = command
        response = await self.bridge_client.execute(
            command_name,
            args=args,
            options=CommandOptions(
                mutates_project=True,
                undo_label=f"Apply ReaTune preset: {accepted_plan.preset_name}",
            ),
        )
        if not response.ok:
            return bridge_error(response)
        try:
            application = VocalTuningPresetPlanApplication.model_validate(
                response.result or {}
            )
        except ValidationError as exc:
            return invalid_payload(
                response,
                exc,
                "vocal tuning preset plan application",
            )
        return {
            "ok": True,
            "application": application.model_dump(mode="json"),
            "warnings": [
                *response.warnings,
                *accepted_plan.warnings,
            ],
        }

    async def preview_plugin_plan(
        self,
        provider_id: VocalTuningProviderId,
        mode: VocalTuningMode,
        track_guid: str,
        settings: dict[str, Any],
        insert_index: int = 0,
    ) -> dict[str, Any]:
        """Preview one parameter-controlled vocal-tuning plugin plan."""

        try:
            request = PreviewVocalTuningPluginPlanRequest(
                provider_id=provider_id,
                mode=mode,
                track_guid=track_guid,
                settings=settings,
                insert_index=insert_index,
            )
        except ValidationError as exc:
            return self._validation_error(exc)

        fx_result = await self.fx_service.list_available_fx()
        if not fx_result["ok"]:
            return fx_result
        provider = self.provider_registry.get(request.provider_id)
        capability = provider.capability(fx_result["fx"])
        if (
            capability.control_mode != "plugin_parameters"
            or not capability.supports_preview
            or request.mode not in capability.supported_modes
        ):
            return self._provider_unavailable(capability.model_dump(mode="json"))

        installed_identifier = provider.resolve_fx_identifier(fx_result["fx"])
        targets = provider.parameter_targets(request.settings)
        if installed_identifier is None or targets is None:
            return self._provider_unavailable(capability.model_dump(mode="json"))
        context_result = await self._current_plugin_context(
            request,
            installed_identifier,
            targets,
        )
        if not context_result["ok"]:
            return context_result
        context = VocalTuningPluginContext.model_validate(context_result["context"])

        context_hash = self._canonical_sha256(context.model_dump(mode="json"))
        warnings = [
            "x42 Auto Tune does not analyze the song key. This plan uses the "
            "caller-approved root and scale.",
            "x42 Auto Tune does not provide formant correction and is intended for "
            "pitch correction rather than large transposition. Approve the result "
            "by listening for artifacts and lost expression.",
        ]
        plan_payload = {
            "provider_id": request.provider_id,
            "mode": request.mode,
            "context": context.model_dump(mode="json"),
            "context_sha256": context_hash,
            "settings": request.settings.model_dump(mode="json"),
            "target_parameters": [target.model_dump(mode="json") for target in targets],
            "warnings": warnings,
        }
        approval_hash = self._canonical_sha256(plan_payload)
        plan = VocalTuningPluginPlan(
            plan_id=f"vtp_{approval_hash[:24]}",
            approval_hash=approval_hash,
            **plan_payload,
        )
        return {
            "ok": True,
            "plan": plan.model_dump(mode="json"),
            "warnings": [
                *fx_result["warnings"],
                *context_result["warnings"],
                *warnings,
            ],
        }

    async def apply_plugin_plan(
        self,
        plan: dict[str, Any],
        approval_hash: str,
    ) -> dict[str, Any]:
        """Revalidate and apply one plugin plan in one undo transaction."""

        try:
            accepted_plan = VocalTuningPluginPlan.model_validate(plan)
        except ValidationError as exc:
            return self._validation_error(exc)
        if approval_hash != accepted_plan.approval_hash:
            return self._stale(
                "The supplied approval hash does not match the tuning plugin plan.",
                {
                    "expected_approval_hash": accepted_plan.approval_hash,
                    "actual_approval_hash": approval_hash,
                },
            )

        refreshed = await self.preview_plugin_plan(
            accepted_plan.provider_id,
            accepted_plan.mode,
            accepted_plan.context.track_guid,
            accepted_plan.settings.model_dump(mode="json"),
            accepted_plan.context.insert_index,
        )
        if not refreshed["ok"]:
            return refreshed
        current_hash = refreshed["plan"]["approval_hash"]
        if current_hash != accepted_plan.approval_hash:
            return self._stale(
                "The project, track, tuning plugin, or parameter state changed "
                "after preview.",
                {
                    "expected_approval_hash": accepted_plan.approval_hash,
                    "current_approval_hash": current_hash,
                },
            )

        provider = self.provider_registry.get(accepted_plan.provider_id)
        command = provider.build_plugin_apply_args(accepted_plan, approval_hash)
        if command is None:
            capability = provider.capability(())
            return self._provider_unavailable(capability.model_dump(mode="json"))
        command_name, args = command
        response = await self.bridge_client.execute(
            command_name,
            args=args,
            options=CommandOptions(
                mutates_project=True,
                undo_label=f"Apply {accepted_plan.provider_id} vocal tuning",
            ),
        )
        if not response.ok:
            return bridge_error(response)
        try:
            application = VocalTuningPluginPlanApplication.model_validate(
                response.result or {}
            )
        except ValidationError as exc:
            return invalid_payload(
                response,
                exc,
                "vocal tuning plugin plan application",
            )
        return {
            "ok": True,
            "application": application.model_dump(mode="json"),
            "warnings": [
                *response.warnings,
                *accepted_plan.warnings,
            ],
        }

    async def _current_context(
        self, request: PreviewVocalTuningPlanRequest
    ) -> dict[str, Any]:
        project = await self.project_service.get_project_snapshot()
        if not project["ok"]:
            return project
        media = await self.media_service.list_media_items()
        if not media["ok"]:
            return media
        item = next(
            (
                candidate
                for candidate in media["items"]
                if candidate["guid"] == request.item_guid
            ),
            None,
        )
        if item is None:
            return self._stale(
                "The target media item is no longer present.",
                {"item_guid": request.item_guid},
            )
        if item["track_guid"] != request.track_guid:
            return self._stale(
                "The target media item moved to another track.",
                {
                    "expected_track_guid": request.track_guid,
                    "actual_track_guid": item["track_guid"],
                },
            )

        takes = await self.take_service.list_item_takes(request.item_guid)
        if not takes["ok"]:
            return takes
        take = next(
            (
                candidate
                for candidate in takes["takes"]
                if candidate["guid"] == request.take_guid
            ),
            None,
        )
        if take is None:
            return self._stale(
                "The target take is no longer present on the item.",
                {"take_guid": request.take_guid},
            )
        if takes["take_count"] != 1:
            return self._error(
                ErrorCode.INVALID_VOCAL_TUNING_REQUEST,
                "Segment tuning currently requires a single-take media item.",
                {"take_count": takes["take_count"]},
                "Comp or duplicate the approved take into a single-take item first.",
            )
        if not take["is_active"]:
            return self._error(
                ErrorCode.INVALID_VOCAL_TUNING_REQUEST,
                "The tuning target must be the active take.",
                {"take_guid": request.take_guid},
                "Set the approved take active, then preview the plan again.",
            )
        if take["is_midi"]:
            return self._error(
                ErrorCode.INVALID_VOCAL_TUNING_REQUEST,
                "Vocal tuning requires an audio take.",
                {"take_guid": request.take_guid},
                "Choose a non-MIDI vocal take.",
            )

        metadata = project["snapshot"]["project"]
        return {
            "ok": True,
            "context": VocalTuningContext(
                project_path=metadata["path"],
                project_name=metadata["name"],
                state_change_count=metadata["state_change_count"],
                track_guid=request.track_guid,
                item_guid=request.item_guid,
                item_name=item["name"],
                item_position_seconds=item["position_seconds"],
                item_length_seconds=item["length_seconds"],
                take_guid=request.take_guid,
                take_name=take["name"],
                take_count=takes["take_count"],
                take_pitch_semitones=take["pitch_semitones"],
            ).model_dump(mode="json"),
            "warnings": [
                *project["warnings"],
                *media["warnings"],
                *takes["warnings"],
            ],
        }

    async def _current_preset_context(
        self,
        request: PreviewVocalTuningPresetPlanRequest,
        installed_identifier: str,
    ) -> dict[str, Any]:
        project = await self.project_service.get_project_snapshot()
        if not project["ok"]:
            return project
        track = next(
            (
                candidate
                for candidate in project["snapshot"]["tracks"]
                if candidate["guid"] == request.track_guid
            ),
            None,
        )
        if track is None:
            return self._stale(
                "The target track is no longer present.",
                {"track_guid": request.track_guid},
            )

        track_fx = await self.fx_service.list_track_fx(request.track_guid)
        if not track_fx["ok"]:
            return track_fx
        reatune_fx = [
            fx
            for fx in track_fx["fx"]
            if "reatune"
            in f"{fx.get('name', '')} {fx.get('identifier', '')}".casefold()
        ]
        if len(reatune_fx) > 1:
            return self._error(
                ErrorCode.INVALID_VOCAL_TUNING_REQUEST,
                "The target track has more than one ReaTune instance.",
                {
                    "track_guid": request.track_guid,
                    "reatune_fx_count": len(reatune_fx),
                },
                "Keep one intended ReaTune instance on the track, then preview again.",
            )

        existing_fx_identity = None
        existing_preset_name = None
        if reatune_fx:
            existing_fx = reatune_fx[0]
            if existing_fx["index"] != request.insert_index:
                return self._error(
                    ErrorCode.INVALID_VOCAL_TUNING_REQUEST,
                    "The existing ReaTune instance is not first in the FX chain.",
                    {
                        "track_guid": request.track_guid,
                        "actual_index": existing_fx["index"],
                        "required_index": request.insert_index,
                    },
                    "Move the intended ReaTune instance to FX index 0, then preview "
                    "again.",
                )
            existing_fx_identity = existing_fx["fx_identity"]
            preset_result = await self.fx_service.get_fx_preset(existing_fx_identity)
            if not preset_result["ok"]:
                return preset_result
            existing_preset_name = preset_result["preset_name"]
            if not existing_preset_name:
                return self._error(
                    ErrorCode.INVALID_VOCAL_TUNING_REQUEST,
                    "The existing ReaTune state is not saved as a named preset.",
                    {"track_guid": request.track_guid},
                    "Save the current ReaTune settings as a named FX preset so a "
                    "failed recall can restore the previous state exactly.",
                )

        metadata = project["snapshot"]["project"]
        return {
            "ok": True,
            "context": VocalTuningPresetContext(
                project_path=metadata["path"],
                project_name=metadata["name"],
                state_change_count=metadata["state_change_count"],
                track_guid=request.track_guid,
                track_name=track["name"],
                installed_fx_identifier=installed_identifier,
                insert_index=request.insert_index,
                existing_fx_identity=existing_fx_identity,
                existing_preset_name=existing_preset_name,
            ).model_dump(mode="json"),
            "warnings": [
                *project["warnings"],
                *track_fx["warnings"],
            ],
        }

    async def _current_plugin_context(
        self,
        request: PreviewVocalTuningPluginPlanRequest,
        installed_identifier: str,
        targets: list[VocalTuningParameterState],
    ) -> dict[str, Any]:
        project = await self.project_service.get_project_snapshot()
        if not project["ok"]:
            return project
        track = next(
            (
                candidate
                for candidate in project["snapshot"]["tracks"]
                if candidate["guid"] == request.track_guid
            ),
            None,
        )
        if track is None:
            return self._stale(
                "The target track is no longer present.",
                {"track_guid": request.track_guid},
            )

        track_fx = await self.fx_service.list_track_fx(request.track_guid)
        if not track_fx["ok"]:
            return track_fx
        matches = [
            fx for fx in track_fx["fx"] if fx.get("identifier") == installed_identifier
        ]
        if len(matches) > 1:
            return self._error(
                ErrorCode.INVALID_VOCAL_TUNING_REQUEST,
                "The target track has more than one matching tuning-plugin instance.",
                {
                    "track_guid": request.track_guid,
                    "matching_fx_count": len(matches),
                },
                "Keep one intended tuning-plugin instance, then preview again.",
            )

        existing_fx_identity = None
        existing_fx_enabled = None
        current_parameters: list[VocalTuningParameterState] = []
        parameter_warnings: list[str] = []
        if matches:
            existing_fx = matches[0]
            if existing_fx["index"] != request.insert_index:
                return self._error(
                    ErrorCode.INVALID_VOCAL_TUNING_REQUEST,
                    "The existing tuning plugin is not first in the FX chain.",
                    {
                        "track_guid": request.track_guid,
                        "actual_index": existing_fx["index"],
                        "required_index": request.insert_index,
                    },
                    "Move the intended tuning plugin to FX index 0, then preview "
                    "again.",
                )
            existing_fx_identity = existing_fx["fx_identity"]
            existing_fx_enabled = existing_fx["enabled"]
            parameters_result = await self.fx_service.get_fx_parameters(
                existing_fx_identity
            )
            if not parameters_result["ok"]:
                return parameters_result
            by_index = {
                parameter["index"]: parameter
                for parameter in parameters_result["parameters"]
            }
            for target in targets:
                current = by_index.get(target.index)
                if current is None or current["name"] != target.name:
                    return self._error(
                        ErrorCode.VOCAL_TUNING_PROVIDER_UNAVAILABLE,
                        "The installed tuning plugin parameter contract changed.",
                        {
                            "parameter_index": target.index,
                            "expected_name": target.name,
                            "actual_name": current["name"] if current else None,
                        },
                        "Disable this provider until its parameter adapter is "
                        "reverified.",
                    )
                current_parameters.append(
                    VocalTuningParameterState(
                        index=current["index"],
                        name=current["name"],
                        normalized_value=current["normalized_value"],
                    )
                )
            parameter_warnings = parameters_result["warnings"]

        metadata = project["snapshot"]["project"]
        return {
            "ok": True,
            "context": VocalTuningPluginContext(
                project_path=metadata["path"],
                project_name=metadata["name"],
                state_change_count=metadata["state_change_count"],
                track_guid=request.track_guid,
                track_name=track["name"],
                installed_fx_identifier=installed_identifier,
                insert_index=request.insert_index,
                existing_fx_identity=existing_fx_identity,
                existing_fx_enabled=existing_fx_enabled,
                current_parameters=current_parameters,
            ).model_dump(mode="json"),
            "warnings": [
                *project["warnings"],
                *track_fx["warnings"],
                *parameter_warnings,
            ],
        }

    def _validate_corrections_in_context(
        self,
        request: PreviewVocalTuningPlanRequest,
        context: VocalTuningContext,
    ) -> dict[str, Any] | None:
        item_start = context.item_position_seconds
        item_end = item_start + context.item_length_seconds
        for correction in request.corrections:
            if (
                correction.start_seconds < item_start
                or correction.end_seconds > item_end
            ):
                return self._error(
                    ErrorCode.INVALID_VOCAL_TUNING_REQUEST,
                    "A correction falls outside the target media item.",
                    {
                        "segment_id": correction.segment_id,
                        "item_start_seconds": item_start,
                        "item_end_seconds": item_end,
                    },
                    "Keep every correction inside the current item boundaries.",
                )
            result_pitch = (
                context.take_pitch_semitones + correction.correction_cents / 100.0
            )
            if result_pitch < -80.0 or result_pitch > 80.0:
                return self._error(
                    ErrorCode.INVALID_VOCAL_TUNING_REQUEST,
                    "A correction exceeds REAPER's supported take-pitch range.",
                    {
                        "segment_id": correction.segment_id,
                        "result_pitch_semitones": result_pitch,
                    },
                    "Reduce the correction or reset the take's base pitch first.",
                )
            if not correction.preserve_vibrato:
                return self._error(
                    ErrorCode.INVALID_VOCAL_TUNING_REQUEST,
                    "The selected provider only supports vibrato-preserving offsets.",
                    {"segment_id": correction.segment_id},
                    "Set preserve_vibrato=true or choose a future elastic provider.",
                )
        return None

    @staticmethod
    def _canonical_sha256(value: Any) -> str:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _validation_error(exc: ValidationError) -> dict[str, Any]:
        return validation_error(
            exc,
            ErrorCode.INVALID_VOCAL_TUNING_REQUEST,
            "The vocal tuning request is invalid.",
            "Use a supported provider and chronological, non-overlapping segments.",
        )

    @classmethod
    def _provider_unavailable(cls, capability: dict[str, Any]) -> dict[str, Any]:
        return cls._error(
            ErrorCode.VOCAL_TUNING_PROVIDER_UNAVAILABLE,
            "The selected tuning provider has no verified control path for this plan.",
            {"provider": capability},
            "Use one of the provider's reported control modes or install a verified "
            "provider adapter.",
        )

    @classmethod
    def _stale(cls, message: str, details: dict[str, Any]) -> dict[str, Any]:
        return cls._error(
            ErrorCode.VOCAL_TUNING_PLAN_STALE,
            message,
            details,
            "Refresh the target state, then preview and approve a new plan.",
        )

    @staticmethod
    def _error(
        code: ErrorCode,
        message: str,
        details: dict[str, Any],
        suggested_action: str,
    ) -> dict[str, Any]:
        return {
            "ok": False,
            "error": ErrorResponse(
                code=code,
                message=message,
                details=details,
                recoverable=True,
                suggested_action=suggested_action,
            ).model_dump(mode="json"),
            "warnings": [],
        }
