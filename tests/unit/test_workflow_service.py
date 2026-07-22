"""Tests for the song-starter workflow."""

from reaper_mcp.models.bridge import BridgeResponse, CommandOptions
from reaper_mcp.services.workflow_service import WorkflowService


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


def _track(role: str, index: int) -> dict:
    return {
        "guid": f"{{{role.upper()}-TRACK}}",
        "name": role.title(),
        "index": index,
        "color": 0,
        "volume": 1.0,
        "pan": 0.0,
        "mute": False,
        "solo": False,
        "armed": False,
        "selected": False,
        "media_item_count": 1,
    }


def _part(role: str, index: int, note_count: int) -> dict:
    track = _track(role, index)
    return {
        "role": role,
        "track": track,
        "item": {
            "guid": f"{{{role.upper()}-ITEM}}",
            "track_guid": track["guid"],
            "name": role.title(),
            "position_seconds": 0.0,
            "length_seconds": 16.0,
            "start_qn": 0.0,
            "end_qn": 32.0,
            "selected": False,
            "muted": False,
            "take_count": 1,
            "active_take": {
                "guid": f"{{{role.upper()}-TAKE}}",
                "name": role.title(),
                "is_midi": True,
            },
        },
        "note_count": note_count,
    }


def _result() -> dict:
    parts = [
        _part("drums", 1, 96),
        _part("bass", 2, 32),
        _part("chords", 3, 24),
        _part("lead", 4, 32),
    ]
    return {
        "name": "Demo",
        "start_measure": 1,
        "bars": 8,
        "root_note": 60,
        "mode": "major",
        "start_qn": 0.0,
        "end_qn": 32.0,
        "start_seconds": 0.0,
        "end_seconds": 16.0,
        "parts": parts,
        "region": {
            "id": 1,
            "name": "Demo",
            "start_seconds": 0.0,
            "end_seconds": 16.0,
            "color": 0,
        },
        "total_note_count": 184,
        "selection_restored": True,
        "changes_applied": True,
    }


async def test_workflow_service_creates_song_starter_in_one_undo_step() -> None:
    bridge = FakeBridgeClient(BridgeResponse(id="request-1", ok=True, result=_result()))

    result = await WorkflowService(bridge).create_song_starter(name=" Demo ")

    assert bridge.command == "create_song_starter"
    assert bridge.args == {
        "name": "Demo",
        "start_measure": 1,
        "bars": 8,
        "root_note": 60,
        "mode": "major",
    }
    assert bridge.options == CommandOptions(
        mutates_project=True,
        undo_label="Create song starter: Demo",
    )
    assert result["ok"] is True
    assert result["total_note_count"] == 184
    assert [part["role"] for part in result["parts"]] == [
        "drums",
        "bass",
        "chords",
        "lead",
    ]


async def test_workflow_service_rejects_invalid_bars_before_bridge() -> None:
    bridge = FakeBridgeClient(BridgeResponse(id="request-1", ok=True, result={}))

    result = await WorkflowService(bridge).create_song_starter(bars=6)

    assert bridge.command is None
    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_workflow_request"


async def test_workflow_service_rejects_whitespace_name_before_bridge() -> None:
    bridge = FakeBridgeClient(BridgeResponse(id="request-1", ok=True, result={}))

    result = await WorkflowService(bridge).create_song_starter(name="   ")

    assert bridge.command is None
    assert result["error"]["code"] == "invalid_workflow_request"


async def test_workflow_service_rejects_inconsistent_bridge_payload() -> None:
    payload = _result()
    payload["total_note_count"] = 1
    bridge = FakeBridgeClient(BridgeResponse(id="request-1", ok=True, result=payload))

    result = await WorkflowService(bridge).create_song_starter(name="Demo")

    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_bridge_response"
