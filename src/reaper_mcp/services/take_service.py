"""Media take and comping service."""

from typing import Any

from pydantic import ValidationError

from reaper_mcp.bridge.base import BridgeClient
from reaper_mcp.errors import ErrorCode
from reaper_mcp.models.bridge import CommandOptions
from reaper_mcp.models.take import (
    AddEmptyTakeRequest,
    CropToActiveTakeRequest,
    RenameTakeRequest,
    SetTakePropertyRequest,
    TakeGuidRequest,
    TakeList,
    TakeMutationResult,
)
from reaper_mcp.services._bridge_result import (
    bridge_error,
    invalid_payload,
    validation_error,
)


class TakeService:
    """Expose GUID-addressed take selection and comping operations."""

    def __init__(self, bridge_client: BridgeClient) -> None:
        self.bridge_client = bridge_client

    async def list_item_takes(self, item_guid: str) -> dict[str, Any]:
        response = await self.bridge_client.execute(
            "list_item_takes", args={"item_guid": item_guid}
        )
        if not response.ok:
            return bridge_error(response)
        return self._parse_list(response)

    async def add_empty_take(
        self, item_guid: str, name: str = "Take"
    ) -> dict[str, Any]:
        try:
            request = AddEmptyTakeRequest(item_guid=item_guid, name=name)
        except ValidationError as exc:
            return self._validation_error(exc)
        return await self._mutate(
            "add_empty_take",
            request.model_dump(mode="json"),
            f"Add take: {request.name}",
        )

    async def set_active_take(self, take_guid: str) -> dict[str, Any]:
        return await self._take_guid_mutation(
            "set_active_take", take_guid, "Set active take"
        )

    async def rename_take(self, take_guid: str, name: str) -> dict[str, Any]:
        try:
            request = RenameTakeRequest(take_guid=take_guid, name=name)
        except ValidationError as exc:
            return self._validation_error(exc)
        return await self._mutate(
            "rename_take",
            request.model_dump(mode="json"),
            f"Rename take: {request.name}",
        )

    async def set_take_volume(self, take_guid: str, volume: float) -> dict[str, Any]:
        if volume < 0.0 or volume > 4.0:
            return self._property_range_error("volume", "0.0 and 4.0")
        return await self._set_property(take_guid, "volume", volume)

    async def set_take_pan(self, take_guid: str, pan: float) -> dict[str, Any]:
        if pan < -1.0 or pan > 1.0:
            return self._property_range_error("pan", "-1.0 and 1.0")
        return await self._set_property(take_guid, "pan", pan)

    async def set_take_pitch(self, take_guid: str, semitones: float) -> dict[str, Any]:
        if semitones < -80.0 or semitones > 80.0:
            return self._property_range_error("pitch", "-80 and 80 semitones")
        return await self._set_property(take_guid, "pitch_semitones", semitones)

    async def set_take_playback_rate(
        self,
        take_guid: str,
        playback_rate: float,
        preserve_pitch: bool = True,
    ) -> dict[str, Any]:
        if playback_rate < 0.05 or playback_rate > 8.0:
            return self._property_range_error("playback_rate", "0.05 and 8.0")
        return await self._set_property(
            take_guid,
            "playback_rate",
            playback_rate,
            preserve_pitch=preserve_pitch,
        )

    async def crop_to_active_take(
        self,
        item_guid: str,
        expected_active_take_guid: str,
        expected_take_count: int,
    ) -> dict[str, Any]:
        try:
            request = CropToActiveTakeRequest(
                item_guid=item_guid,
                expected_active_take_guid=expected_active_take_guid,
                expected_take_count=expected_take_count,
            )
        except ValidationError as exc:
            return self._validation_error(exc)
        return await self._mutate(
            "crop_to_active_take",
            request.model_dump(mode="json"),
            "Crop to active take",
        )

    async def _take_guid_mutation(
        self, command: str, take_guid: str, undo_label: str
    ) -> dict[str, Any]:
        try:
            request = TakeGuidRequest(take_guid=take_guid)
        except ValidationError as exc:
            return self._validation_error(exc)
        return await self._mutate(command, request.model_dump(mode="json"), undo_label)

    async def _set_property(
        self,
        take_guid: str,
        property_name: str,
        value: float,
        preserve_pitch: bool | None = None,
    ) -> dict[str, Any]:
        try:
            request = SetTakePropertyRequest(
                take_guid=take_guid,
                property=property_name,
                value=value,
                preserve_pitch=preserve_pitch,
            )
        except ValidationError as exc:
            return self._validation_error(exc)
        return await self._mutate(
            "set_take_property",
            request.model_dump(mode="json", exclude_none=True),
            f"Set take {property_name}",
        )

    async def _mutate(
        self, command: str, args: dict[str, Any], undo_label: str
    ) -> dict[str, Any]:
        response = await self.bridge_client.execute(
            command,
            args=args,
            options=CommandOptions(mutates_project=True, undo_label=undo_label),
        )
        if not response.ok:
            return bridge_error(response)
        try:
            result = TakeMutationResult.model_validate(response.result or {})
        except ValidationError as exc:
            return invalid_payload(response, exc, "take mutation")
        return {
            "ok": True,
            **result.model_dump(mode="json"),
            "warnings": response.warnings,
        }

    def _parse_list(self, response: Any) -> dict[str, Any]:
        try:
            result = TakeList.model_validate(response.result or {})
        except ValidationError as exc:
            return invalid_payload(response, exc, "take list")
        return {
            "ok": True,
            **result.model_dump(mode="json"),
            "warnings": response.warnings,
        }

    def _validation_error(self, exc: ValidationError) -> dict[str, Any]:
        return validation_error(
            exc,
            ErrorCode.INVALID_TAKE_REQUEST,
            "The take request is invalid.",
            "Refresh item takes and retry with current GUIDs and values.",
        )

    def _property_range_error(
        self, property_name: str, expected_range: str
    ) -> dict[str, Any]:
        return {
            "ok": False,
            "error": {
                "code": ErrorCode.INVALID_TAKE_REQUEST,
                "message": f"Take {property_name} is outside the supported range.",
                "details": {"expected_range": expected_range},
                "recoverable": True,
                "suggested_action": f"Use a {property_name} between {expected_range}.",
            },
            "warnings": [],
        }
