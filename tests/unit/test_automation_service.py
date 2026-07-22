from reaper_mcp.models.bridge import BridgeResponse, CommandOptions
from reaper_mcp.services.automation_service import AutomationService


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


def point_result() -> dict:
    return {
        "envelope": {
            "guid": "{ENV}",
            "track_guid": "{TRACK}",
            "index": 0,
            "name": "Volume",
            "point_count": 1,
        },
        "points": [
            {
                "index": 0,
                "fingerprint": "0:1:0:0:0",
                "time_seconds": 0.0,
                "value": 1.0,
                "shape": 0,
                "tension": 0.0,
                "selected": False,
                "formatted_value": "0.00 dB",
            }
        ],
        "point_count": 1,
        "changes_applied": True,
    }


async def test_add_envelope_points_is_one_undoable_batch() -> None:
    bridge = FakeBridgeClient(point_result())

    result = await AutomationService(bridge).add_envelope_points(
        "{TRACK}",
        "{ENV}",
        [{"time_seconds": 0.0, "value": 1.0}],
    )

    assert bridge.command == "add_envelope_points"
    assert bridge.args == {
        "envelope_identity": {
            "track_guid": "{TRACK}",
            "envelope_guid": "{ENV}",
        },
        "points": [
            {
                "time_seconds": 0.0,
                "value": 1.0,
                "shape": 0,
                "tension": 0.0,
                "selected": False,
            }
        ],
    }
    assert bridge.options == CommandOptions(
        mutates_project=True,
        undo_label="Add 1 envelope points",
    )
    assert result["changes_applied"] is True


async def test_ensure_track_envelope_is_undoable() -> None:
    payload = {
        "envelope": point_result()["envelope"],
        "created": True,
        "changes_applied": True,
    }
    bridge = FakeBridgeClient(payload)

    result = await AutomationService(bridge).ensure_track_envelope("{TRACK}", "volume")

    assert bridge.command == "ensure_track_envelope"
    assert bridge.args == {"track_guid": "{TRACK}", "envelope_type": "volume"}
    assert bridge.options == CommandOptions(
        mutates_project=True,
        undo_label="Ensure track envelope: volume",
    )
    assert result["created"] is True


async def test_duplicate_point_times_are_rejected_before_bridge() -> None:
    bridge = FakeBridgeClient({})

    result = await AutomationService(bridge).add_envelope_points(
        "{TRACK}",
        "{ENV}",
        [
            {"time_seconds": 1.0, "value": 0.5},
            {"time_seconds": 1.0, "value": 0.75},
        ],
    )

    assert bridge.command is None
    assert result["error"]["code"] == "invalid_automation_request"
