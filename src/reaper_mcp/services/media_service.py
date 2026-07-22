"""Media item service."""

from pathlib import Path
from typing import Any

from pydantic import ValidationError

from reaper_mcp.bridge.base import BridgeClient
from reaper_mcp.errors import ErrorCode
from reaper_mcp.models.bridge import BridgeResponse, CommandOptions, ErrorResponse
from reaper_mcp.models.media import (
    AddMidiNoteRequest,
    AddMidiNoteResult,
    AddMidiNotesRequest,
    AddMidiNotesResult,
    CreateMidiItemRequest,
    CreateMidiItemResult,
    DeleteMediaItemResult,
    DeleteMidiNotesRequest,
    DeleteMidiNotesResult,
    DuplicateMediaItemResult,
    InsertAudioItemRequest,
    InsertAudioItemResult,
    MediaItemGuidRequest,
    MediaItemList,
    MediaItemMutationResult,
    MidiNoteList,
    MoveMediaItemRequest,
    ResizeMediaItemRequest,
    SetMediaItemFadeRequest,
    SetMediaItemGainRequest,
    SetMediaItemMuteRequest,
    SplitMediaItemRequest,
    SplitMediaItemResult,
    UpdateMidiNoteRequest,
    UpdateMidiNoteResult,
)
from reaper_mcp.models.position import MusicalLength, MusicalPosition


class MediaService:
    """Expose media item operations."""

    def __init__(
        self,
        bridge_client: BridgeClient,
        allowed_media_source_roots: list[Path] | None = None,
    ) -> None:
        self.bridge_client = bridge_client
        self.allowed_media_source_roots = [
            root.expanduser().resolve() for root in (allowed_media_source_roots or [])
        ]

    async def list_media_items(self) -> dict[str, Any]:
        """Return media items in project order."""

        response = await self.bridge_client.execute("list_media_items")
        if not response.ok:
            return self._error_result(response)

        try:
            item_list = MediaItemList.model_validate(response.result or {})
        except ValidationError as exc:
            return self._invalid_payload_result(response, exc)

        return {
            "ok": True,
            "items": [item.model_dump(mode="json") for item in item_list.items],
            "item_count": item_list.item_count,
            "warnings": response.warnings,
        }

    async def create_midi_item(
        self,
        track_guid: str,
        measure: int = 1,
        beat: float = 1.0,
        length_beats: float = 4.0,
        name: str = "MIDI item",
    ) -> dict[str, Any]:
        """Create one empty MIDI item on a track."""

        try:
            request = CreateMidiItemRequest(
                track_guid=track_guid,
                start=MusicalPosition(measure=measure, beat=beat),
                length=MusicalLength(beats=length_beats),
                name=name,
            )
        except ValidationError as exc:
            return self._validation_error_result(exc)

        response = await self.bridge_client.execute(
            "create_midi_item",
            args=request.model_dump(mode="json"),
            options=CommandOptions(
                mutates_project=True,
                undo_label=f"Create MIDI item: {request.name}",
            ),
        )
        if not response.ok:
            return self._error_result(response)

        try:
            result = CreateMidiItemResult.model_validate(response.result or {})
        except ValidationError as exc:
            return self._invalid_payload_result(response, exc)

        return {
            "ok": True,
            "item": result.item.model_dump(mode="json"),
            "position": result.position.model_dump(mode="json"),
            "changes_applied": result.changes_applied,
            "warnings": response.warnings,
        }

    async def insert_audio_item(
        self,
        track_guid: str,
        source_path: str,
        measure: int = 1,
        beat: float = 1.0,
        name: str | None = None,
    ) -> dict[str, Any]:
        """Insert one local audio file as a media item on a track."""

        source = Path(source_path).expanduser()
        resolved_source = source.resolve(strict=False)
        if not self._is_allowed_media_source(resolved_source):
            return self._media_source_not_allowed_result(resolved_source)
        if not source.exists() or not source.is_file():
            return self._invalid_source_path_result(source)

        try:
            request = InsertAudioItemRequest(
                track_guid=track_guid,
                source_path=str(resolved_source),
                start=MusicalPosition(measure=measure, beat=beat),
                name=name,
            )
        except ValidationError as exc:
            return self._validation_error_result(exc)

        response = await self.bridge_client.execute(
            "insert_audio_item",
            args=request.model_dump(mode="json", exclude_none=True),
            options=CommandOptions(
                mutates_project=True,
                undo_label="Insert audio item",
            ),
        )
        if not response.ok:
            return self._error_result(response)

        try:
            result = InsertAudioItemResult.model_validate(response.result or {})
        except ValidationError as exc:
            return self._invalid_payload_result(response, exc)

        return {
            "ok": True,
            "item": result.item.model_dump(mode="json"),
            "position": result.position.model_dump(mode="json"),
            "changes_applied": result.changes_applied,
            "warnings": response.warnings,
        }

    async def move_media_item(
        self,
        item_guid: str,
        measure: int,
        beat: float = 1.0,
    ) -> dict[str, Any]:
        """Move one media item by stable GUID to a musical position."""

        try:
            request = MoveMediaItemRequest(
                item_guid=item_guid,
                start=MusicalPosition(measure=measure, beat=beat),
            )
        except ValidationError as exc:
            return self._validation_error_result(exc)
        return await self._execute_item_mutation(
            "move_media_item",
            request.model_dump(mode="json"),
            "Move media item",
        )

    async def resize_media_item(
        self,
        item_guid: str,
        length_beats: float,
    ) -> dict[str, Any]:
        """Set one media item's length in beats by stable GUID."""

        try:
            request = ResizeMediaItemRequest(
                item_guid=item_guid,
                length=MusicalLength(beats=length_beats),
            )
        except ValidationError as exc:
            return self._validation_error_result(exc)
        return await self._execute_item_mutation(
            "resize_media_item",
            request.model_dump(mode="json"),
            "Resize media item",
        )

    async def duplicate_media_item(self, item_guid: str) -> dict[str, Any]:
        """Duplicate one media item by stable GUID."""

        try:
            request = MediaItemGuidRequest(item_guid=item_guid)
        except ValidationError as exc:
            return self._validation_error_result(exc)
        response = await self.bridge_client.execute(
            "duplicate_media_item",
            args=request.model_dump(mode="json"),
            options=CommandOptions(
                mutates_project=True,
                undo_label="Duplicate media item",
            ),
        )
        if not response.ok:
            return self._error_result(response)
        try:
            result = DuplicateMediaItemResult.model_validate(response.result or {})
        except ValidationError as exc:
            return self._invalid_payload_result(response, exc)
        return {
            "ok": True,
            "source_item_guid": result.source_item_guid,
            "item": result.item.model_dump(mode="json"),
            "selection_restored": result.selection_restored,
            "changes_applied": result.changes_applied,
            "warnings": response.warnings,
        }

    async def split_media_item(
        self,
        item_guid: str,
        measure: int,
        beat: float = 1.0,
    ) -> dict[str, Any]:
        """Split one media item by stable GUID at a musical position."""

        try:
            request = SplitMediaItemRequest(
                item_guid=item_guid,
                split_at=MusicalPosition(measure=measure, beat=beat),
            )
        except ValidationError as exc:
            return self._validation_error_result(exc)
        response = await self.bridge_client.execute(
            "split_media_item",
            args=request.model_dump(mode="json"),
            options=CommandOptions(
                mutates_project=True,
                undo_label="Split media item",
            ),
        )
        if not response.ok:
            return self._error_result(response)
        try:
            result = SplitMediaItemResult.model_validate(response.result or {})
        except ValidationError as exc:
            return self._invalid_payload_result(response, exc)
        return {
            "ok": True,
            "left_item": result.left_item.model_dump(mode="json"),
            "right_item": result.right_item.model_dump(mode="json"),
            "changes_applied": result.changes_applied,
            "warnings": response.warnings,
        }

    async def set_media_item_mute(self, item_guid: str, muted: bool) -> dict[str, Any]:
        """Set one media item's mute state by stable GUID."""

        try:
            request = SetMediaItemMuteRequest(item_guid=item_guid, muted=muted)
        except ValidationError as exc:
            return self._validation_error_result(exc)
        return await self._execute_item_mutation(
            "set_media_item_mute",
            request.model_dump(mode="json"),
            "Set media item mute",
        )

    async def set_media_item_gain(self, item_guid: str, gain: float) -> dict[str, Any]:
        """Set one media item's linear gain by stable GUID."""

        try:
            request = SetMediaItemGainRequest(item_guid=item_guid, gain=gain)
        except ValidationError as exc:
            return self._validation_error_result(exc)
        return await self._execute_item_mutation(
            "set_media_item_gain",
            request.model_dump(mode="json"),
            "Set media item gain",
        )

    async def set_media_item_fade_in(
        self, item_guid: str, length_seconds: float
    ) -> dict[str, Any]:
        """Set one media item's manual fade-in length by stable GUID."""

        return await self._set_media_item_fade(
            "set_media_item_fade_in",
            item_guid,
            length_seconds,
            "Set media item fade in",
        )

    async def set_media_item_fade_out(
        self, item_guid: str, length_seconds: float
    ) -> dict[str, Any]:
        """Set one media item's manual fade-out length by stable GUID."""

        return await self._set_media_item_fade(
            "set_media_item_fade_out",
            item_guid,
            length_seconds,
            "Set media item fade out",
        )

    async def delete_media_item(self, item_guid: str) -> dict[str, Any]:
        """Delete one media item by stable GUID."""

        try:
            request = MediaItemGuidRequest(item_guid=item_guid)
        except ValidationError as exc:
            return self._validation_error_result(exc)
        response = await self.bridge_client.execute(
            "delete_media_item",
            args=request.model_dump(mode="json"),
            options=CommandOptions(
                mutates_project=True,
                undo_label="Delete media item",
            ),
        )
        if not response.ok:
            return self._error_result(response)
        try:
            result = DeleteMediaItemResult.model_validate(response.result or {})
        except ValidationError as exc:
            return self._invalid_payload_result(response, exc)
        return {
            "ok": True,
            "deleted_item_guid": result.deleted_item_guid,
            "item_count": result.item_count,
            "changes_applied": result.changes_applied,
            "warnings": response.warnings,
        }

    async def get_midi_notes(self, take_guid: str) -> dict[str, Any]:
        """Return MIDI notes in one take."""

        response = await self.bridge_client.execute(
            "get_midi_notes",
            args={"take_guid": take_guid},
        )
        if not response.ok:
            return self._error_result(response)

        try:
            note_list = MidiNoteList.model_validate(response.result or {})
        except ValidationError as exc:
            return self._invalid_payload_result(response, exc)

        return {
            "ok": True,
            "take_guid": note_list.take_guid,
            "notes": [note.model_dump(mode="json") for note in note_list.notes],
            "note_count": note_list.note_count,
            "warnings": response.warnings,
        }

    async def add_midi_note(
        self,
        take_guid: str,
        note: dict[str, Any],
    ) -> dict[str, Any]:
        """Insert one MIDI note and return the inserted note plus take notes."""

        try:
            request = AddMidiNoteRequest(take_guid=take_guid, note=note)
        except ValidationError as exc:
            return self._midi_validation_error_result(exc)

        response = await self.bridge_client.execute(
            "add_midi_notes",
            args={
                "take_guid": request.take_guid,
                "notes": [request.note.model_dump(mode="json")],
            },
            options=CommandOptions(
                mutates_project=True,
                undo_label="Add MIDI note",
            ),
        )
        if not response.ok:
            return self._error_result(response)

        try:
            batch_result = AddMidiNotesResult.model_validate(response.result or {})
        except ValidationError as exc:
            return self._invalid_payload_result(response, exc)

        if len(batch_result.inserted_notes) != 1:
            return self._invalid_payload_message_result(
                response,
                "The Lua bridge did not return exactly one inserted MIDI note.",
            )

        try:
            result = AddMidiNoteResult.model_validate(
                {
                    "take_guid": batch_result.take_guid,
                    "inserted_note": batch_result.inserted_notes[0],
                    "notes": batch_result.notes,
                    "note_count": batch_result.note_count,
                    "changes_applied": batch_result.changes_applied,
                }
            )
        except ValidationError as exc:
            return self._invalid_payload_result(response, exc)

        return {
            "ok": True,
            "take_guid": result.take_guid,
            "inserted_note": result.inserted_note.model_dump(mode="json"),
            "notes": [note.model_dump(mode="json") for note in result.notes],
            "note_count": result.note_count,
            "changes_applied": result.changes_applied,
            "warnings": response.warnings,
        }

    async def add_midi_notes(
        self,
        take_guid: str,
        notes: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Insert MIDI notes in one batch and return the take notes."""

        try:
            request = AddMidiNotesRequest(take_guid=take_guid, notes=notes)
        except ValidationError as exc:
            return self._midi_validation_error_result(exc)

        response = await self.bridge_client.execute(
            "add_midi_notes",
            args=request.model_dump(mode="json"),
            options=CommandOptions(
                mutates_project=True,
                undo_label=f"Add {len(request.notes)} MIDI notes",
            ),
        )
        if not response.ok:
            return self._error_result(response)

        try:
            result = AddMidiNotesResult.model_validate(response.result or {})
        except ValidationError as exc:
            return self._invalid_payload_result(response, exc)

        return {
            "ok": True,
            "take_guid": result.take_guid,
            "inserted_notes": [
                note.model_dump(mode="json") for note in result.inserted_notes
            ],
            "notes": [note.model_dump(mode="json") for note in result.notes],
            "note_count": result.note_count,
            "inserted_count": result.inserted_count,
            "changes_applied": result.changes_applied,
            "warnings": response.warnings,
        }

    async def update_midi_note(
        self,
        take_guid: str,
        note_index: int,
        expected_fingerprint: str,
        note: dict[str, Any],
    ) -> dict[str, Any]:
        """Replace one MIDI note after checking its fingerprint."""

        try:
            request = UpdateMidiNoteRequest(
                take_guid=take_guid,
                note_identity={
                    "index": note_index,
                    "expected_fingerprint": expected_fingerprint,
                },
                note=note,
            )
        except ValidationError as exc:
            return self._midi_validation_error_result(exc)

        response = await self.bridge_client.execute(
            "update_midi_note",
            args=request.model_dump(mode="json"),
            options=CommandOptions(
                mutates_project=True,
                undo_label="Update MIDI note",
            ),
        )
        if not response.ok:
            return self._error_result(response)

        try:
            result = UpdateMidiNoteResult.model_validate(response.result or {})
        except ValidationError as exc:
            return self._invalid_payload_result(response, exc)

        return {
            "ok": True,
            "take_guid": result.take_guid,
            "updated_note": result.updated_note.model_dump(mode="json"),
            "notes": [note.model_dump(mode="json") for note in result.notes],
            "note_count": result.note_count,
            "changes_applied": result.changes_applied,
            "warnings": response.warnings,
        }

    async def delete_midi_notes(
        self,
        take_guid: str,
        notes: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Delete MIDI notes after checking each fingerprint."""

        try:
            request = DeleteMidiNotesRequest(take_guid=take_guid, notes=notes)
        except ValidationError as exc:
            return self._midi_validation_error_result(exc)

        response = await self.bridge_client.execute(
            "delete_midi_notes",
            args=request.model_dump(mode="json"),
            options=CommandOptions(
                mutates_project=True,
                undo_label=f"Delete {len(request.notes)} MIDI notes",
            ),
        )
        if not response.ok:
            return self._error_result(response)

        try:
            result = DeleteMidiNotesResult.model_validate(response.result or {})
        except ValidationError as exc:
            return self._invalid_payload_result(response, exc)

        return {
            "ok": True,
            "take_guid": result.take_guid,
            "notes": [note.model_dump(mode="json") for note in result.notes],
            "note_count": result.note_count,
            "deleted_count": result.deleted_count,
            "changes_applied": result.changes_applied,
            "warnings": response.warnings,
        }

    def _error_result(self, response: BridgeResponse) -> dict[str, Any]:
        return {
            "ok": False,
            "error": response.error.model_dump(mode="json") if response.error else None,
            "warnings": response.warnings,
        }

    async def _execute_item_mutation(
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
            result = MediaItemMutationResult.model_validate(response.result or {})
        except ValidationError as exc:
            return self._invalid_payload_result(response, exc)
        return {
            "ok": True,
            "item": result.item.model_dump(mode="json"),
            "changes_applied": result.changes_applied,
            "warnings": response.warnings,
        }

    async def _set_media_item_fade(
        self,
        command: str,
        item_guid: str,
        length_seconds: float,
        undo_label: str,
    ) -> dict[str, Any]:
        try:
            request = SetMediaItemFadeRequest(
                item_guid=item_guid,
                length_seconds=length_seconds,
            )
        except ValidationError as exc:
            return self._validation_error_result(exc)
        return await self._execute_item_mutation(
            command,
            request.model_dump(mode="json"),
            undo_label,
        )

    def _invalid_payload_result(
        self, response: BridgeResponse, exc: ValidationError
    ) -> dict[str, Any]:
        return {
            "ok": False,
            "error": ErrorResponse(
                code=ErrorCode.INVALID_BRIDGE_RESPONSE,
                message="The Lua bridge returned an invalid media payload.",
                details={"errors": self._json_safe_validation_errors(exc)},
                recoverable=True,
                suggested_action="Restart the Lua bridge and retry the command.",
            ).model_dump(mode="json"),
            "warnings": response.warnings,
        }

    def _invalid_payload_message_result(
        self, response: BridgeResponse, message: str
    ) -> dict[str, Any]:
        return {
            "ok": False,
            "error": ErrorResponse(
                code=ErrorCode.INVALID_BRIDGE_RESPONSE,
                message=message,
                details={"response_id": response.id},
                recoverable=True,
                suggested_action="Restart the Lua bridge and retry the command.",
            ).model_dump(mode="json"),
            "warnings": response.warnings,
        }

    def _validation_error_result(self, exc: ValidationError) -> dict[str, Any]:
        return {
            "ok": False,
            "error": ErrorResponse(
                code=ErrorCode.INVALID_MEDIA_ITEM_REQUEST,
                message="The media item request is invalid.",
                details={"errors": self._json_safe_validation_errors(exc)},
                recoverable=True,
                suggested_action="Check the track GUID and musical position values.",
            ).model_dump(mode="json"),
            "warnings": [],
        }

    def _invalid_source_path_result(self, source_path: Path) -> dict[str, Any]:
        return {
            "ok": False,
            "error": ErrorResponse(
                code=ErrorCode.INVALID_MEDIA_ITEM_REQUEST,
                message="The audio source path is invalid.",
                details={"source_path": str(source_path)},
                recoverable=True,
                suggested_action="Provide an existing local audio file path.",
            ).model_dump(mode="json"),
            "warnings": [],
        }

    def _media_source_not_allowed_result(self, source_path: Path) -> dict[str, Any]:
        return {
            "ok": False,
            "error": ErrorResponse(
                code=ErrorCode.MEDIA_SOURCE_NOT_ALLOWED,
                message="The audio source path is outside the allowed media roots.",
                details={
                    "source_path": str(source_path),
                    "allowed_media_source_roots": [
                        str(root) for root in self.allowed_media_source_roots
                    ],
                },
                recoverable=True,
                suggested_action=(
                    "Set REAPER_MCP_ALLOWED_MEDIA_SOURCE_ROOTS to include the "
                    "directory that contains the audio source."
                ),
            ).model_dump(mode="json"),
            "warnings": [],
        }

    def _midi_validation_error_result(self, exc: ValidationError) -> dict[str, Any]:
        return {
            "ok": False,
            "error": ErrorResponse(
                code=ErrorCode.INVALID_MIDI_NOTE_REQUEST,
                message="The MIDI note request is invalid.",
                details={"errors": self._json_safe_validation_errors(exc)},
                recoverable=True,
                suggested_action="Check the take GUID and MIDI note values.",
            ).model_dump(mode="json"),
            "warnings": [],
        }

    def _json_safe_validation_errors(
        self, exc: ValidationError
    ) -> list[dict[str, Any]]:
        return exc.errors(include_context=False)

    def _is_allowed_media_source(self, source_path: Path) -> bool:
        return any(
            source_path == root or source_path.is_relative_to(root)
            for root in self.allowed_media_source_roots
        )
