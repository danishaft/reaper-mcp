"""Marker and region service."""

from typing import Any

from pydantic import ValidationError

from reaper_mcp.bridge.base import BridgeClient
from reaper_mcp.errors import ErrorCode
from reaper_mcp.models.arrangement import (
    CreateMarkerRequest,
    CreateMarkerResult,
    CreateRegionRequest,
    CreateRegionResult,
    DeleteMarkerRequest,
    DeleteMarkerResult,
    DeleteRegionRequest,
    DeleteRegionResult,
    MarkerIdentity,
    MarkerList,
    RegionIdentity,
    RegionList,
)
from reaper_mcp.models.bridge import BridgeResponse, CommandOptions, ErrorResponse


class ArrangementService:
    """Expose marker and region operations."""

    def __init__(self, bridge_client: BridgeClient) -> None:
        self.bridge_client = bridge_client

    async def list_markers(self) -> dict[str, Any]:
        """Return project markers in timeline order."""

        response = await self.bridge_client.execute("list_markers")
        if not response.ok:
            return self._error_result(response)

        try:
            result = MarkerList.model_validate(response.result or {})
        except ValidationError as exc:
            return self._invalid_payload_result(response, exc)

        return {
            "ok": True,
            "markers": [marker.model_dump(mode="json") for marker in result.markers],
            "marker_count": result.marker_count,
            "warnings": response.warnings,
        }

    async def create_marker(
        self,
        start_seconds: float,
        name: str = "",
        color: int = 0,
    ) -> dict[str, Any]:
        """Create one marker and return its REAPER marker ID."""

        try:
            request = CreateMarkerRequest(
                name=name,
                start_seconds=start_seconds,
                color=color,
            )
        except ValidationError as exc:
            return self._validation_error_result(exc, ErrorCode.INVALID_MARKER_REQUEST)

        response = await self.bridge_client.execute(
            "create_marker",
            args=request.model_dump(mode="json"),
            options=CommandOptions(
                mutates_project=True,
                undo_label=f"Create marker: {request.name or request.start_seconds}",
            ),
        )
        if not response.ok:
            return self._error_result(response)

        try:
            result = CreateMarkerResult.model_validate(response.result or {})
        except ValidationError as exc:
            return self._invalid_payload_result(response, exc)

        return {
            "ok": True,
            "marker": result.marker.model_dump(mode="json"),
            "markers": [marker.model_dump(mode="json") for marker in result.markers],
            "marker_count": result.marker_count,
            "changes_applied": result.changes_applied,
            "warnings": response.warnings,
        }

    async def delete_marker(
        self,
        marker_id: int,
        expected_name: str | None = None,
        expected_start_seconds: float | None = None,
    ) -> dict[str, Any]:
        """Delete one marker after checking its guarded identity."""

        try:
            request = DeleteMarkerRequest(
                marker_identity=MarkerIdentity(
                    id=marker_id,
                    expected_name=expected_name,
                    expected_start_seconds=expected_start_seconds,
                )
            )
        except ValidationError as exc:
            return self._validation_error_result(exc, ErrorCode.INVALID_MARKER_REQUEST)

        response = await self.bridge_client.execute(
            "delete_marker",
            args=request.model_dump(mode="json", exclude_none=True),
            options=CommandOptions(
                mutates_project=True,
                undo_label=f"Delete marker: {request.marker_identity.id}",
            ),
        )
        if not response.ok:
            return self._error_result(response)

        try:
            result = DeleteMarkerResult.model_validate(response.result or {})
        except ValidationError as exc:
            return self._invalid_payload_result(response, exc)

        return {
            "ok": True,
            "deleted_marker_id": result.deleted_marker_id,
            "markers": [marker.model_dump(mode="json") for marker in result.markers],
            "marker_count": result.marker_count,
            "changes_applied": result.changes_applied,
            "warnings": response.warnings,
        }

    async def list_regions(self) -> dict[str, Any]:
        """Return project regions in timeline order."""

        response = await self.bridge_client.execute("list_regions")
        if not response.ok:
            return self._error_result(response)

        try:
            result = RegionList.model_validate(response.result or {})
        except ValidationError as exc:
            return self._invalid_payload_result(response, exc)

        return {
            "ok": True,
            "regions": [region.model_dump(mode="json") for region in result.regions],
            "region_count": result.region_count,
            "warnings": response.warnings,
        }

    async def create_region(
        self,
        start_seconds: float,
        end_seconds: float,
        name: str = "",
        color: int = 0,
    ) -> dict[str, Any]:
        """Create one region and return its REAPER region ID."""

        try:
            request = CreateRegionRequest(
                name=name,
                start_seconds=start_seconds,
                end_seconds=end_seconds,
                color=color,
            )
        except ValidationError as exc:
            return self._validation_error_result(exc, ErrorCode.INVALID_REGION_REQUEST)

        response = await self.bridge_client.execute(
            "create_region",
            args=request.model_dump(mode="json"),
            options=CommandOptions(
                mutates_project=True,
                undo_label=f"Create region: {request.name or request.start_seconds}",
            ),
        )
        if not response.ok:
            return self._error_result(response)

        try:
            result = CreateRegionResult.model_validate(response.result or {})
        except ValidationError as exc:
            return self._invalid_payload_result(response, exc)

        return {
            "ok": True,
            "region": result.region.model_dump(mode="json"),
            "regions": [region.model_dump(mode="json") for region in result.regions],
            "region_count": result.region_count,
            "changes_applied": result.changes_applied,
            "warnings": response.warnings,
        }

    async def delete_region(
        self,
        region_id: int,
        expected_name: str | None = None,
        expected_start_seconds: float | None = None,
        expected_end_seconds: float | None = None,
    ) -> dict[str, Any]:
        """Delete one region after checking its guarded identity."""

        try:
            request = DeleteRegionRequest(
                region_identity=RegionIdentity(
                    id=region_id,
                    expected_name=expected_name,
                    expected_start_seconds=expected_start_seconds,
                    expected_end_seconds=expected_end_seconds,
                )
            )
        except ValidationError as exc:
            return self._validation_error_result(exc, ErrorCode.INVALID_REGION_REQUEST)

        response = await self.bridge_client.execute(
            "delete_region",
            args=request.model_dump(mode="json", exclude_none=True),
            options=CommandOptions(
                mutates_project=True,
                undo_label=f"Delete region: {request.region_identity.id}",
            ),
        )
        if not response.ok:
            return self._error_result(response)

        try:
            result = DeleteRegionResult.model_validate(response.result or {})
        except ValidationError as exc:
            return self._invalid_payload_result(response, exc)

        return {
            "ok": True,
            "deleted_region_id": result.deleted_region_id,
            "regions": [region.model_dump(mode="json") for region in result.regions],
            "region_count": result.region_count,
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
                message="The Lua bridge returned an invalid arrangement payload.",
                details={"errors": exc.errors(include_context=False)},
                recoverable=True,
                suggested_action="Restart the Lua bridge and retry the command.",
            ).model_dump(mode="json"),
            "warnings": response.warnings,
        }

    def _validation_error_result(
        self,
        exc: ValidationError,
        code: ErrorCode,
    ) -> dict[str, Any]:
        return {
            "ok": False,
            "error": ErrorResponse(
                code=code,
                message="The marker or region request is invalid.",
                details={"errors": exc.errors(include_context=False)},
                recoverable=True,
                suggested_action="Check IDs, names, colors, and timeline positions.",
            ).model_dump(mode="json"),
            "warnings": [],
        }
