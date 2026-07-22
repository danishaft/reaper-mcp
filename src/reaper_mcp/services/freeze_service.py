"""Track freeze service."""

from typing import Any

from pydantic import ValidationError

from reaper_mcp.bridge.base import BridgeClient
from reaper_mcp.errors import ErrorCode
from reaper_mcp.models.bridge import BridgeResponse, CommandOptions, ErrorResponse
from reaper_mcp.models.freeze import TrackFreezeResult, TrackFreezeState
from reaper_mcp.models.project import TrackGuidRequest


class FreezeService:
    """Expose verified track freeze operations."""

    def __init__(self, bridge_client: BridgeClient) -> None:
        self.bridge_client = bridge_client

    async def get_track_freeze_state(self, track_guid: str) -> dict[str, Any]:
        """Return the current freeze count for one track GUID."""

        request = self._validate_request(track_guid)
        if isinstance(request, dict):
            return request
        response = await self.bridge_client.execute(
            "get_track_freeze_state",
            args=request.model_dump(mode="json"),
        )
        if not response.ok:
            return self._error_result(response)
        try:
            state = TrackFreezeState.model_validate(response.result or {})
        except ValidationError as exc:
            return self._invalid_payload_result(response, exc)
        return {
            "ok": True,
            "state": state.model_dump(mode="json"),
            "warnings": response.warnings,
        }

    async def freeze_track(self, track_guid: str) -> dict[str, Any]:
        """Freeze one track to stereo and verify the state transition."""

        return await self._execute_freeze_mutation(
            "freeze_track",
            track_guid,
            "Freeze track to stereo",
        )

    async def unfreeze_track(self, track_guid: str) -> dict[str, Any]:
        """Unfreeze one track and verify the state transition."""

        return await self._execute_freeze_mutation(
            "unfreeze_track",
            track_guid,
            "Unfreeze track",
        )

    async def _execute_freeze_mutation(
        self,
        command: str,
        track_guid: str,
        undo_label: str,
    ) -> dict[str, Any]:
        request = self._validate_request(track_guid)
        if isinstance(request, dict):
            return request
        response = await self.bridge_client.execute(
            command,
            args=request.model_dump(mode="json"),
            options=CommandOptions(
                mutates_project=True,
                undo_label=undo_label,
            ),
        )
        if not response.ok:
            return self._error_result(response)
        try:
            result = TrackFreezeResult.model_validate(response.result or {})
        except ValidationError as exc:
            return self._invalid_payload_result(response, exc)
        return {
            "ok": True,
            **result.model_dump(mode="json"),
            "warnings": response.warnings,
        }

    def _validate_request(self, track_guid: str) -> TrackGuidRequest | dict[str, Any]:
        try:
            return TrackGuidRequest(track_guid=track_guid)
        except ValidationError as exc:
            return {
                "ok": False,
                "error": ErrorResponse(
                    code=ErrorCode.INVALID_TRACK_REQUEST,
                    message="The track freeze request is invalid.",
                    details={"errors": exc.errors(include_context=False)},
                    recoverable=True,
                    suggested_action="Provide a current non-empty track GUID.",
                ).model_dump(mode="json"),
                "warnings": [],
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
                message="The Lua bridge returned an invalid freeze payload.",
                details={"errors": exc.errors(include_context=False)},
                recoverable=True,
                suggested_action="Restart the bridge and refresh track state.",
            ).model_dump(mode="json"),
            "warnings": response.warnings,
        }
