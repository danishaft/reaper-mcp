"""Tempo and time signature service."""

from typing import Any

from pydantic import ValidationError

from reaper_mcp.bridge.base import BridgeClient
from reaper_mcp.errors import ErrorCode
from reaper_mcp.models.bridge import BridgeResponse, CommandOptions, ErrorResponse
from reaper_mcp.models.tempo import (
    SetTempoRequest,
    SetTempoResult,
    SetTimeSignatureRequest,
    SetTimeSignatureResult,
    TempoResult,
    TimeSignatureResult,
)


class TempoService:
    """Expose project tempo and time signature operations."""

    def __init__(self, bridge_client: BridgeClient) -> None:
        self.bridge_client = bridge_client

    async def get_tempo(self) -> dict[str, Any]:
        """Return the effective project tempo at the project start."""

        response = await self.bridge_client.execute("get_tempo")
        if not response.ok:
            return self._error_result(response)

        try:
            result = TempoResult.model_validate(response.result or {})
        except ValidationError as exc:
            return self._invalid_payload_result(response, exc)

        return {
            "ok": True,
            "tempo": result.tempo.model_dump(mode="json"),
            "warnings": response.warnings,
        }

    async def set_tempo(self, bpm: float) -> dict[str, Any]:
        """Set the project tempo in one undoable operation."""

        try:
            request = SetTempoRequest(bpm=bpm)
        except ValidationError as exc:
            return self._validation_error_result(exc)

        response = await self.bridge_client.execute(
            "set_tempo",
            args=request.model_dump(mode="json"),
            options=CommandOptions(
                mutates_project=True,
                undo_label=f"Set tempo: {request.bpm:g} BPM",
            ),
        )
        if not response.ok:
            return self._error_result(response)

        try:
            result = SetTempoResult.model_validate(response.result or {})
        except ValidationError as exc:
            return self._invalid_payload_result(response, exc)

        return {
            "ok": True,
            "tempo": result.tempo.model_dump(mode="json"),
            "changes_applied": result.changes_applied,
            "warnings": response.warnings,
        }

    async def get_time_signature(self) -> dict[str, Any]:
        """Return the effective time signature at the project start."""

        response = await self.bridge_client.execute("get_time_signature")
        if not response.ok:
            return self._error_result(response)

        try:
            result = TimeSignatureResult.model_validate(response.result or {})
        except ValidationError as exc:
            return self._invalid_payload_result(response, exc)

        return {
            "ok": True,
            "time_signature": result.time_signature.model_dump(mode="json"),
            "tempo": result.tempo.model_dump(mode="json"),
            "warnings": response.warnings,
        }

    async def set_time_signature(
        self,
        numerator: int,
        denominator: int,
    ) -> dict[str, Any]:
        """Set the project time signature in one undoable operation."""

        try:
            request = SetTimeSignatureRequest(
                numerator=numerator,
                denominator=denominator,
            )
        except ValidationError as exc:
            return self._validation_error_result(exc)

        response = await self.bridge_client.execute(
            "set_time_signature",
            args=request.model_dump(mode="json"),
            options=CommandOptions(
                mutates_project=True,
                undo_label=(
                    f"Set time signature: {request.numerator}/{request.denominator}"
                ),
            ),
        )
        if not response.ok:
            return self._error_result(response)

        try:
            result = SetTimeSignatureResult.model_validate(response.result or {})
        except ValidationError as exc:
            return self._invalid_payload_result(response, exc)

        return {
            "ok": True,
            "time_signature": result.time_signature.model_dump(mode="json"),
            "tempo": result.tempo.model_dump(mode="json"),
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
                message="The Lua bridge returned an invalid tempo payload.",
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
                message="The tempo or time signature request is invalid.",
                details={"errors": exc.errors(include_context=False)},
                recoverable=True,
                suggested_action="Check BPM, numerator, and denominator values.",
            ).model_dump(mode="json"),
            "warnings": [],
        }
