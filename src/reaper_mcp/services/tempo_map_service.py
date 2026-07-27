"""Tempo-map marker service."""

from typing import Any

from pydantic import ValidationError

from reaper_mcp.bridge.base import BridgeClient
from reaper_mcp.errors import ErrorCode
from reaper_mcp.models.bridge import BridgeResponse, CommandOptions, ErrorResponse
from reaper_mcp.models.tempo import (
    TempoMarkerIdentity,
    TempoMarkerInput,
    TempoMarkerList,
    TempoMarkerMutationResult,
)


class TempoMapService:
    """Expose guarded tempo-map marker operations."""

    def __init__(self, bridge_client: BridgeClient) -> None:
        self.bridge_client = bridge_client

    async def list_markers(self) -> dict[str, Any]:
        """Return tempo-map markers in timeline order."""

        response = await self.bridge_client.execute("list_tempo_markers")
        if not response.ok:
            return self._error_result(response)
        try:
            result = TempoMarkerList.model_validate(response.result or {})
        except ValidationError as exc:
            return self._invalid_payload_result(response, exc)
        return self._list_result(result, response)

    async def create_marker(
        self,
        position_seconds: float,
        bpm: float,
        numerator: int = 4,
        denominator: int = 4,
        linear: bool = False,
    ) -> dict[str, Any]:
        """Create one tempo-map marker."""

        try:
            marker = TempoMarkerInput(
                position_seconds=position_seconds,
                bpm=bpm,
                numerator=numerator,
                denominator=denominator,
                linear=linear,
            )
        except ValidationError as exc:
            return self._validation_error_result(exc)
        response = await self.bridge_client.execute(
            "create_tempo_marker",
            args=marker.model_dump(mode="json"),
            options=CommandOptions(
                mutates_project=True,
                undo_label=f"Create tempo marker: {marker.bpm:g} BPM",
            ),
        )
        return self._mutation_response(response)

    async def update_marker(
        self,
        index: int,
        expected_fingerprint: str,
        position_seconds: float,
        bpm: float,
        numerator: int = 4,
        denominator: int = 4,
        linear: bool = False,
    ) -> dict[str, Any]:
        """Update one guarded tempo-map marker."""

        try:
            identity = TempoMarkerIdentity(
                index=index, expected_fingerprint=expected_fingerprint
            )
            marker = TempoMarkerInput(
                position_seconds=position_seconds,
                bpm=bpm,
                numerator=numerator,
                denominator=denominator,
                linear=linear,
            )
        except ValidationError as exc:
            return self._validation_error_result(exc)
        response = await self.bridge_client.execute(
            "update_tempo_marker",
            args={
                "identity": identity.model_dump(mode="json"),
                "marker": marker.model_dump(mode="json"),
            },
            options=CommandOptions(
                mutates_project=True,
                undo_label="Update tempo marker",
            ),
        )
        return self._mutation_response(response)

    async def delete_marker(
        self, index: int, expected_fingerprint: str
    ) -> dict[str, Any]:
        """Delete one guarded tempo-map marker."""

        try:
            identity = TempoMarkerIdentity(
                index=index, expected_fingerprint=expected_fingerprint
            )
        except ValidationError as exc:
            return self._validation_error_result(exc)
        response = await self.bridge_client.execute(
            "delete_tempo_marker",
            args={"identity": identity.model_dump(mode="json")},
            options=CommandOptions(
                mutates_project=True,
                undo_label="Delete tempo marker",
            ),
        )
        return self._mutation_response(response)

    def _mutation_response(self, response: BridgeResponse) -> dict[str, Any]:
        if not response.ok:
            return self._error_result(response)
        try:
            result = TempoMarkerMutationResult.model_validate(response.result or {})
        except ValidationError as exc:
            return self._invalid_payload_result(response, exc)
        payload = self._list_result(result, response)
        payload["changes_applied"] = result.changes_applied
        if result.marker is not None:
            payload["marker"] = result.marker.model_dump(mode="json")
        if result.deleted_marker_index is not None:
            payload["deleted_marker_index"] = result.deleted_marker_index
        return payload

    def _list_result(
        self, result: TempoMarkerList, response: BridgeResponse
    ) -> dict[str, Any]:
        return {
            "ok": True,
            "markers": [marker.model_dump(mode="json") for marker in result.markers],
            "marker_count": result.marker_count,
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
                message="The Lua bridge returned an invalid tempo-map payload.",
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
                code=ErrorCode.INVALID_TEMPO_REQUEST,
                message="The tempo-map marker request is invalid.",
                details={"errors": exc.errors(include_context=False)},
                recoverable=True,
                suggested_action="Check position, BPM, and time signature values.",
            ).model_dump(mode="json"),
            "warnings": [],
        }
