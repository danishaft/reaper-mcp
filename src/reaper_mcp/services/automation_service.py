"""Track automation envelope service."""

from typing import Any

from pydantic import ValidationError

from reaper_mcp.bridge.base import BridgeClient
from reaper_mcp.errors import ErrorCode
from reaper_mcp.models.automation import (
    AddEnvelopePointsRequest,
    AutomationMode,
    DeleteEnvelopePointRangeRequest,
    DeleteEnvelopePointsRequest,
    EnsureEnvelopeResult,
    EnvelopeIdentity,
    EnvelopeList,
    EnvelopePointList,
    EnvelopeType,
    SetTrackAutomationModeRequest,
    TrackAutomationModeResult,
    UpdateEnvelopePointRequest,
)
from reaper_mcp.models.bridge import CommandOptions
from reaper_mcp.services._bridge_result import (
    bridge_error,
    invalid_payload,
    validation_error,
)


class AutomationService:
    """Expose guarded track automation operations."""

    def __init__(self, bridge_client: BridgeClient) -> None:
        self.bridge_client = bridge_client

    async def list_track_envelopes(self, track_guid: str) -> dict[str, Any]:
        response = await self.bridge_client.execute(
            "list_track_envelopes", args={"track_guid": track_guid}
        )
        if not response.ok:
            return bridge_error(response)
        try:
            result = EnvelopeList.model_validate(response.result or {})
        except ValidationError as exc:
            return invalid_payload(response, exc, "automation envelope")
        return {
            "ok": True,
            **result.model_dump(mode="json"),
            "warnings": response.warnings,
        }

    async def ensure_track_envelope(
        self, track_guid: str, envelope_type: EnvelopeType
    ) -> dict[str, Any]:
        response = await self.bridge_client.execute(
            "ensure_track_envelope",
            args={"track_guid": track_guid, "envelope_type": envelope_type},
            options=CommandOptions(
                mutates_project=True,
                undo_label=f"Ensure track envelope: {envelope_type}",
            ),
        )
        if not response.ok:
            return bridge_error(response)
        try:
            result = EnsureEnvelopeResult.model_validate(response.result or {})
        except ValidationError as exc:
            return invalid_payload(response, exc, "ensured track envelope")
        return {
            "ok": True,
            **result.model_dump(mode="json"),
            "warnings": response.warnings,
        }

    async def get_envelope_points(
        self, track_guid: str, envelope_guid: str
    ) -> dict[str, Any]:
        try:
            identity = EnvelopeIdentity(
                track_guid=track_guid, envelope_guid=envelope_guid
            )
        except ValidationError as exc:
            return self._validation_error(exc)
        return await self._execute_point_read(identity)

    async def add_envelope_points(
        self,
        track_guid: str,
        envelope_guid: str,
        points: list[dict[str, Any]],
    ) -> dict[str, Any]:
        try:
            request = AddEnvelopePointsRequest(
                envelope_identity={
                    "track_guid": track_guid,
                    "envelope_guid": envelope_guid,
                },
                points=points,
            )
        except ValidationError as exc:
            return self._validation_error(exc)
        return await self._execute_point_mutation(
            "add_envelope_points",
            request.model_dump(mode="json"),
            f"Add {len(request.points)} envelope points",
        )

    async def update_envelope_point(
        self,
        track_guid: str,
        envelope_guid: str,
        point_index: int,
        expected_fingerprint: str,
        *,
        time_seconds: float | None = None,
        value: float | None = None,
        shape: int | None = None,
        tension: float | None = None,
        selected: bool | None = None,
    ) -> dict[str, Any]:
        try:
            request = UpdateEnvelopePointRequest(
                envelope_identity={
                    "track_guid": track_guid,
                    "envelope_guid": envelope_guid,
                },
                point_identity={
                    "index": point_index,
                    "expected_fingerprint": expected_fingerprint,
                },
                time_seconds=time_seconds,
                value=value,
                shape=shape,
                tension=tension,
                selected=selected,
            )
        except ValidationError as exc:
            return self._validation_error(exc)
        return await self._execute_point_mutation(
            "update_envelope_point",
            request.model_dump(mode="json", exclude_none=True),
            "Update envelope point",
        )

    async def delete_envelope_points(
        self,
        track_guid: str,
        envelope_guid: str,
        points: list[dict[str, Any]],
    ) -> dict[str, Any]:
        try:
            request = DeleteEnvelopePointsRequest(
                envelope_identity={
                    "track_guid": track_guid,
                    "envelope_guid": envelope_guid,
                },
                points=points,
            )
        except ValidationError as exc:
            return self._validation_error(exc)
        return await self._execute_point_mutation(
            "delete_envelope_points",
            request.model_dump(mode="json"),
            f"Delete {len(request.points)} envelope points",
        )

    async def delete_envelope_points_in_range(
        self,
        track_guid: str,
        envelope_guid: str,
        start_seconds: float,
        end_seconds: float,
    ) -> dict[str, Any]:
        try:
            request = DeleteEnvelopePointRangeRequest(
                envelope_identity={
                    "track_guid": track_guid,
                    "envelope_guid": envelope_guid,
                },
                start_seconds=start_seconds,
                end_seconds=end_seconds,
            )
        except ValidationError as exc:
            return self._validation_error(exc)
        return await self._execute_point_mutation(
            "delete_envelope_points_in_range",
            request.model_dump(mode="json"),
            "Delete envelope points in range",
        )

    async def get_track_automation_mode(self, track_guid: str) -> dict[str, Any]:
        response = await self.bridge_client.execute(
            "get_track_automation_mode", args={"track_guid": track_guid}
        )
        if not response.ok:
            return bridge_error(response)
        return self._parse_mode(response)

    async def set_track_automation_mode(
        self, track_guid: str, mode: AutomationMode
    ) -> dict[str, Any]:
        try:
            request = SetTrackAutomationModeRequest(track_guid=track_guid, mode=mode)
        except ValidationError as exc:
            return self._validation_error(exc)
        response = await self.bridge_client.execute(
            "set_track_automation_mode",
            args={"track_guid": request.track_guid, "mode": request.mode},
            options=CommandOptions(
                mutates_project=True,
                undo_label=f"Set track automation mode: {request.mode}",
            ),
        )
        if not response.ok:
            return bridge_error(response)
        return self._parse_mode(response)

    async def _execute_point_read(self, identity: EnvelopeIdentity) -> dict[str, Any]:
        response = await self.bridge_client.execute(
            "get_envelope_points",
            args={"envelope_identity": identity.model_dump(mode="json")},
        )
        if not response.ok:
            return bridge_error(response)
        return self._parse_points(response)

    async def _execute_point_mutation(
        self, command: str, args: dict[str, Any], undo_label: str
    ) -> dict[str, Any]:
        response = await self.bridge_client.execute(
            command,
            args=args,
            options=CommandOptions(mutates_project=True, undo_label=undo_label),
        )
        if not response.ok:
            return bridge_error(response)
        return self._parse_points(response)

    def _parse_points(self, response: Any) -> dict[str, Any]:
        try:
            result = EnvelopePointList.model_validate(response.result or {})
        except ValidationError as exc:
            return invalid_payload(response, exc, "automation point")
        return {
            "ok": True,
            **result.model_dump(mode="json"),
            "warnings": response.warnings,
        }

    def _parse_mode(self, response: Any) -> dict[str, Any]:
        try:
            result = TrackAutomationModeResult.model_validate(response.result or {})
        except ValidationError as exc:
            return invalid_payload(response, exc, "automation mode")
        return {
            "ok": True,
            **result.model_dump(mode="json"),
            "warnings": response.warnings,
        }

    def _validation_error(self, exc: ValidationError) -> dict[str, Any]:
        return validation_error(
            exc,
            ErrorCode.INVALID_AUTOMATION_REQUEST,
            "The automation request is invalid.",
            "Refresh envelope state and check point values and identities.",
        )
