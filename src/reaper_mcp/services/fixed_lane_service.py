"""Guarded whole-lane operations for REAPER fixed-lane tracks."""

from typing import Any

from pydantic import ValidationError

from reaper_mcp.bridge.base import BridgeClient
from reaper_mcp.errors import ErrorCode
from reaper_mcp.models.bridge import CommandOptions
from reaper_mcp.models.fixed_lane import FixedLaneLayout, SelectFixedLaneRequest
from reaper_mcp.services._bridge_result import (
    bridge_error,
    invalid_payload,
    validation_error,
)


class FixedLaneService:
    """Inspect fixed lanes and select one complete lane for playback."""

    def __init__(self, bridge_client: BridgeClient) -> None:
        self.bridge_client = bridge_client

    async def list_fixed_lanes(self, track_guid: str) -> dict[str, Any]:
        response = await self.bridge_client.execute(
            "list_fixed_lanes", args={"track_guid": track_guid}
        )
        return self._parse(response, "fixed-lane layout")

    async def select_fixed_lane(
        self,
        track_guid: str,
        lane_index: int,
        expected_layout_fingerprint: str,
    ) -> dict[str, Any]:
        try:
            request = SelectFixedLaneRequest(
                track_guid=track_guid,
                lane_index=lane_index,
                expected_layout_fingerprint=expected_layout_fingerprint,
            )
        except ValidationError as exc:
            return validation_error(
                exc,
                ErrorCode.INVALID_FIXED_LANE_REQUEST,
                "The fixed-lane request is invalid.",
                "Refresh the fixed-lane layout and retry with its current fingerprint.",
            )
        response = await self.bridge_client.execute(
            "select_fixed_lane",
            args=request.model_dump(mode="json"),
            options=CommandOptions(
                mutates_project=True,
                undo_label=f"Select fixed lane {request.lane_index + 1}",
            ),
        )
        return self._parse(response, "fixed-lane mutation")

    @staticmethod
    def _parse(response: Any, payload_name: str) -> dict[str, Any]:
        if not response.ok:
            return bridge_error(response)
        try:
            result = FixedLaneLayout.model_validate(response.result or {})
        except ValidationError as exc:
            return invalid_payload(response, exc, payload_name)
        return {
            "ok": True,
            **result.model_dump(mode="json"),
            "warnings": response.warnings,
        }
