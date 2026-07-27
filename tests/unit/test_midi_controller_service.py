from reaper_mcp.models.bridge import BridgeResponse, CommandOptions
from reaper_mcp.services.midi_controller_service import MidiControllerService


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


def event_payload(**overrides: object) -> dict:
    event = {
        "index": 0,
        "fingerprint": "0:0:960:176:0:1:100",
        "position_ppq": 960.0,
        "position_qn": 1.0,
        "event_type": "cc",
        "controller": 1,
        "value": 100,
        "channel": 0,
        "selected": False,
        "muted": False,
    }
    event.update(overrides)
    return event


def list_result(event: dict | None = None) -> dict:
    events = [event or event_payload()]
    return {
        "take_guid": "{TAKE-GUID}",
        "events": events,
        "event_count": len(events),
    }


async def test_lists_controller_events() -> None:
    bridge = FakeBridgeClient(
        BridgeResponse(id="request-1", ok=True, result=list_result())
    )

    result = await MidiControllerService(bridge).list_events("{TAKE-GUID}")

    assert bridge.command == "get_midi_controller_events"
    assert result["event_count"] == 1
    assert result["events"][0]["event_type"] == "cc"


async def test_adds_controller_events_in_one_undoable_batch() -> None:
    bridge = FakeBridgeClient(
        BridgeResponse(
            id="request-1",
            ok=True,
            result={
                **list_result(),
                "inserted_events": [event_payload()],
                "inserted_count": 1,
                "changes_applied": True,
            },
        )
    )

    result = await MidiControllerService(bridge).add_events(
        "{TAKE-GUID}",
        [
            {
                "position": {"measure": 1, "beat": 2},
                "event_type": "cc",
                "controller": 1,
                "value": 100,
            }
        ],
    )

    assert bridge.command == "add_midi_controller_events"
    assert bridge.options == CommandOptions(
        mutates_project=True,
        undo_label="Add 1 MIDI controller events",
    )
    assert result["inserted_count"] == 1


async def test_rejects_invalid_controller_before_bridge() -> None:
    bridge = FakeBridgeClient(BridgeResponse(id="request-1", ok=True, result={}))

    result = await MidiControllerService(bridge).add_events(
        "{TAKE-GUID}",
        [
            {
                "position": {"measure": 1, "beat": 1},
                "event_type": "cc",
                "controller": 1,
                "value": 200,
            }
        ],
    )

    assert bridge.command is None
    assert result["error"]["code"] == "invalid_midi_controller_request"
