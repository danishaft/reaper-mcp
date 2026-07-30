"""Tests for guarded track routing operations."""

from reaper_mcp.models.bridge import BridgeResponse, CommandOptions
from reaper_mcp.services.routing_service import RoutingService


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


def send_payload(**changes: object) -> dict:
    return {
        "identity": "{SOURCE}:0:{DESTINATION}",
        "source_track_guid": "{SOURCE}",
        "destination_track_guid": "{DESTINATION}",
        "destination_track_name": "Bus",
        "index": 0,
        "volume": 1.0,
        "pan": 0.0,
        "muted": False,
        **changes,
    }


async def test_routing_service_lists_track_sends() -> None:
    bridge = FakeBridgeClient(
        BridgeResponse(
            id="request-1",
            ok=True,
            result={
                "source_track_guid": "{SOURCE}",
                "sends": [send_payload()],
                "send_count": 1,
            },
        )
    )

    result = await RoutingService(bridge).list_track_sends("{SOURCE}")

    assert bridge.command == "list_track_sends"
    assert result["sends"][0]["destination_track_guid"] == "{DESTINATION}"


async def test_routing_service_creates_send_with_undo() -> None:
    bridge = FakeBridgeClient(
        BridgeResponse(
            id="request-1",
            ok=True,
            result={"send": send_payload(), "send_count": 1},
        )
    )

    result = await RoutingService(bridge).create_track_send(
        "{SOURCE}", "{DESTINATION}", volume=0.5, pan=-0.2
    )

    assert bridge.command == "create_track_send"
    assert bridge.args == {
        "source_track_guid": "{SOURCE}",
        "destination_track_guid": "{DESTINATION}",
        "volume": 0.5,
        "pan": -0.2,
        "muted": False,
    }
    assert bridge.options == CommandOptions(
        mutates_project=True,
        undo_label="Create track send",
    )
    assert result["send_count"] == 1


async def test_routing_service_sets_guarded_send_properties() -> None:
    bridge = FakeBridgeClient(
        BridgeResponse(
            id="request-1",
            ok=True,
            result={"send": send_payload(volume=0.25, muted=True)},
        )
    )

    result = await RoutingService(bridge).set_track_send(
        "{SOURCE}",
        0,
        "{DESTINATION}",
        volume=0.25,
        muted=True,
    )

    assert bridge.command == "set_track_send"
    assert bridge.args == {
        "send_identity": {
            "source_track_guid": "{SOURCE}",
            "index": 0,
            "expected_destination_track_guid": "{DESTINATION}",
        },
        "volume": 0.25,
        "muted": True,
    }
    assert result["send"]["muted"] is True


async def test_routing_service_removes_guarded_send() -> None:
    bridge = FakeBridgeClient(
        BridgeResponse(
            id="request-1",
            ok=True,
            result={
                "source_track_guid": "{SOURCE}",
                "destination_track_guid": "{DESTINATION}",
                "removed_index": 0,
                "send_count": 0,
            },
        )
    )

    result = await RoutingService(bridge).remove_track_send(
        "{SOURCE}", 0, "{DESTINATION}"
    )

    assert bridge.command == "remove_track_send"
    assert bridge.options == CommandOptions(
        mutates_project=True,
        undo_label="Remove track send",
    )
    assert result["send_count"] == 0


async def test_routing_service_rejects_self_send_and_empty_update() -> None:
    bridge = FakeBridgeClient(BridgeResponse(id="request-1", ok=True, result={}))
    service = RoutingService(bridge)

    self_send = await service.create_track_send("{TRACK}", "{TRACK}")
    empty_update = await service.set_track_send("{SOURCE}", 0, "{DESTINATION}")

    assert bridge.command is None
    assert self_send["error"]["code"] == "invalid_send_request"
    assert empty_update["error"]["code"] == "invalid_send_request"


async def test_routing_service_configures_reference_track_with_undo() -> None:
    bridge = FakeBridgeClient(
        BridgeResponse(
            id="request-1",
            ok=True,
            result={
                "track_guid": "{REFERENCE}",
                "master_send_enabled": False,
                "hardware_output": {
                    "identity": "{REFERENCE}:hardware:0:0",
                    "source_track_guid": "{REFERENCE}",
                    "index": 0,
                    "hardware_output_pair": 1,
                    "destination_channels": "1/2",
                    "volume": 0.5,
                    "pan": 0.0,
                    "muted": False,
                    "send_mode": 0,
                },
                "hardware_send_created": True,
                "changes_applied": True,
            },
        )
    )

    result = await RoutingService(bridge).configure_reference_track(
        "{REFERENCE}",
        hardware_output_pair=1,
        volume=0.5,
    )

    assert bridge.command == "configure_reference_track"
    assert bridge.args == {
        "track_guid": "{REFERENCE}",
        "hardware_output_pair": 1,
        "volume": 0.5,
        "pan": 0.0,
    }
    assert bridge.options == CommandOptions(
        mutates_project=True,
        undo_label="Configure reference track routing",
    )
    assert result["master_send_enabled"] is False
    assert result["hardware_output"]["destination_channels"] == "1/2"


async def test_routing_service_rejects_invalid_reference_output_pair() -> None:
    bridge = FakeBridgeClient(BridgeResponse(id="request-1", ok=True, result={}))

    result = await RoutingService(bridge).configure_reference_track(
        "{REFERENCE}",
        hardware_output_pair=0,
    )

    assert bridge.command is None
    assert result["error"]["code"] == "invalid_send_request"
