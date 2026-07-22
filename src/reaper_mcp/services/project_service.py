"""Project read service."""

from typing import Any

from pydantic import ValidationError

from reaper_mcp.bridge.base import BridgeClient
from reaper_mcp.errors import ErrorCode
from reaper_mcp.models.bridge import BridgeResponse, CommandOptions, ErrorResponse
from reaper_mcp.models.project import (
    CreateTrackRequest,
    CreateTrackResult,
    DeleteTrackResult,
    MasterTrackMutationResult,
    MasterTrackSnapshot,
    ProjectSnapshot,
    RenameTrackRequest,
    SetMasterMuteRequest,
    SetMasterPanRequest,
    SetMasterVolumeRequest,
    SetTrackArmRequest,
    SetTrackColorRequest,
    SetTrackMuteRequest,
    SetTrackPanRequest,
    SetTrackSoloRequest,
    SetTrackVolumeRequest,
    TrackGuidRequest,
    TrackList,
    TrackMutationResult,
)


class ProjectService:
    """Expose project and track operations."""

    def __init__(self, bridge_client: BridgeClient) -> None:
        self.bridge_client = bridge_client

    async def get_project_snapshot(self) -> dict[str, Any]:
        """Return a read-only snapshot of the active REAPER project."""

        response = await self.bridge_client.execute("get_project_snapshot")
        if not response.ok:
            return self._error_result(response)

        try:
            snapshot = ProjectSnapshot.model_validate(response.result or {})
        except ValidationError as exc:
            return self._invalid_payload_result(response, exc)

        return {
            "ok": True,
            "snapshot": snapshot.model_dump(mode="json"),
            "warnings": response.warnings,
        }

    async def list_tracks(self) -> dict[str, Any]:
        """Return a read-only list of tracks in REAPER UI order."""

        response = await self.bridge_client.execute("list_tracks")
        if not response.ok:
            return self._error_result(response)

        try:
            track_list = TrackList.model_validate(response.result or {})
        except ValidationError as exc:
            return self._invalid_payload_result(response, exc)

        return {
            "ok": True,
            "tracks": [track.model_dump(mode="json") for track in track_list.tracks],
            "track_count": track_list.track_count,
            "warnings": response.warnings,
        }

    async def create_track(
        self,
        name: str = "Track",
        index: int | None = None,
        color: int | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Create one track and return its stable REAPER GUID."""

        try:
            request = CreateTrackRequest(
                name=name,
                index=index,
                color=color,
                dry_run=dry_run,
            )
        except ValidationError as exc:
            return self._validation_error_result(exc)

        response = await self.bridge_client.execute(
            "create_track",
            args=request.model_dump(mode="json", exclude_none=True),
            options=CommandOptions(
                mutates_project=True,
                undo_label=None if request.dry_run else f"Create track: {request.name}",
                dry_run=request.dry_run,
            ),
        )
        if not response.ok:
            return self._error_result(response)

        try:
            result = CreateTrackResult.model_validate(response.result or {})
        except ValidationError as exc:
            return self._invalid_payload_result(response, exc)

        return {
            "ok": True,
            "track": result.track.model_dump(mode="json"),
            "track_count": result.track_count,
            "dry_run": result.dry_run,
            "changes_applied": result.changes_applied,
            "warnings": response.warnings,
        }

    async def rename_track(self, track_guid: str, name: str) -> dict[str, Any]:
        """Rename one track by stable REAPER GUID."""

        try:
            request = RenameTrackRequest(track_guid=track_guid, name=name)
        except ValidationError as exc:
            return self._validation_error_result(exc)
        return await self._execute_track_mutation(
            command="rename_track",
            args=request.model_dump(mode="json"),
            undo_label=f"Rename track: {request.name}",
        )

    async def set_track_color(self, track_guid: str, color: int) -> dict[str, Any]:
        """Set one track color by stable REAPER GUID."""

        try:
            request = SetTrackColorRequest(track_guid=track_guid, color=color)
        except ValidationError as exc:
            return self._validation_error_result(exc)
        return await self._execute_track_mutation(
            command="set_track_color",
            args=request.model_dump(mode="json"),
            undo_label="Set track color",
        )

    async def set_track_mute(self, track_guid: str, muted: bool) -> dict[str, Any]:
        """Set one track mute state by stable REAPER GUID."""

        try:
            request = SetTrackMuteRequest(track_guid=track_guid, muted=muted)
        except ValidationError as exc:
            return self._validation_error_result(exc)
        return await self._execute_track_mutation(
            command="set_track_mute",
            args=request.model_dump(mode="json"),
            undo_label="Set track mute",
        )

    async def set_track_solo(self, track_guid: str, soloed: bool) -> dict[str, Any]:
        """Set one track solo state by stable REAPER GUID."""

        try:
            request = SetTrackSoloRequest(track_guid=track_guid, soloed=soloed)
        except ValidationError as exc:
            return self._validation_error_result(exc)
        return await self._execute_track_mutation(
            command="set_track_solo",
            args=request.model_dump(mode="json"),
            undo_label="Set track solo",
        )

    async def set_track_arm(self, track_guid: str, armed: bool) -> dict[str, Any]:
        """Set one track record-arm state by stable REAPER GUID."""

        try:
            request = SetTrackArmRequest(track_guid=track_guid, armed=armed)
        except ValidationError as exc:
            return self._validation_error_result(exc)
        return await self._execute_track_mutation(
            command="set_track_arm",
            args=request.model_dump(mode="json"),
            undo_label="Set track record arm",
        )

    async def set_track_volume(self, track_guid: str, volume: float) -> dict[str, Any]:
        """Set one track's linear gain by stable REAPER GUID."""

        try:
            request = SetTrackVolumeRequest(track_guid=track_guid, volume=volume)
        except ValidationError as exc:
            return self._validation_error_result(exc)
        return await self._execute_track_mutation(
            command="set_track_volume",
            args=request.model_dump(mode="json"),
            undo_label="Set track volume",
        )

    async def set_track_pan(self, track_guid: str, pan: float) -> dict[str, Any]:
        """Set one track's pan by stable REAPER GUID."""

        try:
            request = SetTrackPanRequest(track_guid=track_guid, pan=pan)
        except ValidationError as exc:
            return self._validation_error_result(exc)
        return await self._execute_track_mutation(
            command="set_track_pan",
            args=request.model_dump(mode="json"),
            undo_label="Set track pan",
        )

    async def get_master_track(self) -> dict[str, Any]:
        """Return the current master track state."""

        response = await self.bridge_client.execute("get_master_track")
        if not response.ok:
            return self._error_result(response)
        try:
            master_track = MasterTrackSnapshot.model_validate(response.result or {})
        except ValidationError as exc:
            return self._invalid_payload_result(response, exc)
        return {
            "ok": True,
            "master_track": master_track.model_dump(mode="json"),
            "warnings": response.warnings,
        }

    async def set_master_volume(self, volume: float) -> dict[str, Any]:
        """Set the master track's linear gain."""

        try:
            request = SetMasterVolumeRequest(volume=volume)
        except ValidationError as exc:
            return self._validation_error_result(exc)
        return await self._execute_master_mutation(
            "set_master_volume",
            request.model_dump(mode="json"),
            "Set master volume",
        )

    async def set_master_pan(self, pan: float) -> dict[str, Any]:
        """Set the master track's pan."""

        try:
            request = SetMasterPanRequest(pan=pan)
        except ValidationError as exc:
            return self._validation_error_result(exc)
        return await self._execute_master_mutation(
            "set_master_pan",
            request.model_dump(mode="json"),
            "Set master pan",
        )

    async def set_master_mute(self, muted: bool) -> dict[str, Any]:
        """Set the master track's mute state explicitly."""

        request = SetMasterMuteRequest(muted=muted)
        return await self._execute_master_mutation(
            "set_master_mute",
            request.model_dump(mode="json"),
            "Set master mute",
        )

    async def delete_track(self, track_guid: str) -> dict[str, Any]:
        """Delete one track by stable REAPER GUID."""

        try:
            request = TrackGuidRequest(track_guid=track_guid)
        except ValidationError as exc:
            return self._validation_error_result(exc)

        response = await self.bridge_client.execute(
            "delete_track",
            args=request.model_dump(mode="json"),
            options=CommandOptions(
                mutates_project=True,
                undo_label="Delete track",
            ),
        )
        if not response.ok:
            return self._error_result(response)

        try:
            result = DeleteTrackResult.model_validate(response.result or {})
        except ValidationError as exc:
            return self._invalid_payload_result(response, exc)

        return {
            "ok": True,
            "deleted_track_guid": result.deleted_track_guid,
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

    async def _execute_track_mutation(
        self,
        command: str,
        args: dict[str, Any],
        undo_label: str,
    ) -> dict[str, Any]:
        response = await self.bridge_client.execute(
            command,
            args=args,
            options=CommandOptions(
                mutates_project=True,
                undo_label=undo_label,
            ),
        )
        if not response.ok:
            return self._error_result(response)

        try:
            result = TrackMutationResult.model_validate(response.result or {})
        except ValidationError as exc:
            return self._invalid_payload_result(response, exc)

        return {
            "ok": True,
            "track": result.track.model_dump(mode="json"),
            "track_count": result.track_count,
            "changes_applied": result.changes_applied,
            "warnings": response.warnings,
        }

    async def _execute_master_mutation(
        self,
        command: str,
        args: dict[str, Any],
        undo_label: str,
    ) -> dict[str, Any]:
        response = await self.bridge_client.execute(
            command,
            args=args,
            options=CommandOptions(mutates_project=True, undo_label=undo_label),
        )
        if not response.ok:
            return self._error_result(response)
        try:
            result = MasterTrackMutationResult.model_validate(response.result or {})
        except ValidationError as exc:
            return self._invalid_payload_result(response, exc)
        return {
            "ok": True,
            "master_track": result.master_track.model_dump(mode="json"),
            "changes_applied": result.changes_applied,
            "warnings": response.warnings,
        }

    def _invalid_payload_result(
        self, response: BridgeResponse, exc: ValidationError
    ) -> dict[str, Any]:
        return {
            "ok": False,
            "error": ErrorResponse(
                code=ErrorCode.INVALID_BRIDGE_RESPONSE,
                message="The REAPER Lua bridge returned an invalid project payload.",
                details={"errors": exc.errors()},
                recoverable=True,
                suggested_action="Restart the Lua bridge and retry the command.",
            ).model_dump(mode="json"),
            "warnings": response.warnings,
        }

    def _validation_error_result(self, exc: ValidationError) -> dict[str, Any]:
        return {
            "ok": False,
            "error": ErrorResponse(
                code=ErrorCode.INVALID_TRACK_REQUEST,
                message="The track request is invalid.",
                details={"errors": exc.errors()},
                recoverable=True,
                suggested_action="Check the track name, index, and color values.",
            ).model_dump(mode="json"),
            "warnings": [],
        }
