"""Tests for verified track freeze operations."""

from reaper_mcp.models.bridge import BridgeResponse, CommandOptions
from reaper_mcp.services.freeze_service import FreezeService


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


def freeze_state(*, frozen: bool, freeze_count: int) -> dict:
    return {
        "track_guid": "{TRACK-GUID}",
        "frozen": frozen,
        "freeze_count": freeze_count,
        "track": {
            "guid": "{TRACK-GUID}",
            "name": "Synth",
            "index": 1,
        },
    }


async def test_freeze_service_reads_track_state() -> None:
    bridge = FakeBridgeClient(
        BridgeResponse(
            id="request-1",
            ok=True,
            result=freeze_state(frozen=False, freeze_count=0),
        )
    )

    result = await FreezeService(bridge).get_track_freeze_state("{TRACK-GUID}")

    assert bridge.command == "get_track_freeze_state"
    assert bridge.args == {"track_guid": "{TRACK-GUID}"}
    assert bridge.options is None
    assert result["state"]["frozen"] is False


async def test_freeze_service_freezes_track_with_undo() -> None:
    bridge = FakeBridgeClient(
        BridgeResponse(
            id="request-1",
            ok=True,
            result={
                "state": freeze_state(frozen=True, freeze_count=1),
                "selection_restored": True,
                "may_create_media_files": True,
                "changes_applied": True,
            },
        )
    )

    result = await FreezeService(bridge).freeze_track("{TRACK-GUID}")

    assert bridge.command == "freeze_track"
    assert bridge.options == CommandOptions(
        mutates_project=True,
        undo_label="Freeze track to stereo",
    )
    assert result["state"]["freeze_count"] == 1
    assert result["selection_restored"] is True
    assert result["may_create_media_files"] is True


async def test_freeze_service_unfreezes_track_with_undo() -> None:
    bridge = FakeBridgeClient(
        BridgeResponse(
            id="request-1",
            ok=True,
            result={
                "state": freeze_state(frozen=False, freeze_count=0),
                "selection_restored": True,
                "may_create_media_files": False,
                "changes_applied": True,
            },
        )
    )

    result = await FreezeService(bridge).unfreeze_track("{TRACK-GUID}")

    assert bridge.command == "unfreeze_track"
    assert bridge.options == CommandOptions(
        mutates_project=True,
        undo_label="Unfreeze track",
    )
    assert result["state"]["frozen"] is False
    assert result["may_create_media_files"] is False


async def test_freeze_service_rejects_empty_guid_before_bridge() -> None:
    bridge = FakeBridgeClient(BridgeResponse(id="request-1", ok=True, result={}))

    result = await FreezeService(bridge).freeze_track("")

    assert bridge.command is None
    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_track_request"
