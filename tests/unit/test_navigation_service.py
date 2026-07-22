from pathlib import Path

from reaper_mcp.models.bridge import BridgeResponse, CommandOptions
from reaper_mcp.services.navigation_service import NavigationService


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


def navigation_result(project_path: str | None = None) -> dict:
    empty_range = {
        "start_seconds": 0.0,
        "end_seconds": 0.0,
        "length_seconds": 0.0,
        "is_set": False,
    }
    return {
        "project_path": project_path,
        "dirty": False,
        "edit_cursor_seconds": 0.0,
        "time_selection": empty_range,
        "loop_points": empty_range,
        "loop_enabled": False,
        "changes_applied": True,
        "saved": project_path is not None,
    }


async def test_save_as_is_default_deny() -> None:
    bridge = FakeBridgeClient({})
    service = NavigationService(bridge)

    result = await service.save_project_as("/tmp/session.rpp")

    assert bridge.command is None
    assert result["error"]["code"] == "project_path_not_allowed"


async def test_save_as_uses_allowed_root_without_project_mutation_flag(
    tmp_path: Path,
) -> None:
    project_path = tmp_path / "session.rpp"
    bridge = FakeBridgeClient(navigation_result(str(project_path)))
    service = NavigationService(bridge, allowed_project_roots=[tmp_path])

    result = await service.save_project_as(str(project_path))

    assert bridge.command == "save_project_as"
    assert bridge.args == {"project_path": str(project_path), "overwrite": False}
    assert bridge.options is None
    assert result["saved"] is True
