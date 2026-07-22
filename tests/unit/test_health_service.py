from reaper_mcp.errors import ErrorCode
from reaper_mcp.models.bridge import BridgeResponse, ErrorResponse
from reaper_mcp.services.health_service import HealthService


class FakeBridgeClient:
    def __init__(self, response: BridgeResponse) -> None:
        self.response = response

    async def execute(self, command: str) -> BridgeResponse:
        assert command == "health_check"
        return self.response


async def test_health_service_returns_bridge_details() -> None:
    service = HealthService(
        FakeBridgeClient(
            BridgeResponse(
                id="request-1",
                ok=True,
                result={"status": "ok", "reaper_version": "7.0"},
            )
        )
    )

    result = await service.check()

    assert result["ok"] is True
    assert result["status"] == "ok"
    assert result["bridge"]["reaper_version"] == "7.0"


async def test_health_service_maps_timeout_to_bridge_not_running() -> None:
    service = HealthService(
        FakeBridgeClient(
            BridgeResponse(
                id="request-1",
                ok=False,
                error=ErrorResponse(
                    code=ErrorCode.COMMAND_TIMEOUT,
                    message="Timed out.",
                ),
            )
        )
    )

    result = await service.check()

    assert result["ok"] is False
    assert result["error"]["code"] == ErrorCode.BRIDGE_NOT_RUNNING
