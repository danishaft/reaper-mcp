"""FX service."""

from typing import Any

from pydantic import ValidationError

from reaper_mcp.bridge.base import BridgeClient
from reaper_mcp.errors import ErrorCode
from reaper_mcp.models.bridge import BridgeResponse, CommandOptions, ErrorResponse
from reaper_mcp.models.fx import (
    AddFxRequest,
    AddFxResult,
    AddTakeFxRequest,
    AddTakeFxResult,
    AvailableFxList,
    CopyFxChainRequest,
    CopyFxChainResult,
    FxIdentity,
    FxParameterList,
    FxPresetBankResult,
    FxPresetResult,
    GetFxParametersRequest,
    MoveFxRequest,
    MoveFxResult,
    NavigateFxPresetsRequest,
    RemoveFxRequest,
    RemoveFxResult,
    RemoveTakeFxRequest,
    RemoveTakeFxResult,
    SetFxEnabledRequest,
    SetFxEnabledResult,
    SetFxParameterRequest,
    SetFxParameterResult,
    SetFxPresetIndexRequest,
    SetFxPresetRequest,
    SetTakeFxEnabledRequest,
    SetTakeFxEnabledResult,
    TakeFxList,
    TakeFxRequest,
    TrackFxList,
    TrackFxRequest,
)


class FxService:
    """Expose FX operations."""

    def __init__(self, bridge_client: BridgeClient) -> None:
        self.bridge_client = bridge_client

    async def list_take_fx(self, take_guid: str) -> dict[str, Any]:
        """Return FX on one media take by stable take GUID."""

        try:
            request = TakeFxRequest(take_guid=take_guid)
        except ValidationError as exc:
            return self._validation_error_result(exc)
        response = await self.bridge_client.execute(
            "list_take_fx", args=request.model_dump(mode="json")
        )
        if not response.ok:
            return self._error_result(response)
        try:
            result = TakeFxList.model_validate(response.result or {})
        except ValidationError as exc:
            return self._invalid_payload_result(response, exc)
        return {
            "ok": True,
            **result.model_dump(mode="json"),
            "warnings": response.warnings,
        }

    async def add_take_fx(
        self,
        take_guid: str,
        fx_identifier: str,
        index: int | None = None,
        enabled: bool = True,
    ) -> dict[str, Any]:
        """Add one FX to a media take."""

        try:
            request = AddTakeFxRequest(
                take_guid=take_guid,
                fx_identifier=fx_identifier,
                index=index,
                enabled=enabled,
            )
        except ValidationError as exc:
            return self._validation_error_result(exc)
        response = await self.bridge_client.execute(
            "add_take_fx",
            args=request.model_dump(mode="json", exclude_none=True),
            options=CommandOptions(
                mutates_project=True,
                undo_label=f"Add take FX: {request.fx_identifier}",
            ),
        )
        return self._take_fx_result(response, AddTakeFxResult)

    async def remove_take_fx(self, fx_identity: dict[str, Any]) -> dict[str, Any]:
        """Remove one take FX after checking its guarded identity."""

        try:
            request = RemoveTakeFxRequest(fx_identity=fx_identity)
        except ValidationError as exc:
            return self._validation_error_result(exc)
        response = await self.bridge_client.execute(
            "remove_take_fx",
            args=request.model_dump(mode="json"),
            options=CommandOptions(mutates_project=True, undo_label="Remove take FX"),
        )
        return self._take_fx_result(response, RemoveTakeFxResult)

    async def set_take_fx_enabled(
        self, fx_identity: dict[str, Any], enabled: bool
    ) -> dict[str, Any]:
        """Set one take FX enabled state after checking its identity."""

        try:
            request = SetTakeFxEnabledRequest(fx_identity=fx_identity, enabled=enabled)
        except ValidationError as exc:
            return self._validation_error_result(exc)
        response = await self.bridge_client.execute(
            "set_take_fx_enabled",
            args=request.model_dump(mode="json"),
            options=CommandOptions(
                mutates_project=True, undo_label="Set take FX enabled"
            ),
        )
        return self._take_fx_result(response, SetTakeFxEnabledResult)

    async def list_available_fx(self) -> dict[str, Any]:
        """Return installed FX entries that can be used for later insertion."""

        response = await self.bridge_client.execute("list_available_fx")
        if not response.ok:
            return self._error_result(response)

        try:
            result = AvailableFxList.model_validate(response.result or {})
        except ValidationError as exc:
            return self._invalid_payload_result(response, exc)

        return {
            "ok": True,
            "fx": [fx.model_dump(mode="json") for fx in result.fx],
            "fx_count": result.fx_count,
            "warnings": response.warnings,
        }

    async def list_track_fx(self, track_guid: str) -> dict[str, Any]:
        """Return FX on one track by stable track GUID."""

        try:
            request = TrackFxRequest(track_guid=track_guid)
        except ValidationError as exc:
            return self._validation_error_result(exc)

        response = await self.bridge_client.execute(
            "list_track_fx",
            args=request.model_dump(mode="json"),
        )
        if not response.ok:
            return self._error_result(response)

        try:
            result = TrackFxList.model_validate(response.result or {})
        except ValidationError as exc:
            return self._invalid_payload_result(response, exc)

        return {
            "ok": True,
            "track_guid": result.track_guid,
            "fx": [fx.model_dump(mode="json") for fx in result.fx],
            "fx_count": result.fx_count,
            "warnings": response.warnings,
        }

    async def add_fx(
        self,
        track_guid: str,
        fx_identifier: str,
        index: int | None = None,
        enabled: bool = True,
    ) -> dict[str, Any]:
        """Add one FX to a track."""

        try:
            request = AddFxRequest(
                track_guid=track_guid,
                fx_identifier=fx_identifier,
                index=index,
                enabled=enabled,
            )
        except ValidationError as exc:
            return self._validation_error_result(exc)

        response = await self.bridge_client.execute(
            "add_fx",
            args=request.model_dump(mode="json", exclude_none=True),
            options=CommandOptions(
                mutates_project=True,
                undo_label=f"Add FX: {request.fx_identifier}",
            ),
        )
        if not response.ok:
            return self._error_result(response)

        try:
            result = AddFxResult.model_validate(response.result or {})
        except ValidationError as exc:
            return self._invalid_payload_result(response, exc)

        return {
            "ok": True,
            "track_guid": result.track_guid,
            "added_fx": result.added_fx.model_dump(mode="json"),
            "fx": [fx.model_dump(mode="json") for fx in result.fx],
            "fx_count": result.fx_count,
            "changes_applied": result.changes_applied,
            "warnings": response.warnings,
        }

    async def remove_fx(self, fx_identity: dict[str, Any]) -> dict[str, Any]:
        """Remove one FX after checking its guarded identity."""

        try:
            request = RemoveFxRequest(fx_identity=fx_identity)
        except ValidationError as exc:
            return self._validation_error_result(exc)

        response = await self.bridge_client.execute(
            "remove_fx",
            args=request.model_dump(mode="json"),
            options=CommandOptions(
                mutates_project=True,
                undo_label=f"Remove FX: {request.fx_identity.expected_name}",
            ),
        )
        if not response.ok:
            return self._error_result(response)

        try:
            result = RemoveFxResult.model_validate(response.result or {})
        except ValidationError as exc:
            return self._invalid_payload_result(response, exc)

        return {
            "ok": True,
            "track_guid": result.track_guid,
            "removed_fx_identity": result.removed_fx_identity,
            "fx": [fx.model_dump(mode="json") for fx in result.fx],
            "fx_count": result.fx_count,
            "changes_applied": result.changes_applied,
            "warnings": response.warnings,
        }

    async def set_fx_enabled(
        self,
        fx_identity: dict[str, Any],
        enabled: bool,
    ) -> dict[str, Any]:
        """Set one FX enabled state after checking its guarded identity."""

        try:
            request = SetFxEnabledRequest(
                fx_identity=fx_identity,
                enabled=enabled,
            )
        except ValidationError as exc:
            return self._validation_error_result(exc)

        response = await self.bridge_client.execute(
            "set_fx_enabled",
            args=request.model_dump(mode="json"),
            options=CommandOptions(
                mutates_project=True,
                undo_label=f"Set FX enabled: {request.fx_identity.expected_name}",
            ),
        )
        if not response.ok:
            return self._error_result(response)

        try:
            result = SetFxEnabledResult.model_validate(response.result or {})
        except ValidationError as exc:
            return self._invalid_payload_result(response, exc)

        return {
            "ok": True,
            "track_guid": result.track_guid,
            "updated_fx": result.updated_fx.model_dump(mode="json"),
            "fx": [fx.model_dump(mode="json") for fx in result.fx],
            "fx_count": result.fx_count,
            "changes_applied": result.changes_applied,
            "warnings": response.warnings,
        }

    async def get_fx_parameters(self, fx_identity: dict[str, Any]) -> dict[str, Any]:
        """Return parameters for one FX after checking its guarded identity."""

        try:
            request = GetFxParametersRequest(fx_identity=fx_identity)
        except ValidationError as exc:
            return self._validation_error_result(exc)

        response = await self.bridge_client.execute(
            "get_fx_parameters",
            args=request.model_dump(mode="json"),
        )
        if not response.ok:
            return self._error_result(response)

        try:
            result = FxParameterList.model_validate(response.result or {})
        except ValidationError as exc:
            return self._invalid_payload_result(response, exc)

        return {
            "ok": True,
            "fx_identity": result.fx_identity.model_dump(mode="json"),
            "parameters": [
                parameter.model_dump(mode="json") for parameter in result.parameters
            ],
            "parameter_count": result.parameter_count,
            "warnings": response.warnings,
        }

    async def set_fx_parameter(
        self,
        fx_identity: dict[str, Any],
        parameter_index: int,
        normalized_value: float,
    ) -> dict[str, Any]:
        """Set one normalized FX parameter value after checking FX identity."""

        try:
            request = SetFxParameterRequest(
                fx_identity=fx_identity,
                parameter_index=parameter_index,
                normalized_value=normalized_value,
            )
        except ValidationError as exc:
            return self._validation_error_result(exc)

        response = await self.bridge_client.execute(
            "set_fx_parameter",
            args=request.model_dump(mode="json"),
            options=CommandOptions(
                mutates_project=True,
                undo_label=f"Set FX parameter: {request.fx_identity.expected_name}",
            ),
        )
        if not response.ok:
            return self._error_result(response)

        try:
            result = SetFxParameterResult.model_validate(response.result or {})
        except ValidationError as exc:
            return self._invalid_payload_result(response, exc)

        return {
            "ok": True,
            "fx_identity": result.fx_identity.model_dump(mode="json"),
            "updated_parameter": result.updated_parameter.model_dump(mode="json"),
            "parameters": [
                parameter.model_dump(mode="json") for parameter in result.parameters
            ],
            "parameter_count": result.parameter_count,
            "changes_applied": result.changes_applied,
            "warnings": response.warnings,
        }

    async def get_fx_preset(self, fx_identity: dict[str, Any]) -> dict[str, Any]:
        """Return the current preset name for one guarded FX slot."""

        try:
            request = FxPresetResult(fx_identity=fx_identity)
        except ValidationError as exc:
            return self._validation_error_result(exc)
        response = await self.bridge_client.execute(
            "get_fx_preset",
            args=request.model_dump(mode="json"),
        )
        return self._preset_result(response)

    async def set_fx_preset(
        self, fx_identity: dict[str, Any], preset_name: str
    ) -> dict[str, Any]:
        """Set one guarded FX preset."""

        try:
            request = SetFxPresetRequest(
                fx_identity=fx_identity, preset_name=preset_name
            )
        except ValidationError as exc:
            return self._validation_error_result(exc)
        response = await self.bridge_client.execute(
            "set_fx_preset",
            args=request.model_dump(mode="json"),
            options=CommandOptions(
                mutates_project=True,
                undo_label=f"Set FX preset: {request.preset_name}",
            ),
        )
        return self._preset_result(response)

    async def get_fx_preset_index(self, fx_identity: dict[str, Any]) -> dict[str, Any]:
        """Return preset index and count for one guarded FX slot."""

        try:
            request = FxIdentity.model_validate(fx_identity)
        except ValidationError as exc:
            return self._validation_error_result(exc)
        response = await self.bridge_client.execute(
            "get_fx_preset_index",
            args={"fx_identity": request.model_dump(mode="json")},
        )
        return self._preset_bank_result(response)

    async def set_fx_preset_index(
        self, fx_identity: dict[str, Any], preset_index: int
    ) -> dict[str, Any]:
        """Select a factory or user preset by index."""

        try:
            request = SetFxPresetIndexRequest(
                fx_identity=fx_identity, preset_index=preset_index
            )
        except ValidationError as exc:
            return self._validation_error_result(exc)
        response = await self.bridge_client.execute(
            "set_fx_preset_index",
            args=request.model_dump(mode="json"),
            options=CommandOptions(
                mutates_project=True,
                undo_label=f"Set FX preset index: {request.preset_index}",
            ),
        )
        return self._preset_bank_result(response)

    async def navigate_fx_presets(
        self, fx_identity: dict[str, Any], direction: int
    ) -> dict[str, Any]:
        """Move one or more positions within a guarded FX preset bank."""

        try:
            request = NavigateFxPresetsRequest(
                fx_identity=fx_identity, direction=direction
            )
        except ValidationError as exc:
            return self._validation_error_result(exc)
        response = await self.bridge_client.execute(
            "navigate_fx_presets",
            args=request.model_dump(mode="json"),
            options=CommandOptions(
                mutates_project=True,
                undo_label=f"Navigate FX presets: {request.direction}",
            ),
        )
        return self._preset_bank_result(response)

    async def move_fx(
        self, fx_identity: dict[str, Any], destination_index: int
    ) -> dict[str, Any]:
        """Move one guarded FX slot inside its track chain."""

        try:
            request = MoveFxRequest(
                fx_identity=fx_identity, destination_index=destination_index
            )
        except ValidationError as exc:
            return self._validation_error_result(exc)
        response = await self.bridge_client.execute(
            "move_fx",
            args=request.model_dump(mode="json"),
            options=CommandOptions(mutates_project=True, undo_label="Move FX"),
        )
        if not response.ok:
            return self._error_result(response)
        try:
            result = MoveFxResult.model_validate(response.result or {})
        except ValidationError as exc:
            return self._invalid_payload_result(response, exc)
        return {
            "ok": True,
            "track_guid": result.track_guid,
            "moved_fx": result.moved_fx.model_dump(mode="json"),
            "fx": [fx.model_dump(mode="json") for fx in result.fx],
            "fx_count": result.fx_count,
            "changes_applied": result.changes_applied,
            "warnings": response.warnings,
        }

    async def copy_fx_chain(
        self,
        source_track_guid: str,
        destination_track_guid: str,
        replace_destination: bool = False,
    ) -> dict[str, Any]:
        """Copy one complete track FX chain to another track."""

        try:
            request = CopyFxChainRequest(
                source_track_guid=source_track_guid,
                destination_track_guid=destination_track_guid,
                replace_destination=replace_destination,
            )
        except ValidationError as exc:
            return self._validation_error_result(exc)
        response = await self.bridge_client.execute(
            "copy_fx_chain",
            args=request.model_dump(mode="json"),
            options=CommandOptions(
                mutates_project=True,
                undo_label="Copy FX chain",
            ),
        )
        if not response.ok:
            return self._error_result(response)
        try:
            result = CopyFxChainResult.model_validate(response.result or {})
        except ValidationError as exc:
            return self._invalid_payload_result(response, exc)
        return {
            "ok": True,
            "source_track_guid": result.source_track_guid,
            "track_guid": result.track_guid,
            "fx": [fx.model_dump(mode="json") for fx in result.fx],
            "fx_count": result.fx_count,
            "changes_applied": result.changes_applied,
            "warnings": response.warnings,
        }

    def _preset_result(self, response: BridgeResponse) -> dict[str, Any]:
        if not response.ok:
            return self._error_result(response)
        try:
            result = FxPresetResult.model_validate(response.result or {})
        except ValidationError as exc:
            return self._invalid_payload_result(response, exc)
        return {
            "ok": True,
            "fx_identity": result.fx_identity.model_dump(mode="json"),
            "preset_name": result.preset_name,
            "changes_applied": result.changes_applied,
            "warnings": response.warnings,
        }

    def _take_fx_result(
        self,
        response: BridgeResponse,
        result_type: type[TakeFxList] = TakeFxList,
    ) -> dict[str, Any]:
        if not response.ok:
            return self._error_result(response)
        try:
            result = result_type.model_validate(response.result or {})
        except ValidationError as exc:
            return self._invalid_payload_result(response, exc)
        return {
            "ok": True,
            **result.model_dump(mode="json"),
            "warnings": response.warnings,
        }

    def _preset_bank_result(self, response: BridgeResponse) -> dict[str, Any]:
        if not response.ok:
            return self._error_result(response)
        try:
            result = FxPresetBankResult.model_validate(response.result or {})
        except ValidationError as exc:
            return self._invalid_payload_result(response, exc)
        return {
            "ok": True,
            **result.model_dump(mode="json"),
            "warnings": response.warnings,
        }

    def _error_result(self, response: BridgeResponse) -> dict[str, Any]:
        return {
            "ok": False,
            "error": response.error.model_dump(mode="json") if response.error else None,
            "warnings": response.warnings,
        }

    def _invalid_payload_result(
        self, response: BridgeResponse, exc: ValidationError
    ) -> dict[str, Any]:
        return {
            "ok": False,
            "error": ErrorResponse(
                code=ErrorCode.INVALID_BRIDGE_RESPONSE,
                message="The Lua bridge returned an invalid FX payload.",
                details={"errors": exc.errors(include_context=False)},
                recoverable=True,
                suggested_action="Restart the Lua bridge and retry the command.",
            ).model_dump(mode="json"),
            "warnings": response.warnings,
        }

    def _validation_error_result(self, exc: ValidationError) -> dict[str, Any]:
        return {
            "ok": False,
            "error": ErrorResponse(
                code=ErrorCode.INVALID_FX_REQUEST,
                message="The FX request is invalid.",
                details={"errors": exc.errors(include_context=False)},
                recoverable=True,
                suggested_action="Check the track GUID value.",
            ).model_dump(mode="json"),
            "warnings": [],
        }
