"""FX service."""

from typing import Any

from pydantic import ValidationError

from reaper_mcp.bridge.base import BridgeClient
from reaper_mcp.errors import ErrorCode
from reaper_mcp.models.bridge import BridgeResponse, CommandOptions, ErrorResponse
from reaper_mcp.models.fx import (
    AddFxRequest,
    AddFxResult,
    AvailableFxList,
    FxParameterList,
    GetFxParametersRequest,
    RemoveFxRequest,
    RemoveFxResult,
    SetFxEnabledRequest,
    SetFxEnabledResult,
    SetFxParameterRequest,
    SetFxParameterResult,
    TrackFxList,
    TrackFxRequest,
)


class FxService:
    """Expose FX operations."""

    def __init__(self, bridge_client: BridgeClient) -> None:
        self.bridge_client = bridge_client

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
