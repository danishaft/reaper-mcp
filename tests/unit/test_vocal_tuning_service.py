from typing import Any

from reaper_mcp.errors import ErrorCode
from reaper_mcp.models.bridge import BridgeResponse, CommandOptions
from reaper_mcp.models.vocal_tuning import X42AutoTuneSettings
from reaper_mcp.services.vocal_tuning_provider import X42AutoTuneProvider
from reaper_mcp.services.vocal_tuning_service import VocalTuningService

TRACK_GUID = "{TRACK-GUID}"
ITEM_GUID = "{ITEM-GUID}"
TAKE_GUID = "{TAKE-GUID}"


def correction(
    segment_id: str = "verse-note-1",
    start_seconds: float = 12.0,
    end_seconds: float = 12.5,
) -> dict[str, Any]:
    return {
        "segment_id": segment_id,
        "start_seconds": start_seconds,
        "end_seconds": end_seconds,
        "correction_cents": -18.0,
        "observed_note_midi": 62,
        "target_note_midi": 62,
        "preserve_vibrato": True,
        "rationale": "Center the sustained note without flattening its vibrato",
    }


class FakeProjectService:
    def __init__(self) -> None:
        self.state_change_count = 7

    async def get_project_snapshot(self) -> dict[str, Any]:
        return {
            "ok": True,
            "snapshot": {
                "project": {
                    "path": "/sessions/song.rpp",
                    "name": "Song",
                    "dirty": True,
                    "state_change_count": self.state_change_count,
                },
                "tracks": [
                    {
                        "guid": TRACK_GUID,
                        "name": "AJ Lead",
                        "index": 1,
                    }
                ],
            },
            "warnings": [],
        }


class FakeMediaService:
    async def list_media_items(self) -> dict[str, Any]:
        return {
            "ok": True,
            "items": [
                {
                    "guid": ITEM_GUID,
                    "track_guid": TRACK_GUID,
                    "name": "Lead vocal",
                    "position_seconds": 10.0,
                    "length_seconds": 20.0,
                }
            ],
            "item_count": 1,
            "warnings": [],
        }


class FakeTakeService:
    def __init__(self) -> None:
        self.take_count = 1

    async def list_item_takes(self, item_guid: str) -> dict[str, Any]:
        return {
            "ok": True,
            "item_guid": item_guid,
            "takes": [
                {
                    "guid": TAKE_GUID,
                    "item_guid": ITEM_GUID,
                    "index": 0,
                    "name": "Lead vocal",
                    "is_active": True,
                    "is_midi": False,
                    "volume": 1.0,
                    "pan": 0.0,
                    "pitch_semitones": 0.0,
                    "playback_rate": 1.0,
                    "start_offset_seconds": 0.0,
                    "preserve_pitch": False,
                }
            ],
            "take_count": self.take_count,
            "active_take_guid": TAKE_GUID,
            "warnings": [],
        }


class FakeFxService:
    def __init__(self) -> None:
        self.track_fx: list[dict[str, Any]] = []
        self.current_preset_name = ""

    async def list_available_fx(self) -> dict[str, Any]:
        return {
            "ok": True,
            "fx": [
                {
                    "index": 0,
                    "name": "VST: ReaTune (Cockos)",
                    "identifier": "reatune.dll",
                },
                {
                    "index": 1,
                    "name": "LV2: x42-Autotune (Robin Gareus) (Mono)",
                    "identifier": "http://gareus.org/oss/lv2/fat1",
                },
            ],
            "fx_count": 2,
            "warnings": [],
        }

    async def list_track_fx(self, track_guid: str) -> dict[str, Any]:
        return {
            "ok": True,
            "track_guid": track_guid,
            "fx": self.track_fx,
            "fx_count": len(self.track_fx),
            "warnings": [],
        }

    async def get_fx_preset(self, fx_identity: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "fx_identity": fx_identity,
            "preset_name": self.current_preset_name,
            "changes_applied": False,
            "warnings": [],
        }

    async def get_fx_parameters(self, fx_identity: dict[str, Any]) -> dict[str, Any]:
        del fx_identity
        settings = X42AutoTuneSettings(
            root_pitch_class=10,
            scale="natural_minor",
            correction_amount=1.0,
            smoothing_seconds=0.02,
            bias=0.35,
        )
        parameters = X42AutoTuneProvider().parameter_targets(settings)
        return {
            "ok": True,
            "parameters": [
                {
                    **parameter.model_dump(mode="json"),
                    "formatted_value": "",
                    "minimum_value": None,
                    "maximum_value": None,
                    "midpoint_value": None,
                }
                for parameter in parameters
            ],
            "parameter_count": len(parameters),
            "warnings": [],
        }


class FakeBridgeClient:
    def __init__(self) -> None:
        self.response: BridgeResponse | None = None
        self.command: str | None = None
        self.args: dict[str, Any] | None = None
        self.options: CommandOptions | None = None

    async def execute(
        self,
        command: str,
        args: dict[str, Any] | None = None,
        options: CommandOptions | None = None,
    ) -> BridgeResponse:
        self.command = command
        self.args = args
        self.options = options
        assert self.response is not None
        return self.response


def service(
    bridge: FakeBridgeClient | None = None,
    fx_service: FakeFxService | None = None,
) -> tuple[VocalTuningService, FakeProjectService, FakeTakeService]:
    project = FakeProjectService()
    takes = FakeTakeService()
    return (
        VocalTuningService(
            bridge or FakeBridgeClient(),
            project,  # type: ignore[arg-type]
            FakeMediaService(),  # type: ignore[arg-type]
            takes,  # type: ignore[arg-type]
            fx_service or FakeFxService(),  # type: ignore[arg-type]
        ),
        project,
        takes,
    )


async def test_provider_discovery_reports_verified_control_paths() -> None:
    tuning_service, _, _ = service()

    result = await tuning_service.list_providers()

    assert result["ok"] is True
    providers = {provider["provider_id"]: provider for provider in result["providers"]}
    assert providers["reaper_take_pitch"]["supports_apply"] is True
    assert providers["reaper_take_pitch"]["supports_analysis"] is False
    assert providers["reatune"]["installed"] is True
    assert providers["reatune"]["supports_apply"] is True
    assert providers["reatune"]["control_mode"] == "plugin_preset"
    assert providers["x42_autotune"]["installed"] is True
    assert providers["x42_autotune"]["control_mode"] == "plugin_parameters"


def test_x42_provider_maps_b_flat_natural_minor_and_correction_controls() -> None:
    settings = X42AutoTuneSettings(
        root_pitch_class=10,
        scale="natural_minor",
        correction_amount=1.0,
        smoothing_seconds=0.02,
        bias=0.35,
    )

    targets = X42AutoTuneProvider().parameter_targets(settings)
    by_name = {target.name: target.normalized_value for target in targets}

    assert by_name["Correction"] == 1.0
    assert by_name["Filter"] == 0.0
    assert by_name["Bias"] == 0.35
    assert by_name["Tuning"] == 0.5
    note_names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    assert {name for name in note_names if by_name[name]} == {
        "C",
        "C#",
        "D#",
        "F",
        "F#",
        "G#",
        "A#",
    }


async def test_preview_and_apply_x42_plugin_plan() -> None:
    bridge = FakeBridgeClient()
    tuning_service, _, _ = service(bridge)
    settings = {
        "root_pitch_class": 10,
        "scale": "natural_minor",
        "correction_amount": 1.0,
        "smoothing_seconds": 0.02,
        "bias": 0.35,
        "tuning_hz": 440.0,
        "fast_correction": False,
        "wet": 1.0,
    }
    preview = await tuning_service.preview_plugin_plan(
        "x42_autotune",
        "creative_effect",
        TRACK_GUID,
        settings,
    )

    assert preview["ok"] is True
    plan = preview["plan"]
    assert plan["context"]["existing_fx_identity"] is None
    assert plan["target_parameters"][19]["name"] == "A#"
    bridge.response = BridgeResponse(
        id="request-1",
        ok=True,
        result={
            "approval_hash": plan["approval_hash"],
            "provider_id": "x42_autotune",
            "track_guid": TRACK_GUID,
            "track_name": "AJ Lead",
            "fx": {
                "identity": f"{TRACK_GUID}:0:{{X42-GUID}}",
                "track_guid": TRACK_GUID,
                "index": 0,
                "name": "LV2: x42-Autotune (Robin Gareus) (Mono)",
                "enabled": True,
                "offline": False,
                "guid": "{X42-GUID}",
                "identifier": "http://gareus.org/oss/lv2/fat1",
            },
            "parameters": [
                {
                    "index": target["index"],
                    "name": target["name"],
                    "normalized_value": target["normalized_value"],
                    "formatted_value": "",
                    "minimum_value": None,
                    "maximum_value": None,
                    "midpoint_value": None,
                }
                for target in plan["target_parameters"]
            ],
            "inserted": True,
            "changes_applied": True,
        },
    )

    result = await tuning_service.apply_plugin_plan(plan, plan["approval_hash"])

    assert result["ok"] is True
    assert bridge.command == "apply_vocal_tuning_plugin_plan"
    assert bridge.options == CommandOptions(
        mutates_project=True,
        undo_label="Apply x42_autotune vocal tuning",
    )
    assert bridge.args is not None
    assert bridge.args["target_parameters"][19]["name"] == "A#"
    assert result["application"]["inserted"] is True


async def test_preview_plan_is_deterministic_and_binds_current_state() -> None:
    tuning_service, _, _ = service()

    first = await tuning_service.preview_plan(
        "reaper_take_pitch",
        "transparent_repair",
        TRACK_GUID,
        ITEM_GUID,
        TAKE_GUID,
        [correction()],
    )
    second = await tuning_service.preview_plan(
        "reaper_take_pitch",
        "transparent_repair",
        TRACK_GUID,
        ITEM_GUID,
        TAKE_GUID,
        [correction()],
    )

    assert first["ok"] is True
    plan = first["plan"]
    assert plan["approval_hash"] == second["plan"]["approval_hash"]
    assert plan["plan_id"] == f"vtp_{plan['approval_hash'][:24]}"
    assert plan["context"]["state_change_count"] == 7
    assert plan["context"]["take_pitch_semitones"] == 0.0
    assert len(plan["context_sha256"]) == 64
    assert "No pitch analysis was performed" in plan["warnings"][0]


async def test_preview_plan_rejects_overlapping_segments_before_bridge() -> None:
    tuning_service, _, _ = service()

    result = await tuning_service.preview_plan(
        "reaper_take_pitch",
        "transparent_repair",
        TRACK_GUID,
        ITEM_GUID,
        TAKE_GUID,
        [
            correction("one", 12.0, 13.0),
            correction("two", 12.5, 13.5),
        ],
    )

    assert result["ok"] is False
    assert result["error"]["code"] == ErrorCode.INVALID_VOCAL_TUNING_REQUEST


async def test_preview_plan_rejects_segments_outside_item() -> None:
    tuning_service, _, _ = service()

    result = await tuning_service.preview_plan(
        "reaper_take_pitch",
        "transparent_repair",
        TRACK_GUID,
        ITEM_GUID,
        TAKE_GUID,
        [correction(start_seconds=9.9)],
    )

    assert result["ok"] is False
    assert result["error"]["code"] == ErrorCode.INVALID_VOCAL_TUNING_REQUEST


async def test_preview_plan_does_not_claim_reatune_control() -> None:
    tuning_service, _, _ = service()

    result = await tuning_service.preview_plan(
        "reatune",
        "transparent_repair",
        TRACK_GUID,
        ITEM_GUID,
        TAKE_GUID,
        [correction()],
    )

    assert result["ok"] is False
    assert result["error"]["code"] == ErrorCode.VOCAL_TUNING_PROVIDER_UNAVAILABLE
    assert result["error"]["details"]["provider"]["installed"] is True


async def test_preview_preset_plan_binds_track_and_installed_identifier() -> None:
    tuning_service, _, _ = service()

    first = await tuning_service.preview_preset_plan(
        "reatune",
        "creative_effect",
        TRACK_GUID,
        "Song - Hard Lead",
    )
    second = await tuning_service.preview_preset_plan(
        "reatune",
        "creative_effect",
        TRACK_GUID,
        "Song - Hard Lead",
    )

    assert first["ok"] is True
    plan = first["plan"]
    assert plan["approval_hash"] == second["plan"]["approval_hash"]
    assert plan["context"]["track_name"] == "AJ Lead"
    assert plan["context"]["installed_fx_identifier"] == "reatune.dll"
    assert plan["context"]["existing_fx_identity"] is None
    assert plan["preset_name"] == "Song - Hard Lead"
    assert "hidden key" in plan["warnings"][0]


async def test_preview_preset_plan_rejects_existing_reatune_after_other_fx() -> None:
    fx_service = FakeFxService()
    fx_service.track_fx = [
        {
            "identity": "VST: ReaEQ (Cockos)",
            "track_guid": TRACK_GUID,
            "index": 0,
            "name": "VST: ReaEQ (Cockos)",
            "enabled": True,
            "offline": False,
            "guid": "{EQ-GUID}",
            "identifier": "reaeq.dll",
            "latency_samples": 0,
            "gain_reduction_db": None,
            "fx_identity": {
                "track_guid": TRACK_GUID,
                "index": 0,
                "expected_identity": "VST: ReaEQ (Cockos)",
                "expected_name": "VST: ReaEQ (Cockos)",
                "expected_guid": "{EQ-GUID}",
            },
        },
        {
            "identity": "VST: ReaTune (Cockos)",
            "track_guid": TRACK_GUID,
            "index": 1,
            "name": "VST: ReaTune (Cockos)",
            "enabled": True,
            "offline": False,
            "guid": "{TUNE-GUID}",
            "identifier": "reatune.dll",
            "latency_samples": 0,
            "gain_reduction_db": None,
            "fx_identity": {
                "track_guid": TRACK_GUID,
                "index": 1,
                "expected_identity": "VST: ReaTune (Cockos)",
                "expected_name": "VST: ReaTune (Cockos)",
                "expected_guid": "{TUNE-GUID}",
            },
        },
    ]
    tuning_service, _, _ = service(fx_service=fx_service)

    result = await tuning_service.preview_preset_plan(
        "reatune",
        "transparent_repair",
        TRACK_GUID,
        "Song - Natural Lead",
    )

    assert result["ok"] is False
    assert result["error"]["code"] == ErrorCode.INVALID_VOCAL_TUNING_REQUEST
    assert result["error"]["details"]["actual_index"] == 1


async def test_apply_preset_plan_uses_one_verified_undo_transaction() -> None:
    bridge = FakeBridgeClient()
    tuning_service, _, _ = service(bridge)
    preview = await tuning_service.preview_preset_plan(
        "reatune",
        "creative_effect",
        TRACK_GUID,
        "Song - Hard Lead",
    )
    approval_hash = preview["plan"]["approval_hash"]
    bridge.response = BridgeResponse(
        id="request-1",
        ok=True,
        result={
            "approval_hash": approval_hash,
            "provider_id": "reatune",
            "track_guid": TRACK_GUID,
            "track_name": "AJ Lead",
            "fx": {
                "identity": "VST: ReaTune (Cockos)",
                "track_guid": TRACK_GUID,
                "index": 0,
                "name": "VST: ReaTune (Cockos)",
                "enabled": True,
                "offline": False,
                "guid": "{TUNE-GUID}",
                "identifier": "reatune.dll",
                "latency_samples": 0,
                "gain_reduction_db": None,
            },
            "preset_name": "Song - Hard Lead",
            "preset_index": 0,
            "preset_count": 2,
            "inserted": True,
            "changes_applied": True,
        },
    )

    result = await tuning_service.apply_preset_plan(
        preview["plan"],
        approval_hash,
    )

    assert result["ok"] is True
    assert bridge.command == "apply_vocal_tuning_preset_plan"
    assert bridge.options == CommandOptions(
        mutates_project=True,
        undo_label="Apply ReaTune preset: Song - Hard Lead",
    )
    assert bridge.args is not None
    assert bridge.args["context"]["insert_index"] == 0
    assert bridge.args["preset_name"] == "Song - Hard Lead"
    assert result["application"]["inserted"] is True


async def test_apply_plan_revalidates_and_uses_one_undo_transaction() -> None:
    bridge = FakeBridgeClient()
    tuning_service, _, _ = service(bridge)
    preview = await tuning_service.preview_plan(
        "reaper_take_pitch",
        "transparent_repair",
        TRACK_GUID,
        ITEM_GUID,
        TAKE_GUID,
        [correction()],
    )
    approval_hash = preview["plan"]["approval_hash"]
    bridge.response = BridgeResponse(
        id="request-1",
        ok=True,
        result={
            "approval_hash": approval_hash,
            "provider_id": "reaper_take_pitch",
            "applied_correction_count": 1,
            "segments": [
                {
                    "segment_id": "verse-note-1",
                    "item_guid": "{SPLIT-ITEM-GUID}",
                    "take_guid": "{SPLIT-TAKE-GUID}",
                    "start_seconds": 12.0,
                    "end_seconds": 12.5,
                    "correction_cents": -18.0,
                    "result_pitch_semitones": -0.18,
                }
            ],
            "changes_applied": True,
        },
    )

    result = await tuning_service.apply_plan(preview["plan"], approval_hash)

    assert result["ok"] is True
    assert bridge.command == "apply_vocal_tuning_plan"
    assert bridge.options == CommandOptions(
        mutates_project=True,
        undo_label="Apply approved vocal tuning plan",
    )
    assert bridge.args is not None
    assert bridge.args["context"]["item_guid"] == ITEM_GUID
    assert bridge.args["corrections"][0]["correction_cents"] == -18.0
    assert result["application"]["applied_correction_count"] == 1


async def test_apply_plan_rejects_project_changes_after_preview() -> None:
    bridge = FakeBridgeClient()
    tuning_service, project, _ = service(bridge)
    preview = await tuning_service.preview_plan(
        "reaper_take_pitch",
        "transparent_repair",
        TRACK_GUID,
        ITEM_GUID,
        TAKE_GUID,
        [correction()],
    )
    project.state_change_count += 1

    result = await tuning_service.apply_plan(
        preview["plan"],
        preview["plan"]["approval_hash"],
    )

    assert result["ok"] is False
    assert result["error"]["code"] == ErrorCode.VOCAL_TUNING_PLAN_STALE
    assert bridge.command is None
