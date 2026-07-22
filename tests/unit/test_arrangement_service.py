from reaper_mcp.models.bridge import BridgeResponse, CommandOptions
from reaper_mcp.services.arrangement_service import ArrangementService


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


def marker_payload() -> dict:
    return {
        "id": 1,
        "name": "Verse",
        "start_seconds": 4.0,
        "color": 0,
    }


def region_payload() -> dict:
    return {
        "id": 2,
        "name": "Chorus",
        "start_seconds": 8.0,
        "end_seconds": 16.0,
        "color": 0,
    }


async def test_arrangement_service_lists_markers() -> None:
    bridge = FakeBridgeClient(
        BridgeResponse(
            id="request-1",
            ok=True,
            result={"markers": [marker_payload()], "marker_count": 1},
        )
    )
    service = ArrangementService(bridge)

    result = await service.list_markers()

    assert bridge.command == "list_markers"
    assert result["ok"] is True
    assert result["markers"] == [marker_payload()]


async def test_arrangement_service_lists_regions() -> None:
    bridge = FakeBridgeClient(
        BridgeResponse(
            id="request-1",
            ok=True,
            result={"regions": [region_payload()], "region_count": 1},
        )
    )
    service = ArrangementService(bridge)

    result = await service.list_regions()

    assert bridge.command == "list_regions"
    assert result["ok"] is True
    assert result["regions"] == [region_payload()]


async def test_arrangement_service_creates_marker_with_undo() -> None:
    bridge = FakeBridgeClient(
        BridgeResponse(
            id="request-1",
            ok=True,
            result={
                "marker": marker_payload(),
                "markers": [marker_payload()],
                "marker_count": 1,
                "changes_applied": True,
            },
        )
    )
    service = ArrangementService(bridge)

    result = await service.create_marker(
        start_seconds=4.0,
        name="Verse",
    )

    assert bridge.command == "create_marker"
    assert bridge.args == {"name": "Verse", "start_seconds": 4.0, "color": 0}
    assert bridge.options == CommandOptions(
        mutates_project=True,
        undo_label="Create marker: Verse",
    )
    assert result["marker"] == marker_payload()


async def test_arrangement_service_deletes_marker_with_guard() -> None:
    bridge = FakeBridgeClient(
        BridgeResponse(
            id="request-1",
            ok=True,
            result={
                "deleted_marker_id": 1,
                "markers": [],
                "marker_count": 0,
                "changes_applied": True,
            },
        )
    )
    service = ArrangementService(bridge)

    result = await service.delete_marker(
        marker_id=1,
        expected_name="Verse",
        expected_start_seconds=4.0,
    )

    assert bridge.command == "delete_marker"
    assert bridge.args == {
        "marker_identity": {
            "id": 1,
            "expected_name": "Verse",
            "expected_start_seconds": 4.0,
        }
    }
    assert bridge.options == CommandOptions(
        mutates_project=True,
        undo_label="Delete marker: 1",
    )
    assert result["deleted_marker_id"] == 1


async def test_arrangement_service_creates_region_with_undo() -> None:
    bridge = FakeBridgeClient(
        BridgeResponse(
            id="request-1",
            ok=True,
            result={
                "region": region_payload(),
                "regions": [region_payload()],
                "region_count": 1,
                "changes_applied": True,
            },
        )
    )
    service = ArrangementService(bridge)

    result = await service.create_region(
        start_seconds=8.0,
        end_seconds=16.0,
        name="Chorus",
    )

    assert bridge.command == "create_region"
    assert bridge.args == {
        "name": "Chorus",
        "start_seconds": 8.0,
        "end_seconds": 16.0,
        "color": 0,
    }
    assert bridge.options == CommandOptions(
        mutates_project=True,
        undo_label="Create region: Chorus",
    )
    assert result["region"] == region_payload()


async def test_arrangement_service_deletes_region_with_guard() -> None:
    bridge = FakeBridgeClient(
        BridgeResponse(
            id="request-1",
            ok=True,
            result={
                "deleted_region_id": 2,
                "regions": [],
                "region_count": 0,
                "changes_applied": True,
            },
        )
    )
    service = ArrangementService(bridge)

    result = await service.delete_region(
        region_id=2,
        expected_name="Chorus",
        expected_start_seconds=8.0,
        expected_end_seconds=16.0,
    )

    assert bridge.command == "delete_region"
    assert bridge.args == {
        "region_identity": {
            "id": 2,
            "expected_name": "Chorus",
            "expected_start_seconds": 8.0,
            "expected_end_seconds": 16.0,
        }
    }
    assert bridge.options == CommandOptions(
        mutates_project=True,
        undo_label="Delete region: 2",
    )
    assert result["deleted_region_id"] == 2


async def test_arrangement_service_rejects_negative_marker_position() -> None:
    bridge = FakeBridgeClient(BridgeResponse(id="request-1", ok=True, result={}))
    service = ArrangementService(bridge)

    result = await service.create_marker(start_seconds=-1.0)

    assert bridge.command is None
    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_marker_request"


async def test_arrangement_service_rejects_region_with_non_positive_duration() -> None:
    bridge = FakeBridgeClient(BridgeResponse(id="request-1", ok=True, result={}))
    service = ArrangementService(bridge)

    result = await service.create_region(
        start_seconds=8.0,
        end_seconds=8.0,
    )

    assert bridge.command is None
    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_region_request"


async def test_arrangement_service_rejects_invalid_region_delete_guard() -> None:
    bridge = FakeBridgeClient(BridgeResponse(id="request-1", ok=True, result={}))
    service = ArrangementService(bridge)

    result = await service.delete_region(
        region_id=2,
        expected_start_seconds=16.0,
        expected_end_seconds=8.0,
    )

    assert bridge.command is None
    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_region_request"
