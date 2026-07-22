from reaper_mcp.models.bridge import BridgeResponse
from reaper_mcp.services.diagnostics_service import DiagnosticsService


class FakeBridgeClient:
    def __init__(self) -> None:
        self.commands: list[str] = []

    async def execute(self, command: str) -> BridgeResponse:
        self.commands.append(command)
        return BridgeResponse(
            id="request-1",
            ok=True,
            result={"command": command},
        )


async def test_diagnostics_service_calls_read_only_bridge_commands() -> None:
    bridge = FakeBridgeClient()
    service = DiagnosticsService(bridge)

    reaper_version = await service.get_reaper_version()
    project_info = await service.get_project_info()
    bridge_status = await service.get_bridge_status()

    assert bridge.commands == [
        "get_reaper_version",
        "get_project_info",
        "get_bridge_status",
    ]
    assert reaper_version["result"]["command"] == "get_reaper_version"
    assert project_info["result"]["command"] == "get_project_info"
    assert bridge_status["result"]["command"] == "get_bridge_status"
