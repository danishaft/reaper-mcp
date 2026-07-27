from reaper_mcp.models.bridge import BridgeResponse
from reaper_mcp.services.project_controls_service import ProjectControlsService


class FakeBridgeClient:
    def __init__(self, response: BridgeResponse) -> None:
        self.response = response
        self.command: str | None = None
        self.args: dict | None = None

    async def execute(
        self,
        command: str,
        args: dict | None = None,
        options: object | None = None,
    ) -> BridgeResponse:
        self.command = command
        self.args = args
        return self.response


def control_result(action: str = "set_grid") -> dict:
    return {
        "action": action,
        "changes_applied": True,
        "grid": {
            "division": 1.0,
            "swing": 0.0,
            "swing_mode": 0,
            "snap_enabled": True,
        },
    }


async def test_sets_grid_settings() -> None:
    bridge = FakeBridgeClient(
        BridgeResponse(id="request-1", ok=True, result=control_result())
    )

    result = await ProjectControlsService(bridge).set_grid(1.0, 0.25, 1, True)

    assert bridge.command == "set_grid"
    assert bridge.args == {
        "division": 1.0,
        "swing": 0.25,
        "swing_mode": 1,
        "snap_enabled": True,
    }
    assert result["grid"]["division"] == 1.0


async def test_rejects_invalid_playback_rate_before_bridge() -> None:
    bridge = FakeBridgeClient(BridgeResponse(id="request-1", ok=True, result={}))

    result = await ProjectControlsService(bridge).set_playback_rate(5.0)

    assert bridge.command is None
    assert result["error"]["code"] == "invalid_navigation_request"
