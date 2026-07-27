"""High-level music workflow service."""

from typing import Any

from pydantic import ValidationError

from reaper_mcp.bridge.base import BridgeClient
from reaper_mcp.errors import ErrorCode
from reaper_mcp.models.bridge import BridgeResponse, CommandOptions, ErrorResponse
from reaper_mcp.models.workflow import (
    CreateMidiPatternRequest,
    CreateMidiPatternResult,
    CreateSongStarterRequest,
    CreateSongStarterResult,
    SongStarterMode,
)


class WorkflowService:
    """Expose bounded workflows that execute as one REAPER mutation."""

    def __init__(self, bridge_client: BridgeClient) -> None:
        self.bridge_client = bridge_client

    async def create_midi_pattern(
        self,
        track_guid: str,
        pattern: str,
        start_measure: int = 1,
        bars: int = 8,
        root_note: int = 60,
        mode: SongStarterMode = "major",
        subdivision_beats: float = 0.5,
    ) -> dict[str, Any]:
        """Create a deterministic chord or arpeggio pattern on one track."""

        try:
            request = CreateMidiPatternRequest(
                track_guid=track_guid,
                pattern=pattern,
                start_measure=start_measure,
                bars=bars,
                root_note=root_note,
                mode=mode,
                subdivision_beats=subdivision_beats,
            )
        except ValidationError as exc:
            return self._validation_error_result(exc)

        response = await self.bridge_client.execute(
            "create_midi_pattern",
            args=request.model_dump(mode="json"),
            options=CommandOptions(
                mutates_project=True,
                undo_label=f"Create MIDI {request.pattern}",
            ),
        )
        if not response.ok:
            return self._error_result(response)
        try:
            result = CreateMidiPatternResult.model_validate(response.result or {})
        except ValidationError as exc:
            return self._invalid_payload_result(response, exc)
        return {
            "ok": True,
            **result.model_dump(mode="json"),
            "warnings": response.warnings,
        }

    async def create_song_starter(
        self,
        name: str = "Song Starter",
        start_measure: int = 1,
        bars: int = 8,
        root_note: int = 60,
        mode: SongStarterMode = "major",
    ) -> dict[str, Any]:
        """Create four arranged MIDI parts and one region in a single undo step."""

        try:
            request = CreateSongStarterRequest(
                name=name,
                start_measure=start_measure,
                bars=bars,
                root_note=root_note,
                mode=mode,
            )
        except ValidationError as exc:
            return self._validation_error_result(exc)

        response = await self.bridge_client.execute(
            "create_song_starter",
            args=request.model_dump(mode="json"),
            options=CommandOptions(
                mutates_project=True,
                undo_label=f"Create song starter: {request.name}",
            ),
        )
        if not response.ok:
            return self._error_result(response)

        try:
            result = CreateSongStarterResult.model_validate(response.result or {})
        except ValidationError as exc:
            return self._invalid_payload_result(response, exc)
        return {
            "ok": True,
            **result.model_dump(mode="json"),
            "warnings": response.warnings,
        }

    def _validation_error_result(self, exc: ValidationError) -> dict[str, Any]:
        return {
            "ok": False,
            "error": ErrorResponse(
                code=ErrorCode.INVALID_WORKFLOW_REQUEST,
                message="The song starter request is invalid.",
                details={"errors": exc.errors(include_context=False)},
                recoverable=True,
                suggested_action=(
                    "Use a visible name, 4 to 32 bars in multiples of 4, a root "
                    "note from 48 to 72, and major or minor mode."
                ),
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
        self,
        response: BridgeResponse,
        exc: ValidationError,
    ) -> dict[str, Any]:
        return {
            "ok": False,
            "error": ErrorResponse(
                code=ErrorCode.INVALID_BRIDGE_RESPONSE,
                message="The Lua bridge returned an invalid song starter payload.",
                details={"errors": exc.errors(include_context=False)},
                recoverable=True,
                suggested_action="Restart the bridge and inspect the active project.",
            ).model_dump(mode="json"),
            "warnings": response.warnings,
        }
