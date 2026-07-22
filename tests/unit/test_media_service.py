from pathlib import Path

from reaper_mcp.models.bridge import BridgeResponse, CommandOptions
from reaper_mcp.services.media_service import MediaService


class FakeBridgeClient:
    def __init__(self, response: BridgeResponse) -> None:
        self.response = response
        self.command: str | None = None
        self.args: dict | None = None
        self.options: CommandOptions | None = None

    async def execute(
        self,
        command: str,
        args: dict | None = None,
        options: CommandOptions | None = None,
    ) -> BridgeResponse:
        self.command = command
        self.args = args
        self.options = options
        return self.response


def item_payload() -> dict:
    return {
        "guid": "{ITEM-GUID}",
        "track_guid": "{TRACK-GUID}",
        "name": "Verse MIDI",
        "position_seconds": 0.0,
        "length_seconds": 2.0,
        "start_qn": 0.0,
        "end_qn": 4.0,
        "take_count": 1,
        "active_take": {
            "guid": "{TAKE-GUID}",
            "name": "Verse MIDI",
            "is_midi": True,
        },
    }


def note_payload(
    index: int = 0,
    fingerprint: str = "0:0:0:960:0:60:96",
    pitch: int = 60,
    channel: int = 0,
    velocity: int = 96,
    start_ppq: float = 0.0,
    end_ppq: float = 960.0,
    start_qn: float = 0.0,
    end_qn: float = 1.0,
) -> dict:
    return {
        "index": index,
        "fingerprint": fingerprint,
        "start_ppq": start_ppq,
        "end_ppq": end_ppq,
        "start_qn": start_qn,
        "end_qn": end_qn,
        "channel": channel,
        "pitch": pitch,
        "velocity": velocity,
    }


async def test_media_service_lists_media_items() -> None:
    bridge = FakeBridgeClient(
        BridgeResponse(
            id="request-1",
            ok=True,
            result={"items": [item_payload()], "item_count": 1},
        )
    )
    service = MediaService(bridge)

    result = await service.list_media_items()

    assert bridge.command == "list_media_items"
    assert result["ok"] is True
    assert result["items"][0]["guid"] == "{ITEM-GUID}"


async def test_media_service_creates_midi_item_with_undo_options() -> None:
    bridge = FakeBridgeClient(
        BridgeResponse(
            id="request-1",
            ok=True,
            result={
                "item": item_payload(),
                "position": {
                    "start": {"measure": 1, "beat": 1.0},
                    "length": {"beats": 4.0},
                    "start_qn": 0.0,
                    "end_qn": 4.0,
                    "start_seconds": 0.0,
                    "end_seconds": 2.0,
                    "start_ppq": 0.0,
                    "end_ppq": 3840.0,
                },
            },
        )
    )
    service = MediaService(bridge)

    result = await service.create_midi_item(
        track_guid="{TRACK-GUID}",
        measure=1,
        beat=1,
        length_beats=4,
        name="Verse MIDI",
    )

    assert bridge.command == "create_midi_item"
    assert bridge.args == {
        "track_guid": "{TRACK-GUID}",
        "start": {"measure": 1, "beat": 1.0},
        "length": {"beats": 4.0},
        "name": "Verse MIDI",
    }
    assert bridge.options == CommandOptions(
        mutates_project=True,
        undo_label="Create MIDI item: Verse MIDI",
    )
    assert result["ok"] is True
    assert result["item"]["active_take"]["guid"] == "{TAKE-GUID}"


async def test_media_service_inserts_audio_item_with_undo_options(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "loop.wav"
    source_path.write_bytes(b"RIFF")
    bridge = FakeBridgeClient(
        BridgeResponse(
            id="request-1",
            ok=True,
            result={
                "item": {
                    **item_payload(),
                    "name": "Loop",
                    "active_take": {
                        "guid": "{TAKE-GUID}",
                        "name": "Loop",
                        "is_midi": False,
                    },
                },
                "position": {
                    "start": {"measure": 1, "beat": 1.0},
                    "length": {"beats": 4.0},
                    "start_qn": 0.0,
                    "end_qn": 4.0,
                    "start_seconds": 0.0,
                    "end_seconds": 2.0,
                },
            },
        )
    )
    service = MediaService(bridge, allowed_media_source_roots=[tmp_path])

    result = await service.insert_audio_item(
        track_guid="{TRACK-GUID}",
        source_path=str(source_path),
        measure=1,
        beat=1,
        name="Loop",
    )

    assert bridge.command == "insert_audio_item"
    assert bridge.args == {
        "track_guid": "{TRACK-GUID}",
        "source_path": str(source_path.resolve()),
        "start": {"measure": 1, "beat": 1.0},
        "name": "Loop",
    }
    assert bridge.options == CommandOptions(
        mutates_project=True,
        undo_label="Insert audio item",
    )
    assert result["ok"] is True
    assert result["item"]["active_take"]["is_midi"] is False


async def test_media_service_moves_and_resizes_item_by_guid() -> None:
    move_bridge = FakeBridgeClient(
        BridgeResponse(
            id="request-1",
            ok=True,
            result={"item": {**item_payload(), "position_seconds": 2.0}},
        )
    )
    resize_bridge = FakeBridgeClient(
        BridgeResponse(
            id="request-2",
            ok=True,
            result={"item": {**item_payload(), "length_seconds": 4.0}},
        )
    )

    move_result = await MediaService(move_bridge).move_media_item(
        "{ITEM-GUID}", measure=2, beat=1.5
    )
    resize_result = await MediaService(resize_bridge).resize_media_item(
        "{ITEM-GUID}", length_beats=8
    )

    assert move_bridge.command == "move_media_item"
    assert move_bridge.args == {
        "item_guid": "{ITEM-GUID}",
        "start": {"measure": 2, "beat": 1.5},
    }
    assert move_bridge.options == CommandOptions(
        mutates_project=True,
        undo_label="Move media item",
    )
    assert move_result["item"]["position_seconds"] == 2.0
    assert resize_bridge.command == "resize_media_item"
    assert resize_bridge.args == {
        "item_guid": "{ITEM-GUID}",
        "length": {"beats": 8.0},
    }
    assert resize_result["item"]["length_seconds"] == 4.0


async def test_media_service_duplicates_item_with_selection_restoration() -> None:
    duplicated_item = {
        **item_payload(),
        "guid": "{DUPLICATE-GUID}",
        "position_seconds": 2.0,
        "start_qn": 4.0,
        "end_qn": 8.0,
    }
    bridge = FakeBridgeClient(
        BridgeResponse(
            id="request-1",
            ok=True,
            result={
                "source_item_guid": "{ITEM-GUID}",
                "item": duplicated_item,
                "selection_restored": True,
                "changes_applied": True,
            },
        )
    )

    result = await MediaService(bridge).duplicate_media_item("{ITEM-GUID}")

    assert bridge.command == "duplicate_media_item"
    assert bridge.args == {"item_guid": "{ITEM-GUID}"}
    assert bridge.options == CommandOptions(
        mutates_project=True,
        undo_label="Duplicate media item",
    )
    assert result["item"]["guid"] == "{DUPLICATE-GUID}"
    assert result["selection_restored"] is True


async def test_media_service_splits_item_at_musical_position() -> None:
    left_item = {**item_payload(), "length_seconds": 1.0, "end_qn": 2.0}
    right_item = {
        **item_payload(),
        "guid": "{RIGHT-ITEM-GUID}",
        "position_seconds": 1.0,
        "length_seconds": 1.0,
        "start_qn": 2.0,
    }
    bridge = FakeBridgeClient(
        BridgeResponse(
            id="request-1",
            ok=True,
            result={
                "left_item": left_item,
                "right_item": right_item,
                "changes_applied": True,
            },
        )
    )

    result = await MediaService(bridge).split_media_item(
        "{ITEM-GUID}", measure=1, beat=3
    )

    assert bridge.command == "split_media_item"
    assert bridge.args == {
        "item_guid": "{ITEM-GUID}",
        "split_at": {"measure": 1, "beat": 3.0},
    }
    assert bridge.options == CommandOptions(
        mutates_project=True,
        undo_label="Split media item",
    )
    assert result["left_item"]["guid"] == "{ITEM-GUID}"
    assert result["right_item"]["guid"] == "{RIGHT-ITEM-GUID}"


async def test_media_service_sets_item_mix_properties() -> None:
    cases = [
        (
            "set_media_item_mute",
            {"item_guid": "{ITEM-GUID}", "muted": True},
            "Set media item mute",
            {"muted": True},
        ),
        (
            "set_media_item_gain",
            {"item_guid": "{ITEM-GUID}", "gain": 0.5},
            "Set media item gain",
            {"gain": 0.5},
        ),
        (
            "set_media_item_fade_in",
            {"item_guid": "{ITEM-GUID}", "length_seconds": 0.25},
            "Set media item fade in",
            {"fade_in_seconds": 0.25},
        ),
        (
            "set_media_item_fade_out",
            {"item_guid": "{ITEM-GUID}", "length_seconds": 0.5},
            "Set media item fade out",
            {"fade_out_seconds": 0.5},
        ),
    ]

    for command, args, undo_label, item_state in cases:
        bridge = FakeBridgeClient(
            BridgeResponse(
                id="request-1",
                ok=True,
                result={"item": {**item_payload(), **item_state}},
            )
        )
        service = MediaService(bridge)
        method = getattr(service, command)
        value = next(value for key, value in args.items() if key != "item_guid")

        result = await method("{ITEM-GUID}", value)

        assert bridge.command == command
        assert bridge.args == args
        assert bridge.options == CommandOptions(
            mutates_project=True,
            undo_label=undo_label,
        )
        assert all(result["item"][key] == value for key, value in item_state.items())


async def test_media_service_rejects_invalid_item_edits_before_bridge() -> None:
    bridge = FakeBridgeClient(BridgeResponse(id="request-1", ok=True, result={}))
    service = MediaService(bridge)

    invalid_results = [
        await service.split_media_item("{ITEM-GUID}", measure=0),
        await service.set_media_item_gain("{ITEM-GUID}", 4.1),
        await service.set_media_item_fade_in("{ITEM-GUID}", -0.1),
    ]

    assert bridge.command is None
    assert all(result["ok"] is False for result in invalid_results)
    assert all(
        result["error"]["code"] == "invalid_media_item_request"
        for result in invalid_results
    )


async def test_media_service_deletes_item_by_guid() -> None:
    bridge = FakeBridgeClient(
        BridgeResponse(
            id="request-1",
            ok=True,
            result={
                "deleted_item_guid": "{ITEM-GUID}",
                "item_count": 0,
                "changes_applied": True,
            },
        )
    )

    result = await MediaService(bridge).delete_media_item("{ITEM-GUID}")

    assert bridge.command == "delete_media_item"
    assert bridge.args == {"item_guid": "{ITEM-GUID}"}
    assert bridge.options == CommandOptions(
        mutates_project=True,
        undo_label="Delete media item",
    )
    assert result["deleted_item_guid"] == "{ITEM-GUID}"


async def test_media_service_rejects_invalid_item_position_before_bridge() -> None:
    bridge = FakeBridgeClient(BridgeResponse(id="request-1", ok=True, result={}))

    result = await MediaService(bridge).move_media_item("{ITEM-GUID}", measure=0)

    assert bridge.command is None
    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_media_item_request"


async def test_media_service_rejects_audio_source_outside_allowed_roots(
    tmp_path: Path,
) -> None:
    allowed_root = tmp_path / "allowed"
    blocked_root = tmp_path / "blocked"
    allowed_root.mkdir()
    blocked_root.mkdir()
    source_path = blocked_root / "loop.wav"
    source_path.write_bytes(b"RIFF")
    bridge = FakeBridgeClient(BridgeResponse(id="request-1", ok=True, result={}))
    service = MediaService(bridge, allowed_media_source_roots=[allowed_root])

    result = await service.insert_audio_item(
        track_guid="{TRACK-GUID}",
        source_path=str(source_path),
    )

    assert bridge.command is None
    assert result["ok"] is False
    assert result["error"]["code"] == "media_source_not_allowed"


async def test_media_service_requires_explicit_allowed_media_root(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "loop.wav"
    source_path.write_bytes(b"RIFF")
    bridge = FakeBridgeClient(BridgeResponse(id="request-1", ok=True, result={}))
    service = MediaService(bridge)

    result = await service.insert_audio_item(
        track_guid="{TRACK-GUID}",
        source_path=str(source_path),
    )

    assert bridge.command is None
    assert result["ok"] is False
    assert result["error"]["code"] == "media_source_not_allowed"


async def test_media_service_gets_midi_notes() -> None:
    bridge = FakeBridgeClient(
        BridgeResponse(
            id="request-1",
            ok=True,
            result={
                "take_guid": "{TAKE-GUID}",
                "note_count": 1,
                "notes": [note_payload()],
            },
        )
    )
    service = MediaService(bridge)

    result = await service.get_midi_notes(take_guid="{TAKE-GUID}")

    assert bridge.command == "get_midi_notes"
    assert bridge.args == {"take_guid": "{TAKE-GUID}"}
    assert result["ok"] is True
    assert result["notes"][0]["pitch"] == 60


async def test_media_service_adds_midi_notes_in_batch() -> None:
    bridge = FakeBridgeClient(
        BridgeResponse(
            id="request-1",
            ok=True,
            result={
                "take_guid": "{TAKE-GUID}",
                "note_count": 2,
                "inserted_count": 2,
                "inserted_notes": [
                    note_payload(
                        fingerprint="0:0:0:960:9:36:110",
                        channel=9,
                        pitch=36,
                        velocity=110,
                    ),
                    note_payload(
                        index=1,
                        fingerprint="0:0:960:1920:9:38:100",
                        channel=9,
                        pitch=38,
                        velocity=100,
                        start_ppq=960.0,
                        end_ppq=1920.0,
                        start_qn=1.0,
                        end_qn=2.0,
                    ),
                ],
                "notes": [
                    note_payload(
                        fingerprint="0:0:0:960:9:36:110",
                        channel=9,
                        pitch=36,
                        velocity=110,
                    ),
                    note_payload(
                        index=1,
                        fingerprint="0:0:960:1920:9:38:100",
                        channel=9,
                        pitch=38,
                        velocity=100,
                        start_ppq=960.0,
                        end_ppq=1920.0,
                        start_qn=1.0,
                        end_qn=2.0,
                    ),
                ],
            },
        )
    )
    service = MediaService(bridge)
    notes = [
        {
            "start": {"measure": 1, "beat": 1},
            "length": {"beats": 1},
            "pitch": 36,
            "velocity": 110,
            "channel": 9,
        },
        {
            "start": {"measure": 1, "beat": 2},
            "length": {"beats": 1},
            "pitch": 38,
            "velocity": 100,
            "channel": 9,
        },
    ]

    result = await service.add_midi_notes(take_guid="{TAKE-GUID}", notes=notes)

    assert bridge.command == "add_midi_notes"
    assert bridge.args == {
        "take_guid": "{TAKE-GUID}",
        "notes": [
            {
                "start": {"measure": 1, "beat": 1.0},
                "length": {"beats": 1.0},
                "pitch": 36,
                "velocity": 110,
                "channel": 9,
                "selected": False,
                "muted": False,
            },
            {
                "start": {"measure": 1, "beat": 2.0},
                "length": {"beats": 1.0},
                "pitch": 38,
                "velocity": 100,
                "channel": 9,
                "selected": False,
                "muted": False,
            },
        ],
    }
    assert bridge.options == CommandOptions(
        mutates_project=True,
        undo_label="Add 2 MIDI notes",
    )
    assert result["inserted_count"] == 2


async def test_media_service_adds_single_midi_note_with_specific_undo_label() -> None:
    inserted_note = note_payload(
        fingerprint="0:0:0:960:9:36:110",
        channel=9,
        pitch=36,
        velocity=110,
    )
    bridge = FakeBridgeClient(
        BridgeResponse(
            id="request-1",
            ok=True,
            result={
                "take_guid": "{TAKE-GUID}",
                "note_count": 1,
                "inserted_count": 1,
                "inserted_notes": [inserted_note],
                "notes": [inserted_note],
                "changes_applied": True,
            },
        )
    )
    service = MediaService(bridge)
    note = {
        "start": {"measure": 1, "beat": 1},
        "length": {"beats": 1},
        "pitch": 36,
        "velocity": 110,
        "channel": 9,
    }

    result = await service.add_midi_note(take_guid="{TAKE-GUID}", note=note)

    assert bridge.command == "add_midi_notes"
    assert bridge.args == {
        "take_guid": "{TAKE-GUID}",
        "notes": [
            {
                "start": {"measure": 1, "beat": 1.0},
                "length": {"beats": 1.0},
                "pitch": 36,
                "velocity": 110,
                "channel": 9,
                "selected": False,
                "muted": False,
            }
        ],
    }
    assert bridge.options == CommandOptions(
        mutates_project=True,
        undo_label="Add MIDI note",
    )
    assert result["inserted_note"]["fingerprint"] == "0:0:0:960:9:36:110"
    assert result["note_count"] == 1


async def test_media_service_rejects_inconsistent_midi_insertion_counts() -> None:
    inserted_note = note_payload()
    bridge = FakeBridgeClient(
        BridgeResponse(
            id="request-1",
            ok=True,
            result={
                "take_guid": "{TAKE-GUID}",
                "note_count": 1,
                "inserted_count": 1,
                "inserted_notes": [inserted_note, inserted_note],
                "notes": [inserted_note],
                "changes_applied": True,
            },
        )
    )
    service = MediaService(bridge)

    result = await service.add_midi_notes(
        take_guid="{TAKE-GUID}",
        notes=[
            {
                "start": {"measure": 1, "beat": 1},
                "length": {"beats": 1},
                "pitch": 60,
                "velocity": 96,
                "channel": 0,
            }
        ],
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_bridge_response"


async def test_media_service_updates_midi_note_with_fingerprint() -> None:
    updated_note = note_payload(
        fingerprint="0:0:0:480:9:40:120",
        channel=9,
        pitch=40,
        velocity=120,
        end_ppq=480.0,
        end_qn=0.5,
    )
    bridge = FakeBridgeClient(
        BridgeResponse(
            id="request-1",
            ok=True,
            result={
                "take_guid": "{TAKE-GUID}",
                "note_count": 1,
                "updated_note": updated_note,
                "notes": [updated_note],
                "changes_applied": True,
            },
        )
    )
    service = MediaService(bridge)
    note = {
        "start": {"measure": 1, "beat": 1},
        "length": {"beats": 0.5},
        "pitch": 40,
        "velocity": 120,
        "channel": 9,
    }

    result = await service.update_midi_note(
        take_guid="{TAKE-GUID}",
        note_index=0,
        expected_fingerprint="0:0:0:960:9:36:110",
        note=note,
    )

    assert bridge.command == "update_midi_note"
    assert bridge.args == {
        "take_guid": "{TAKE-GUID}",
        "note": {
            "start": {"measure": 1, "beat": 1.0},
            "length": {"beats": 0.5},
            "pitch": 40,
            "velocity": 120,
            "channel": 9,
            "selected": False,
            "muted": False,
        },
        "note_identity": {
            "index": 0,
            "expected_fingerprint": "0:0:0:960:9:36:110",
        },
    }
    assert bridge.options == CommandOptions(
        mutates_project=True,
        undo_label="Update MIDI note",
    )
    assert result["updated_note"]["fingerprint"] == "0:0:0:480:9:40:120"


async def test_media_service_deletes_midi_notes_with_fingerprints() -> None:
    bridge = FakeBridgeClient(
        BridgeResponse(
            id="request-1",
            ok=True,
            result={
                "take_guid": "{TAKE-GUID}",
                "note_count": 0,
                "deleted_count": 2,
                "notes": [],
                "changes_applied": True,
            },
        )
    )
    service = MediaService(bridge)
    notes = [
        {"index": 0, "expected_fingerprint": "0:0:0:960:9:36:110"},
        {"index": 1, "expected_fingerprint": "0:0:960:1920:9:38:100"},
    ]

    result = await service.delete_midi_notes(take_guid="{TAKE-GUID}", notes=notes)

    assert bridge.command == "delete_midi_notes"
    assert bridge.args == {"take_guid": "{TAKE-GUID}", "notes": notes}
    assert bridge.options == CommandOptions(
        mutates_project=True,
        undo_label="Delete 2 MIDI notes",
    )
    assert result["deleted_count"] == 2


async def test_media_service_rejects_duplicate_midi_note_delete_indexes() -> None:
    bridge = FakeBridgeClient(BridgeResponse(id="request-1", ok=True, result={}))
    service = MediaService(bridge)

    result = await service.delete_midi_notes(
        take_guid="{TAKE-GUID}",
        notes=[
            {"index": 0, "expected_fingerprint": "0:0:0:960:9:36:110"},
            {"index": 0, "expected_fingerprint": "0:0:0:960:9:36:110"},
        ],
    )

    assert bridge.command is None
    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_midi_note_request"
