from reaper_mcp.models.bridge import BridgeResponse, CommandOptions
from reaper_mcp.services.batch_service import BatchService


class FakeBridgeClient:
    def __init__(self, response: BridgeResponse) -> None:
        self.response = response
        self.command: str | None = None
        self.options: CommandOptions | None = None

    async def execute(
        self,
        command: str,
        args: dict | None = None,
        options: CommandOptions | None = None,
    ) -> BridgeResponse:
        self.command = command
        self.options = options
        return self.response


def track_payload() -> dict:
    return {
        "guid": "{TRACK-GUID}",
        "name": "Drums",
        "index": 1,
        "color": 0,
        "volume": 1.0,
        "pan": 0.0,
        "mute": False,
        "solo": False,
        "armed": False,
        "selected": False,
        "media_item_count": 0,
    }


async def test_batch_updates_tracks_in_one_undo_block() -> None:
    bridge = FakeBridgeClient(
        BridgeResponse(
            id="request-1",
            ok=True,
            result={
                "tracks": [track_payload()],
                "track_count": 1,
                "changes_applied": True,
            },
        )
    )

    result = await BatchService(bridge).update_tracks(
        [{"track_guid": "{TRACK-GUID}", "volume": 0.8}]
    )

    assert bridge.command == "batch_update_tracks"
    assert bridge.options == CommandOptions(
        mutates_project=True,
        undo_label="Batch update 1 tracks",
    )
    assert result["track_count"] == 1


async def test_batch_rejects_duplicate_track_guids_before_bridge() -> None:
    bridge = FakeBridgeClient(BridgeResponse(id="request-1", ok=True, result={}))

    result = await BatchService(bridge).update_tracks(
        [
            {"track_guid": "{TRACK-GUID}", "volume": 0.8},
            {"track_guid": "{TRACK-GUID}", "pan": 0.2},
        ]
    )

    assert bridge.command is None
    assert result["error"]["code"] == "invalid_track_request"
