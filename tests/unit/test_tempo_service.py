from reaper_mcp.models.bridge import BridgeResponse, CommandOptions
from reaper_mcp.services.tempo_service import TempoService


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


async def test_tempo_service_gets_tempo() -> None:
    bridge = FakeBridgeClient(
        BridgeResponse(
            id="request-1",
            ok=True,
            result={"tempo": {"bpm": 120.0}},
        )
    )
    service = TempoService(bridge)

    result = await service.get_tempo()

    assert bridge.command == "get_tempo"
    assert result["tempo"] == {"bpm": 120.0}


async def test_tempo_service_sets_tempo_with_undo() -> None:
    bridge = FakeBridgeClient(
        BridgeResponse(
            id="request-1",
            ok=True,
            result={"tempo": {"bpm": 128.0}, "changes_applied": True},
        )
    )
    service = TempoService(bridge)

    result = await service.set_tempo(bpm=128.0)

    assert bridge.command == "set_tempo"
    assert bridge.args == {"bpm": 128.0}
    assert bridge.options == CommandOptions(
        mutates_project=True,
        undo_label="Set tempo: 128 BPM",
    )
    assert result["tempo"] == {"bpm": 128.0}


async def test_tempo_service_gets_time_signature() -> None:
    bridge = FakeBridgeClient(
        BridgeResponse(
            id="request-1",
            ok=True,
            result={
                "time_signature": {"numerator": 4, "denominator": 4},
                "tempo": {"bpm": 120.0},
            },
        )
    )
    service = TempoService(bridge)

    result = await service.get_time_signature()

    assert bridge.command == "get_time_signature"
    assert result["time_signature"] == {"numerator": 4, "denominator": 4}
    assert result["tempo"] == {"bpm": 120.0}


async def test_tempo_service_sets_time_signature_with_undo() -> None:
    bridge = FakeBridgeClient(
        BridgeResponse(
            id="request-1",
            ok=True,
            result={
                "time_signature": {"numerator": 7, "denominator": 8},
                "tempo": {"bpm": 120.0},
                "changes_applied": True,
            },
        )
    )
    service = TempoService(bridge)

    result = await service.set_time_signature(numerator=7, denominator=8)

    assert bridge.command == "set_time_signature"
    assert bridge.args == {"numerator": 7, "denominator": 8}
    assert bridge.options == CommandOptions(
        mutates_project=True,
        undo_label="Set time signature: 7/8",
    )
    assert result["time_signature"] == {"numerator": 7, "denominator": 8}


async def test_tempo_service_rejects_bpm_outside_policy() -> None:
    bridge = FakeBridgeClient(BridgeResponse(id="request-1", ok=True, result={}))
    service = TempoService(bridge)

    result = await service.set_tempo(bpm=10.0)

    assert bridge.command is None
    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_tempo_request"


async def test_tempo_service_rejects_unsupported_denominator() -> None:
    bridge = FakeBridgeClient(BridgeResponse(id="request-1", ok=True, result={}))
    service = TempoService(bridge)

    result = await service.set_time_signature(numerator=5, denominator=7)

    assert bridge.command is None
    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_tempo_request"
