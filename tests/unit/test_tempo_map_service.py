from reaper_mcp.models.bridge import BridgeResponse, CommandOptions
from reaper_mcp.services.tempo_map_service import TempoMapService


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


def marker_payload(**overrides: object) -> dict:
    marker = {
        "index": 0,
        "fingerprint": "0:120000:4:4:0",
        "position_seconds": 0.0,
        "position_qn": 0.0,
        "bpm": 120.0,
        "numerator": 4,
        "denominator": 4,
        "linear": False,
    }
    marker.update(overrides)
    return marker


def marker_result(marker: dict | None = None) -> dict:
    markers = [marker or marker_payload()]
    return {"markers": markers, "marker_count": len(markers)}


async def test_lists_tempo_markers() -> None:
    bridge = FakeBridgeClient(
        BridgeResponse(id="request-1", ok=True, result=marker_result())
    )

    result = await TempoMapService(bridge).list_markers()

    assert bridge.command == "list_tempo_markers"
    assert result["marker_count"] == 1
    assert result["markers"][0]["bpm"] == 120.0


async def test_creates_tempo_marker_with_undo() -> None:
    bridge = FakeBridgeClient(
        BridgeResponse(
            id="request-1",
            ok=True,
            result={**marker_result(), "marker": marker_payload()},
        )
    )

    result = await TempoMapService(bridge).create_marker(4.0, 128.0, 3, 4)

    assert bridge.command == "create_tempo_marker"
    assert bridge.args == {
        "position_seconds": 4.0,
        "bpm": 128.0,
        "numerator": 3,
        "denominator": 4,
        "linear": False,
    }
    assert bridge.options == CommandOptions(
        mutates_project=True,
        undo_label="Create tempo marker: 128 BPM",
    )
    assert result["ok"] is True


async def test_rejects_unsupported_tempo_marker_denominator() -> None:
    bridge = FakeBridgeClient(BridgeResponse(id="request-1", ok=True, result={}))

    result = await TempoMapService(bridge).create_marker(4.0, 128.0, 3, 7)

    assert bridge.command is None
    assert result["error"]["code"] == "invalid_tempo_request"
