from reaper_mcp.models.bridge import BridgeResponse, CommandOptions
from reaper_mcp.services.transport_service import TransportService


class FakeBridgeClient:
    def __init__(self) -> None:
        self.commands: list[str] = []
        self.options: list[CommandOptions | None] = []

    async def execute(
        self,
        command: str,
        args: dict | None = None,
        options: CommandOptions | None = None,
    ) -> BridgeResponse:
        self.commands.append(command)
        self.options.append(options)
        return BridgeResponse(
            id="request-1",
            ok=True,
            result={
                "action": command,
                "transport": {
                    "play_state": 0,
                    "playing": False,
                    "paused": False,
                    "recording": False,
                },
                "may_create_media_items": command in {"record", "stop_recording"},
            },
        )


async def test_transport_service_calls_bridge_commands() -> None:
    bridge = FakeBridgeClient()
    service = TransportService(bridge)

    await service.play()
    await service.stop()
    stop_recording_result = await service.stop_recording()
    await service.pause()
    result = await service.record()

    assert bridge.commands == ["play", "stop", "stop_recording", "pause", "record"]
    assert bridge.options[:2] == [None, None]
    assert bridge.options[2] == CommandOptions(
        mutates_project=True,
        undo_label="Stop recording",
    )
    assert bridge.options[3] is None
    assert bridge.options[4] == CommandOptions(
        mutates_project=True,
        undo_label="Record",
    )
    assert stop_recording_result["may_create_media_items"] is True
    assert result["ok"] is True
    assert result["action"] == "record"
    assert result["may_create_media_items"] is True
