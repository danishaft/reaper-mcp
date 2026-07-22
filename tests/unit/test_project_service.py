from reaper_mcp.models.bridge import BridgeResponse, CommandOptions
from reaper_mcp.services.project_service import ProjectService


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


def track_mutation_response(**track_state: object) -> BridgeResponse:
    track = {
        "guid": "{TRACK-GUID}",
        "name": "Track",
        "index": 1,
        **track_state,
    }
    return BridgeResponse(
        id="request-1",
        ok=True,
        result={"track_count": 1, "track": track, "changes_applied": True},
    )


async def test_project_service_returns_snapshot() -> None:
    bridge = FakeBridgeClient(
        BridgeResponse(
            id="request-1",
            ok=True,
            result={
                "tracks": [
                    {
                        "guid": "{TRACK-GUID}",
                        "name": "Drums",
                        "index": 1,
                    }
                ]
            },
        )
    )
    service = ProjectService(bridge)

    result = await service.get_project_snapshot()

    assert bridge.command == "get_project_snapshot"
    assert result["ok"] is True
    assert result["snapshot"]["tracks"][0]["guid"] == "{TRACK-GUID}"


async def test_project_service_lists_tracks() -> None:
    bridge = FakeBridgeClient(
        BridgeResponse(
            id="request-1",
            ok=True,
            result={
                "track_count": 1,
                "tracks": [
                    {
                        "guid": "{TRACK-GUID}",
                        "name": "Bass",
                        "index": 1,
                    }
                ],
            },
        )
    )
    service = ProjectService(bridge)

    result = await service.list_tracks()

    assert bridge.command == "list_tracks"
    assert result["ok"] is True
    assert result["track_count"] == 1
    assert result["tracks"][0]["name"] == "Bass"


async def test_project_service_creates_track_with_undo_options() -> None:
    bridge = FakeBridgeClient(
        BridgeResponse(
            id="request-1",
            ok=True,
            result={
                "track_count": 1,
                "track": {
                    "guid": "{TRACK-GUID}",
                    "name": "Keys",
                    "index": 1,
                },
            },
        )
    )
    service = ProjectService(bridge)

    result = await service.create_track(name="Keys", index=1)

    assert bridge.command == "create_track"
    assert bridge.args == {"name": "Keys", "index": 1, "dry_run": False}
    assert bridge.options == CommandOptions(
        mutates_project=True,
        undo_label="Create track: Keys",
        dry_run=False,
    )
    assert result["ok"] is True
    assert result["track"]["guid"] == "{TRACK-GUID}"


async def test_project_service_create_track_dry_run_omits_undo_label() -> None:
    bridge = FakeBridgeClient(
        BridgeResponse(
            id="request-1",
            ok=True,
            result={
                "track_count": 0,
                "dry_run": True,
                "changes_applied": False,
                "track": {
                    "guid": "",
                    "name": "Preview",
                    "index": 1,
                },
            },
        )
    )
    service = ProjectService(bridge)

    result = await service.create_track(name="Preview", dry_run=True)

    assert bridge.options == CommandOptions(mutates_project=True, dry_run=True)
    assert result["dry_run"] is True
    assert result["changes_applied"] is False


async def test_project_service_renames_track_with_guid() -> None:
    bridge = FakeBridgeClient(
        BridgeResponse(
            id="request-1",
            ok=True,
            result={
                "track_count": 1,
                "track": {
                    "guid": "{TRACK-GUID}",
                    "name": "Renamed",
                    "index": 1,
                },
            },
        )
    )
    service = ProjectService(bridge)

    result = await service.rename_track(track_guid="{TRACK-GUID}", name="Renamed")

    assert bridge.command == "rename_track"
    assert bridge.args == {"track_guid": "{TRACK-GUID}", "name": "Renamed"}
    assert bridge.options == CommandOptions(
        mutates_project=True,
        undo_label="Rename track: Renamed",
    )
    assert result["track"]["name"] == "Renamed"


async def test_project_service_sets_track_color_with_undo() -> None:
    bridge = FakeBridgeClient(track_mutation_response(color=0x224466))
    service = ProjectService(bridge)

    result = await service.set_track_color("{TRACK-GUID}", 0x224466)

    assert bridge.command == "set_track_color"
    assert bridge.args == {"track_guid": "{TRACK-GUID}", "color": 0x224466}
    assert bridge.options == CommandOptions(
        mutates_project=True,
        undo_label="Set track color",
    )
    assert result["track"]["color"] == 0x224466


async def test_project_service_sets_track_mute_with_undo() -> None:
    bridge = FakeBridgeClient(track_mutation_response(mute=True))
    service = ProjectService(bridge)

    result = await service.set_track_mute("{TRACK-GUID}", True)

    assert bridge.command == "set_track_mute"
    assert bridge.args == {"track_guid": "{TRACK-GUID}", "muted": True}
    assert bridge.options == CommandOptions(
        mutates_project=True,
        undo_label="Set track mute",
    )
    assert result["track"]["mute"] is True


async def test_project_service_sets_track_solo_with_undo() -> None:
    bridge = FakeBridgeClient(track_mutation_response(solo=True))
    service = ProjectService(bridge)

    result = await service.set_track_solo("{TRACK-GUID}", True)

    assert bridge.command == "set_track_solo"
    assert bridge.args == {"track_guid": "{TRACK-GUID}", "soloed": True}
    assert bridge.options == CommandOptions(
        mutates_project=True,
        undo_label="Set track solo",
    )
    assert result["track"]["solo"] is True


async def test_project_service_sets_track_arm_with_undo() -> None:
    bridge = FakeBridgeClient(track_mutation_response(armed=True))
    service = ProjectService(bridge)

    result = await service.set_track_arm("{TRACK-GUID}", True)

    assert bridge.command == "set_track_arm"
    assert bridge.args == {"track_guid": "{TRACK-GUID}", "armed": True}
    assert bridge.options == CommandOptions(
        mutates_project=True,
        undo_label="Set track record arm",
    )
    assert result["track"]["armed"] is True


async def test_project_service_sets_track_volume_and_pan_with_undo() -> None:
    volume_bridge = FakeBridgeClient(track_mutation_response(volume=0.5))
    pan_bridge = FakeBridgeClient(track_mutation_response(pan=-0.25))

    volume_result = await ProjectService(volume_bridge).set_track_volume(
        "{TRACK-GUID}", 0.5
    )
    pan_result = await ProjectService(pan_bridge).set_track_pan("{TRACK-GUID}", -0.25)

    assert volume_bridge.command == "set_track_volume"
    assert volume_bridge.args == {"track_guid": "{TRACK-GUID}", "volume": 0.5}
    assert volume_bridge.options == CommandOptions(
        mutates_project=True,
        undo_label="Set track volume",
    )
    assert volume_result["track"]["volume"] == 0.5
    assert pan_bridge.command == "set_track_pan"
    assert pan_bridge.args == {"track_guid": "{TRACK-GUID}", "pan": -0.25}
    assert pan_result["track"]["pan"] == -0.25


async def test_project_service_rejects_invalid_track_pan_before_bridge() -> None:
    bridge = FakeBridgeClient(track_mutation_response())

    result = await ProjectService(bridge).set_track_pan("{TRACK-GUID}", 1.1)

    assert bridge.command is None
    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_track_request"


async def test_project_service_reads_and_mutates_master_track() -> None:
    snapshot = {
        "guid": "{MASTER-GUID}",
        "volume": 0.75,
        "pan": 0.1,
        "mute": False,
    }
    read_bridge = FakeBridgeClient(
        BridgeResponse(id="request-1", ok=True, result=snapshot)
    )
    mutation_bridge = FakeBridgeClient(
        BridgeResponse(
            id="request-2",
            ok=True,
            result={
                "master_track": {**snapshot, "mute": True},
                "changes_applied": True,
            },
        )
    )

    read_result = await ProjectService(read_bridge).get_master_track()
    mute_result = await ProjectService(mutation_bridge).set_master_mute(True)

    assert read_bridge.command == "get_master_track"
    assert read_result["master_track"]["volume"] == 0.75
    assert mutation_bridge.command == "set_master_mute"
    assert mutation_bridge.args == {"muted": True}
    assert mutation_bridge.options == CommandOptions(
        mutates_project=True,
        undo_label="Set master mute",
    )
    assert mute_result["master_track"]["mute"] is True


async def test_project_service_sets_master_volume_and_pan() -> None:
    volume_bridge = FakeBridgeClient(
        BridgeResponse(
            id="request-1",
            ok=True,
            result={
                "master_track": {"volume": 0.8},
                "changes_applied": True,
            },
        )
    )
    pan_bridge = FakeBridgeClient(
        BridgeResponse(
            id="request-2",
            ok=True,
            result={
                "master_track": {"pan": 0.2},
                "changes_applied": True,
            },
        )
    )

    volume_result = await ProjectService(volume_bridge).set_master_volume(0.8)
    pan_result = await ProjectService(pan_bridge).set_master_pan(0.2)

    assert volume_bridge.args == {"volume": 0.8}
    assert volume_result["master_track"]["volume"] == 0.8
    assert pan_bridge.args == {"pan": 0.2}
    assert pan_result["master_track"]["pan"] == 0.2


async def test_project_service_deletes_track_with_guid() -> None:
    bridge = FakeBridgeClient(
        BridgeResponse(
            id="request-1",
            ok=True,
            result={
                "deleted_track_guid": "{TRACK-GUID}",
                "track_count": 0,
                "changes_applied": True,
            },
        )
    )
    service = ProjectService(bridge)

    result = await service.delete_track(track_guid="{TRACK-GUID}")

    assert bridge.command == "delete_track"
    assert bridge.args == {"track_guid": "{TRACK-GUID}"}
    assert bridge.options == CommandOptions(
        mutates_project=True,
        undo_label="Delete track",
    )
    assert result["deleted_track_guid"] == "{TRACK-GUID}"
    assert result["track_count"] == 0
