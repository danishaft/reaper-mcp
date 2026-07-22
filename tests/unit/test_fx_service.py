from reaper_mcp.models.bridge import BridgeResponse, CommandOptions
from reaper_mcp.services.fx_service import FxService


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


def fx_payload(
    index: int = 0,
    identity: str = "{TRACK-GUID}:0:{FX-GUID}",
    name: str = "VST: ReaEQ",
    enabled: bool = True,
    guid: str | None = "{FX-GUID}",
) -> dict:
    return {
        "identity": identity,
        "track_guid": "{TRACK-GUID}",
        "index": index,
        "name": name,
        "enabled": enabled,
        "offline": False,
        "guid": guid,
    }


def fx_identity() -> dict:
    return {
        "track_guid": "{TRACK-GUID}",
        "index": 0,
        "expected_identity": "{TRACK-GUID}:0:{FX-GUID}",
        "expected_name": "VST: ReaEQ",
        "expected_guid": "{FX-GUID}",
    }


def fx_parameter_payload(
    index: int = 0,
    name: str = "Gain",
    normalized_value: float = 0.5,
    formatted_value: str = "-6.00 dB",
) -> dict:
    return {
        "index": index,
        "name": name,
        "normalized_value": normalized_value,
        "formatted_value": formatted_value,
    }


async def test_fx_service_lists_track_fx() -> None:
    bridge = FakeBridgeClient(
        BridgeResponse(
            id="request-1",
            ok=True,
            result={
                "track_guid": "{TRACK-GUID}",
                "fx_count": 1,
                "fx": [fx_payload()],
            },
        )
    )
    service = FxService(bridge)

    result = await service.list_track_fx(track_guid="{TRACK-GUID}")

    assert bridge.command == "list_track_fx"
    assert bridge.args == {"track_guid": "{TRACK-GUID}"}
    assert result["ok"] is True
    assert result["fx_count"] == 1
    assert result["fx"][0]["name"] == "VST: ReaEQ"
    assert result["fx"][0]["identity"] == "{TRACK-GUID}:0:{FX-GUID}"


async def test_fx_service_lists_available_fx() -> None:
    bridge = FakeBridgeClient(
        BridgeResponse(
            id="request-1",
            ok=True,
            result={
                "fx_count": 1,
                "fx": [
                    {
                        "index": 0,
                        "name": "VST: ReaEQ",
                        "identifier": "vst:reaeq",
                    }
                ],
            },
        )
    )
    service = FxService(bridge)

    result = await service.list_available_fx()

    assert bridge.command == "list_available_fx"
    assert bridge.args is None
    assert result["ok"] is True
    assert result["fx_count"] == 1
    assert result["fx"][0]["identifier"] == "vst:reaeq"


async def test_fx_service_rejects_empty_track_guid() -> None:
    bridge = FakeBridgeClient(BridgeResponse(id="request-1", ok=True, result={}))
    service = FxService(bridge)

    result = await service.list_track_fx(track_guid="")

    assert bridge.command is None
    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_fx_request"


async def test_fx_service_adds_fx_with_undo_options() -> None:
    bridge = FakeBridgeClient(
        BridgeResponse(
            id="request-1",
            ok=True,
            result={
                "track_guid": "{TRACK-GUID}",
                "fx_count": 1,
                "added_fx": fx_payload(),
                "fx": [fx_payload()],
                "changes_applied": True,
            },
        )
    )
    service = FxService(bridge)

    result = await service.add_fx(
        track_guid="{TRACK-GUID}",
        fx_identifier="VST: ReaEQ",
        index=0,
    )

    assert bridge.command == "add_fx"
    assert bridge.args == {
        "track_guid": "{TRACK-GUID}",
        "fx_identifier": "VST: ReaEQ",
        "index": 0,
        "enabled": True,
    }
    assert bridge.options == CommandOptions(
        mutates_project=True,
        undo_label="Add FX: VST: ReaEQ",
    )
    assert result["added_fx"]["identity"] == "{TRACK-GUID}:0:{FX-GUID}"


async def test_fx_service_removes_fx_with_identity_guard() -> None:
    bridge = FakeBridgeClient(
        BridgeResponse(
            id="request-1",
            ok=True,
            result={
                "track_guid": "{TRACK-GUID}",
                "fx_count": 0,
                "removed_fx_identity": "{TRACK-GUID}:0:{FX-GUID}",
                "fx": [],
                "changes_applied": True,
            },
        )
    )
    service = FxService(bridge)

    result = await service.remove_fx(fx_identity=fx_identity())

    assert bridge.command == "remove_fx"
    assert bridge.args == {"fx_identity": fx_identity()}
    assert bridge.options == CommandOptions(
        mutates_project=True,
        undo_label="Remove FX: VST: ReaEQ",
    )
    assert result["removed_fx_identity"] == "{TRACK-GUID}:0:{FX-GUID}"


async def test_fx_service_sets_fx_enabled_with_identity_guard() -> None:
    disabled_fx = fx_payload(enabled=False)
    bridge = FakeBridgeClient(
        BridgeResponse(
            id="request-1",
            ok=True,
            result={
                "track_guid": "{TRACK-GUID}",
                "fx_count": 1,
                "updated_fx": disabled_fx,
                "fx": [disabled_fx],
                "changes_applied": True,
            },
        )
    )
    service = FxService(bridge)

    result = await service.set_fx_enabled(
        fx_identity=fx_identity(),
        enabled=False,
    )

    assert bridge.command == "set_fx_enabled"
    assert bridge.args == {"fx_identity": fx_identity(), "enabled": False}
    assert bridge.options == CommandOptions(
        mutates_project=True,
        undo_label="Set FX enabled: VST: ReaEQ",
    )
    assert result["updated_fx"]["enabled"] is False


async def test_fx_service_gets_fx_parameters_with_identity_guard() -> None:
    bridge = FakeBridgeClient(
        BridgeResponse(
            id="request-1",
            ok=True,
            result={
                "fx_identity": fx_identity(),
                "parameter_count": 1,
                "parameters": [fx_parameter_payload()],
            },
        )
    )
    service = FxService(bridge)

    result = await service.get_fx_parameters(fx_identity=fx_identity())

    assert bridge.command == "get_fx_parameters"
    assert bridge.args == {"fx_identity": fx_identity()}
    assert result["ok"] is True
    assert result["parameter_count"] == 1
    assert result["parameters"][0] == fx_parameter_payload()


async def test_fx_service_sets_fx_parameter_with_identity_guard_and_undo() -> None:
    updated_parameter = fx_parameter_payload(normalized_value=0.25)
    bridge = FakeBridgeClient(
        BridgeResponse(
            id="request-1",
            ok=True,
            result={
                "fx_identity": fx_identity(),
                "parameter_count": 1,
                "updated_parameter": updated_parameter,
                "parameters": [updated_parameter],
                "changes_applied": True,
            },
        )
    )
    service = FxService(bridge)

    result = await service.set_fx_parameter(
        fx_identity=fx_identity(),
        parameter_index=0,
        normalized_value=0.25,
    )

    assert bridge.command == "set_fx_parameter"
    assert bridge.args == {
        "fx_identity": fx_identity(),
        "parameter_index": 0,
        "normalized_value": 0.25,
    }
    assert bridge.options == CommandOptions(
        mutates_project=True,
        undo_label="Set FX parameter: VST: ReaEQ",
    )
    assert result["updated_parameter"] == updated_parameter
