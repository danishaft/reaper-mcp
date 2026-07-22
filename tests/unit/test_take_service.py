from reaper_mcp.models.bridge import BridgeResponse, CommandOptions
from reaper_mcp.services.take_service import TakeService


class FakeBridgeClient:
    def __init__(self, result: dict) -> None:
        self.response = BridgeResponse(id="request-1", ok=True, result=result)
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


def take_payload() -> dict:
    return {
        "guid": "{TAKE}",
        "item_guid": "{ITEM}",
        "index": 0,
        "name": "Lead",
        "is_active": True,
        "is_midi": False,
        "volume": 1.0,
        "pan": 0.0,
        "pitch_semitones": 0.0,
        "playback_rate": 1.0,
        "start_offset_seconds": 0.0,
        "preserve_pitch": True,
    }


def mutation_result() -> dict:
    take = take_payload()
    return {
        "item_guid": "{ITEM}",
        "takes": [take],
        "take_count": 1,
        "active_take_guid": "{TAKE}",
        "changed_take": take,
        "changes_applied": True,
    }


async def test_set_take_playback_rate_carries_pitch_policy_and_undo() -> None:
    bridge = FakeBridgeClient(mutation_result())

    result = await TakeService(bridge).set_take_playback_rate(
        "{TAKE}", 1.25, preserve_pitch=False
    )

    assert bridge.command == "set_take_property"
    assert bridge.args == {
        "take_guid": "{TAKE}",
        "property": "playback_rate",
        "value": 1.25,
        "preserve_pitch": False,
    }
    assert bridge.options == CommandOptions(
        mutates_project=True,
        undo_label="Set take playback_rate",
    )
    assert result["changed_take"]["guid"] == "{TAKE}"


async def test_take_property_range_is_rejected_before_bridge() -> None:
    bridge = FakeBridgeClient({})

    result = await TakeService(bridge).set_take_pan("{TAKE}", 1.5)

    assert bridge.command is None
    assert result["error"]["code"] == "invalid_take_request"
