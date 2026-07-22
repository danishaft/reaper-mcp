from typing import Any

from reaper_mcp.models.bridge import BridgeResponse, CommandOptions
from reaper_mcp.services.midi_transform_service import MidiTransformService


class FakeBridgeClient:
    def __init__(self, response: BridgeResponse) -> None:
        self.response = response
        self.command: str | None = None
        self.args: dict[str, Any] | None = None
        self.options: CommandOptions | None = None

    async def execute(
        self,
        command: str,
        args: dict[str, Any] | None = None,
        options: CommandOptions | None = None,
    ) -> BridgeResponse:
        self.command = command
        self.args = args
        self.options = options
        return self.response


def note_identity(index: int = 0, fingerprint: str = "0:0:0:960:0:60:96") -> dict:
    return {"index": index, "expected_fingerprint": fingerprint}


def note_payload() -> dict:
    return {
        "index": 0,
        "fingerprint": "0:0:0:960:0:72:96",
        "selected": False,
        "muted": False,
        "start_ppq": 0.0,
        "end_ppq": 960.0,
        "start_qn": 0.0,
        "end_qn": 1.0,
        "channel": 0,
        "pitch": 72,
        "velocity": 96,
    }


def transform_response(transformed_count: int = 1) -> BridgeResponse:
    return BridgeResponse(
        id="request-1",
        ok=True,
        result={
            "take_guid": "{TAKE-GUID}",
            "notes": [note_payload()],
            "note_count": 1,
            "transformed_count": transformed_count,
            "changes_applied": True,
        },
    )


async def test_midi_transform_service_executes_guarded_transform_contracts() -> None:
    cases = [
        (
            "transpose_midi_notes",
            {"semitones": 12},
            "Transpose MIDI notes",
        ),
        (
            "nudge_midi_notes",
            {"offset_beats": 0.25},
            "Nudge MIDI notes",
        ),
        (
            "quantize_midi_notes",
            {"grid_beats": 0.25, "strength": 0.75, "swing": 0.5},
            "Quantize MIDI notes",
        ),
        (
            "snap_midi_notes_to_scale",
            {
                "root_pitch_class": 0,
                "scale": "major",
                "direction": "nearest",
            },
            "Snap MIDI notes to scale",
        ),
        (
            "shape_midi_note_velocities",
            {"factor": 0.8, "offset": 4},
            "Shape MIDI note velocities",
        ),
        (
            "remove_midi_note_overlaps",
            {},
            "Remove MIDI note overlaps",
        ),
    ]

    for command, parameters, undo_label in cases:
        bridge = FakeBridgeClient(transform_response())
        service = MidiTransformService(bridge)
        method = getattr(service, command)

        result = await method(
            "{TAKE-GUID}",
            [note_identity()],
            **parameters,
        )

        assert bridge.command == command
        assert bridge.args == {
            "take_guid": "{TAKE-GUID}",
            "notes": [note_identity()],
            **parameters,
        }
        assert bridge.options == CommandOptions(
            mutates_project=True,
            undo_label=undo_label,
        )
        assert result["ok"] is True
        assert result["transformed_count"] == 1


async def test_humanize_midi_notes_generates_stable_bounded_offsets() -> None:
    identities = [
        note_identity(),
        note_identity(1, "0:0:960:1920:0:64:100"),
    ]
    first_bridge = FakeBridgeClient(transform_response(2))
    second_bridge = FakeBridgeClient(transform_response(2))

    first = await MidiTransformService(first_bridge).humanize_midi_notes(
        "{TAKE-GUID}", identities, seed=42
    )
    second = await MidiTransformService(second_bridge).humanize_midi_notes(
        "{TAKE-GUID}", identities, seed=42
    )

    assert first["ok"] is True
    assert second["ok"] is True
    assert first_bridge.command == "humanize_midi_notes"
    assert first_bridge.args == second_bridge.args
    assert first_bridge.args == {
        "take_guid": "{TAKE-GUID}",
        "notes": identities,
        "max_timing_offset_beats": 0.02,
        "max_velocity_offset": 8,
        "seed": 42,
        "timing_offsets": [-0.006853, -0.004425],
        "velocity_offsets": [2, -6],
    }
    assert first_bridge.options == CommandOptions(
        mutates_project=True,
        undo_label="Humanize MIDI notes",
    )


async def test_midi_transform_service_rejects_invalid_requests_before_bridge() -> None:
    bridge = FakeBridgeClient(transform_response())
    service = MidiTransformService(bridge)

    invalid_results = [
        await service.transpose_midi_notes("{TAKE-GUID}", [note_identity()], 0),
        await service.nudge_midi_notes("{TAKE-GUID}", [note_identity()], 0),
        await service.quantize_midi_notes(
            "{TAKE-GUID}", [note_identity()], grid_beats=0
        ),
        await service.humanize_midi_notes(
            "{TAKE-GUID}",
            [note_identity()],
            max_timing_offset_beats=0,
            max_velocity_offset=0,
        ),
        await service.snap_midi_notes_to_scale(
            "{TAKE-GUID}", [note_identity()], root_pitch_class=12
        ),
        await service.shape_midi_note_velocities("{TAKE-GUID}", [note_identity()]),
        await service.remove_midi_note_overlaps(
            "{TAKE-GUID}",
            [note_identity(), note_identity()],
        ),
    ]

    assert bridge.command is None
    assert all(result["ok"] is False for result in invalid_results)
    assert all(
        result["error"]["code"] == "invalid_midi_note_request"
        for result in invalid_results
    )


async def test_midi_transform_service_rejects_invalid_bridge_result() -> None:
    bridge = FakeBridgeClient(
        BridgeResponse(
            id="request-1",
            ok=True,
            result={
                "take_guid": "{TAKE-GUID}",
                "notes": [note_payload()],
                "note_count": 1,
                "transformed_count": 0,
            },
        )
    )

    result = await MidiTransformService(bridge).transpose_midi_notes(
        "{TAKE-GUID}", [note_identity()], 12
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_bridge_response"
