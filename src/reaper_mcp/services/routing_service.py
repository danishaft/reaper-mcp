"""Track routing service."""

from typing import Any

from pydantic import ValidationError

from reaper_mcp.bridge.base import BridgeClient
from reaper_mcp.errors import ErrorCode
from reaper_mcp.models.bridge import BridgeResponse, CommandOptions, ErrorResponse
from reaper_mcp.models.routing import (
    CreateTrackSendRequest,
    CreateTrackSendResult,
    RemoveTrackSendRequest,
    RemoveTrackSendResult,
    SetTrackSendRequest,
    SetTrackSendResult,
    SidechainResult,
    TrackSendIdentity,
    TrackSendList,
)


class RoutingService:
    """Expose guarded track send operations."""

    def __init__(self, bridge_client: BridgeClient) -> None:
        self.bridge_client = bridge_client

    async def list_track_sends(self, source_track_guid: str) -> dict[str, Any]:
        """Return sends for one source track."""

        if not source_track_guid:
            return self._validation_error_result(
                ValueError("source_track_guid must be a non-empty string")
            )
        response = await self.bridge_client.execute(
            "list_track_sends",
            args={"source_track_guid": source_track_guid},
        )
        if not response.ok:
            return self._error_result(response)
        try:
            result = TrackSendList.model_validate(response.result or {})
        except ValidationError as exc:
            return self._invalid_payload_result(response, exc)
        return {
            "ok": True,
            "source_track_guid": result.source_track_guid,
            "sends": [send.model_dump(mode="json") for send in result.sends],
            "send_count": result.send_count,
            "warnings": response.warnings,
        }

    async def create_track_send(
        self,
        source_track_guid: str,
        destination_track_guid: str,
        volume: float = 1.0,
        pan: float = 0.0,
        muted: bool = False,
    ) -> dict[str, Any]:
        """Create one send between stable track GUIDs."""

        try:
            request = CreateTrackSendRequest(
                source_track_guid=source_track_guid,
                destination_track_guid=destination_track_guid,
                volume=volume,
                pan=pan,
                muted=muted,
            )
        except ValidationError as exc:
            return self._validation_error_result(exc)
        response = await self.bridge_client.execute(
            "create_track_send",
            args=request.model_dump(mode="json"),
            options=CommandOptions(
                mutates_project=True,
                undo_label="Create track send",
            ),
        )
        if not response.ok:
            return self._error_result(response)
        try:
            result = CreateTrackSendResult.model_validate(response.result or {})
        except ValidationError as exc:
            return self._invalid_payload_result(response, exc)
        return {
            "ok": True,
            "send": result.send.model_dump(mode="json"),
            "send_count": result.send_count,
            "changes_applied": result.changes_applied,
            "warnings": response.warnings,
        }

    async def set_track_send(
        self,
        source_track_guid: str,
        send_index: int,
        expected_destination_track_guid: str,
        *,
        volume: float | None = None,
        pan: float | None = None,
        muted: bool | None = None,
    ) -> dict[str, Any]:
        """Change one send after checking its destination identity."""

        try:
            request = SetTrackSendRequest(
                send_identity=TrackSendIdentity(
                    source_track_guid=source_track_guid,
                    index=send_index,
                    expected_destination_track_guid=(expected_destination_track_guid),
                ),
                volume=volume,
                pan=pan,
                muted=muted,
            )
        except ValidationError as exc:
            return self._validation_error_result(exc)
        response = await self.bridge_client.execute(
            "set_track_send",
            args=request.model_dump(mode="json", exclude_none=True),
            options=CommandOptions(
                mutates_project=True,
                undo_label="Set track send",
            ),
        )
        if not response.ok:
            return self._error_result(response)
        try:
            result = SetTrackSendResult.model_validate(response.result or {})
        except ValidationError as exc:
            return self._invalid_payload_result(response, exc)
        return {
            "ok": True,
            "send": result.send.model_dump(mode="json"),
            "changes_applied": result.changes_applied,
            "warnings": response.warnings,
        }

    async def remove_track_send(
        self,
        source_track_guid: str,
        send_index: int,
        expected_destination_track_guid: str,
    ) -> dict[str, Any]:
        """Remove one send after checking its destination identity."""

        try:
            request = RemoveTrackSendRequest(
                send_identity=TrackSendIdentity(
                    source_track_guid=source_track_guid,
                    index=send_index,
                    expected_destination_track_guid=(expected_destination_track_guid),
                )
            )
        except ValidationError as exc:
            return self._validation_error_result(exc)
        response = await self.bridge_client.execute(
            "remove_track_send",
            args=request.model_dump(mode="json"),
            options=CommandOptions(
                mutates_project=True,
                undo_label="Remove track send",
            ),
        )
        if not response.ok:
            return self._error_result(response)
        try:
            result = RemoveTrackSendResult.model_validate(response.result or {})
        except ValidationError as exc:
            return self._invalid_payload_result(response, exc)
        return {
            "ok": True,
            **result.model_dump(mode="json"),
            "warnings": response.warnings,
        }

    async def setup_sidechain(
        self,
        source_track_guid: str,
        destination_track_guid: str,
        amount: float = 1.0,
    ) -> dict[str, Any]:
        """Create a source-to-destination sidechain send on channels 3/4."""

        try:
            request = CreateTrackSendRequest(
                source_track_guid=source_track_guid,
                destination_track_guid=destination_track_guid,
                volume=amount,
            )
        except ValidationError as exc:
            return self._validation_error_result(exc)
        response = await self.bridge_client.execute(
            "setup_sidechain",
            args=request.model_dump(mode="json"),
            options=CommandOptions(
                mutates_project=True,
                undo_label="Setup sidechain",
            ),
        )
        if not response.ok:
            return self._error_result(response)
        try:
            result = SidechainResult.model_validate(response.result or {})
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

    def _validation_error_result(
        self, exc: ValidationError | ValueError
    ) -> dict[str, Any]:
        details = {"error": str(exc)}
        if isinstance(exc, ValidationError):
            details = {"errors": exc.errors(include_context=False)}
        return {
            "ok": False,
            "error": ErrorResponse(
                code=ErrorCode.INVALID_SEND_REQUEST,
                message="The track send request is invalid.",
                details=details,
                recoverable=True,
                suggested_action="Check track GUIDs, send index, volume, and pan.",
            ).model_dump(mode="json"),
            "warnings": [],
        }

    def _invalid_payload_result(
        self, response: BridgeResponse, exc: ValidationError
    ) -> dict[str, Any]:
        return {
            "ok": False,
            "error": ErrorResponse(
                code=ErrorCode.INVALID_BRIDGE_RESPONSE,
                message="The Lua bridge returned an invalid routing payload.",
                details={"errors": exc.errors(include_context=False)},
                recoverable=True,
                suggested_action="Restart the Lua bridge and refresh track sends.",
            ).model_dump(mode="json"),
            "warnings": response.warnings,
        }
