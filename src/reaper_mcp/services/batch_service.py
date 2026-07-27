"""Atomic batch mutation service."""

from typing import Any

from pydantic import ValidationError

from reaper_mcp.bridge.base import BridgeClient
from reaper_mcp.errors import ErrorCode
from reaper_mcp.models.batch import BatchTrackUpdateResult, TrackBatchChange
from reaper_mcp.models.bridge import BridgeResponse, CommandOptions, ErrorResponse


class BatchService:
    """Expose preflighted batch operations."""

    def __init__(self, bridge_client: BridgeClient) -> None:
        self.bridge_client = bridge_client

    async def update_tracks(self, changes: list[dict[str, Any]]) -> dict[str, Any]:
        """Apply multiple track property changes in one undo block."""

        try:
            requests = [TrackBatchChange.model_validate(change) for change in changes]
            if not requests:
                raise ValueError("changes must be a non-empty array")
            if len(requests) > 64:
                raise ValueError("changes cannot contain more than 64 tracks")
            if len({request.track_guid for request in requests}) != len(requests):
                raise ValueError("changes must not contain duplicate track GUIDs")
        except (ValidationError, ValueError) as exc:
            return self._validation_error(exc)
        response = await self.bridge_client.execute(
            "batch_update_tracks",
            args={"changes": [request.model_dump(mode="json") for request in requests]},
            options=CommandOptions(
                mutates_project=True,
                undo_label=f"Batch update {len(requests)} tracks",
            ),
        )
        if not response.ok:
            return self._error_result(response)
        try:
            result = BatchTrackUpdateResult.model_validate(response.result or {})
        except ValidationError as exc:
            return self._invalid_payload(response, exc)
        return {
            "ok": True,
            "tracks": [track.model_dump(mode="json") for track in result.tracks],
            "track_count": result.track_count,
            "changes_applied": result.changes_applied,
            "warnings": response.warnings,
        }

    def _error_result(self, response: BridgeResponse) -> dict[str, Any]:
        return {
            "ok": False,
            "error": response.error.model_dump(mode="json") if response.error else None,
            "warnings": response.warnings,
        }

    def _validation_error(self, exc: ValidationError | ValueError) -> dict[str, Any]:
        details = (
            {"errors": exc.errors(include_context=False)}
            if isinstance(exc, ValidationError)
            else {"message": str(exc)}
        )
        return {
            "ok": False,
            "error": ErrorResponse(
                code=ErrorCode.INVALID_TRACK_REQUEST,
                message="The batch track request is invalid.",
                details=details,
                recoverable=True,
                suggested_action="Check track GUIDs and property values.",
            ).model_dump(mode="json"),
            "warnings": [],
        }

    def _invalid_payload(
        self, response: BridgeResponse, exc: ValidationError
    ) -> dict[str, Any]:
        return {
            "ok": False,
            "error": ErrorResponse(
                code=ErrorCode.INVALID_BRIDGE_RESPONSE,
                message="The Lua bridge returned an invalid batch payload.",
                details={"errors": exc.errors(include_context=False)},
                recoverable=True,
                suggested_action="Restart the Lua bridge and retry the batch.",
            ).model_dump(mode="json"),
            "warnings": response.warnings,
        }
