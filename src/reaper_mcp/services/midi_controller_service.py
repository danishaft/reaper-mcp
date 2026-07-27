"""MIDI controller-event service."""

from typing import Any

from pydantic import ValidationError

from reaper_mcp.bridge.base import BridgeClient
from reaper_mcp.errors import ErrorCode
from reaper_mcp.models.bridge import BridgeResponse, CommandOptions, ErrorResponse
from reaper_mcp.models.midi_controller import (
    AddMidiControllersResult,
    DeleteMidiControllersResult,
    MidiControllerIdentity,
    MidiControllerInput,
    MidiControllerList,
    UpdateMidiControllerResult,
)


class MidiControllerService:
    """Expose guarded MIDI controller-event operations."""

    def __init__(self, bridge_client: BridgeClient) -> None:
        self.bridge_client = bridge_client

    async def list_events(self, take_guid: str) -> dict[str, Any]:
        """Return controller events in one take."""

        response = await self.bridge_client.execute(
            "get_midi_controller_events", args={"take_guid": take_guid}
        )
        if not response.ok:
            return self._error_result(response)
        try:
            result = MidiControllerList.model_validate(response.result or {})
        except ValidationError as exc:
            return self._invalid_payload_result(response, exc)
        return self._list_result(result, response)

    async def add_events(
        self, take_guid: str, events: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Insert controller events in one guarded batch."""

        try:
            request_events = [
                MidiControllerInput.model_validate(event) for event in events
            ]
            if not request_events:
                raise ValueError("events must be a non-empty array")
        except (ValidationError, ValueError) as exc:
            return self._validation_error_result(exc)
        response = await self.bridge_client.execute(
            "add_midi_controller_events",
            args={
                "take_guid": take_guid,
                "events": [event.model_dump(mode="json") for event in request_events],
            },
            options=CommandOptions(
                mutates_project=True,
                undo_label=f"Add {len(request_events)} MIDI controller events",
            ),
        )
        if not response.ok:
            return self._error_result(response)
        try:
            result = AddMidiControllersResult.model_validate(response.result or {})
        except ValidationError as exc:
            return self._invalid_payload_result(response, exc)
        return self._mutation_result(
            result, response, "inserted_events", "inserted_count"
        )

    async def update_event(
        self,
        take_guid: str,
        index: int,
        expected_fingerprint: str,
        event: dict[str, Any],
    ) -> dict[str, Any]:
        """Update one controller event after checking its fingerprint."""

        try:
            request_event = MidiControllerInput.model_validate(event)
            identity = MidiControllerIdentity(
                index=index, expected_fingerprint=expected_fingerprint
            )
        except ValidationError as exc:
            return self._validation_error_result(exc)
        response = await self.bridge_client.execute(
            "update_midi_controller_event",
            args={
                "take_guid": take_guid,
                "identity": identity.model_dump(mode="json"),
                "event": request_event.model_dump(mode="json"),
            },
            options=CommandOptions(
                mutates_project=True,
                undo_label="Update MIDI controller event",
            ),
        )
        if not response.ok:
            return self._error_result(response)
        try:
            result = UpdateMidiControllerResult.model_validate(response.result or {})
        except ValidationError as exc:
            return self._invalid_payload_result(response, exc)
        return {
            "ok": True,
            "take_guid": result.take_guid,
            "updated_event": result.updated_event.model_dump(mode="json"),
            "events": [event.model_dump(mode="json") for event in result.events],
            "event_count": result.event_count,
            "changes_applied": result.changes_applied,
            "warnings": response.warnings,
        }

    async def delete_events(
        self, take_guid: str, events: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Delete controller events after checking their fingerprints."""

        try:
            identities = [
                MidiControllerIdentity.model_validate(event) for event in events
            ]
            if not identities:
                raise ValueError("events must be a non-empty array")
            if len({identity.index for identity in identities}) != len(identities):
                raise ValueError("events must not contain duplicate indexes")
        except (ValidationError, ValueError) as exc:
            return self._validation_error_result(exc)
        response = await self.bridge_client.execute(
            "delete_midi_controller_events",
            args={
                "take_guid": take_guid,
                "events": [identity.model_dump(mode="json") for identity in identities],
            },
            options=CommandOptions(
                mutates_project=True,
                undo_label=f"Delete {len(identities)} MIDI controller events",
            ),
        )
        if not response.ok:
            return self._error_result(response)
        try:
            result = DeleteMidiControllersResult.model_validate(response.result or {})
        except ValidationError as exc:
            return self._invalid_payload_result(response, exc)
        return {
            "ok": True,
            "take_guid": result.take_guid,
            "events": [event.model_dump(mode="json") for event in result.events],
            "event_count": result.event_count,
            "deleted_count": result.deleted_count,
            "changes_applied": result.changes_applied,
            "warnings": response.warnings,
        }

    def _list_result(
        self, result: MidiControllerList, response: BridgeResponse
    ) -> dict[str, Any]:
        return {
            "ok": True,
            "take_guid": result.take_guid,
            "events": [event.model_dump(mode="json") for event in result.events],
            "event_count": result.event_count,
            "warnings": response.warnings,
        }

    def _mutation_result(
        self,
        result: AddMidiControllersResult,
        response: BridgeResponse,
        inserted_key: str,
        count_key: str,
    ) -> dict[str, Any]:
        return {
            "ok": True,
            "take_guid": result.take_guid,
            "events": [event.model_dump(mode="json") for event in result.events],
            "event_count": result.event_count,
            inserted_key: [
                event.model_dump(mode="json") for event in result.inserted_events
            ],
            count_key: result.inserted_count,
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
                message="The Lua bridge returned an invalid MIDI controller payload.",
                details={"errors": exc.errors(include_context=False)},
                recoverable=True,
                suggested_action="Restart the Lua bridge and retry the command.",
            ).model_dump(mode="json"),
            "warnings": response.warnings,
        }

    def _validation_error_result(
        self, exc: ValidationError | ValueError
    ) -> dict[str, Any]:
        errors = (
            exc.errors(include_context=False)
            if isinstance(exc, ValidationError)
            else [{"msg": str(exc)}]
        )
        return {
            "ok": False,
            "error": ErrorResponse(
                code=ErrorCode.INVALID_MIDI_CONTROLLER_REQUEST,
                message="The MIDI controller request is invalid.",
                details={"errors": errors},
                recoverable=True,
                suggested_action="Check event type, position, channel, and value.",
            ).model_dump(mode="json"),
            "warnings": [],
        }
