"""Tests for guarded fixed-lane service behavior."""

from reaper_mcp.models.bridge import BridgeResponse, CommandOptions
from reaper_mcp.services.fixed_lane_service import FixedLaneService


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


def lane_layout(*, changed: bool = False) -> dict:
    return {
        "track_guid": "{TRACK}",
        "lane_count": 2,
        "layout_fingerprint": "layout-v1",
        "lanes": [
            {"index": 0, "name": "Lead A", "play_state": 1, "items": []},
            {"index": 1, "name": "Lead B", "play_state": 0, "items": []},
        ],
        "changes_applied": changed,
    }


async def test_select_fixed_lane_carries_layout_guard_and_undo() -> None:
    bridge = FakeBridgeClient(lane_layout(changed=True))

    result = await FixedLaneService(bridge).select_fixed_lane("{TRACK}", 1, "layout-v1")

    assert bridge.command == "select_fixed_lane"
    assert bridge.args == {
        "track_guid": "{TRACK}",
        "lane_index": 1,
        "expected_layout_fingerprint": "layout-v1",
    }
    assert bridge.options == CommandOptions(
        mutates_project=True,
        undo_label="Select fixed lane 2",
    )
    assert result["changes_applied"] is True


async def test_select_fixed_lane_rejects_invalid_index_before_bridge() -> None:
    bridge = FakeBridgeClient(lane_layout())

    result = await FixedLaneService(bridge).select_fixed_lane(
        "{TRACK}", -1, "layout-v1"
    )

    assert bridge.command is None
    assert result["error"]["code"] == "invalid_fixed_lane_request"
