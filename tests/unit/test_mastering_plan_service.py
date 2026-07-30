import hashlib
from pathlib import Path

from reaper_mcp.errors import ErrorCode
from reaper_mcp.models.audio_measurement import (
    AudioMeasurementBackendInfo,
    AudioMeasurementBounds,
    AudioMeasurementQuality,
    AudioMeasurementResult,
    DynamicsMeasurement,
    LoudnessMeasurement,
    PeakMeasurement,
    StereoMeasurement,
)
from reaper_mcp.models.bridge import BridgeResponse, CommandOptions
from reaper_mcp.models.mastering import (
    MasteringIntent,
    MasteringSession,
    MasteringSource,
)
from reaper_mcp.services.mastering_plan_service import MasteringPlanService

MASTER_GUID = "{MASTER-GUID}"
FX_GUID = "{FX-GUID}"
FX_IDENTITY = f"{MASTER_GUID}:0:{FX_GUID}"


def session_payload(path: Path) -> dict:
    source_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    measurement = AudioMeasurementResult(
        path=path,
        source_sha256=source_sha256,
        standard="ITU-R BS.1770-4 / EBU R128",
        backend=AudioMeasurementBackendInfo(
            name="ffmpeg_ebur128",
            executable_path=Path("/usr/bin/ffmpeg"),
            version="6.1.1",
        ),
        bounds=AudioMeasurementBounds(
            start_seconds=0.0,
            measured_duration_seconds=180.0,
        ),
        loudness=LoudnessMeasurement(
            integrated_lufs=-16.0,
            momentary_max_lufs=-11.0,
            short_term_max_lufs=-13.0,
            loudness_range_lu=7.0,
        ),
        peaks=PeakMeasurement(
            sample_peak_dbfs=-2.0,
            true_peak_dbtp=-1.5,
        ),
        dynamics=DynamicsMeasurement(peak_to_loudness_ratio_db=14.5),
        stereo=StereoMeasurement(channel_layout="stereo"),
        quality=AudioMeasurementQuality(
            complete_loudness_metrics=True,
            sample_peak_available=True,
            true_peak_available=True,
            loudness_range_stable=True,
            source_integrity_verified=True,
        ),
    )
    return MasteringSession(
        session_id="ms_" + "a" * 24,
        source=MasteringSource(
            workflow_mode="stereo_mix",
            measurement=measurement,
        ),
        intent=MasteringIntent(desired_outcome="Preserve the approved mix"),
    ).model_dump(mode="json")


def operation(parameter_name: str = "Threshold") -> dict:
    return {
        "action": "set_parameter",
        "fx_identity": {
            "track_guid": MASTER_GUID,
            "index": 0,
            "expected_identity": FX_IDENTITY,
            "expected_name": "VST3: Limiter",
            "expected_guid": FX_GUID,
        },
        "parameter_index": 2,
        "expected_parameter_name": parameter_name,
        "normalized_value": 0.42,
        "rationale": "Control the loudest transients",
        "expected_effect": "Lower peaks without changing the mix balance",
    }


class FakeFxService:
    async def list_track_fx(self, track_guid: str) -> dict:
        return {
            "ok": True,
            "track_guid": track_guid,
            "fx": [
                {
                    "identity": FX_IDENTITY,
                    "track_guid": MASTER_GUID,
                    "index": 0,
                    "name": "VST3: Limiter",
                    "enabled": True,
                    "offline": False,
                    "guid": FX_GUID,
                    "fx_identity": {
                        "track_guid": MASTER_GUID,
                        "index": 0,
                        "expected_identity": FX_IDENTITY,
                        "expected_name": "VST3: Limiter",
                        "expected_guid": FX_GUID,
                    },
                }
            ],
            "fx_count": 1,
            "warnings": [],
        }

    async def get_fx_parameters(self, fx_identity: dict) -> dict:
        return {
            "ok": True,
            "fx_identity": fx_identity,
            "parameters": [
                {
                    "index": 2,
                    "name": "Threshold",
                    "normalized_value": 0.5,
                    "formatted_value": "-3.0 dB",
                }
            ],
            "parameter_count": 1,
            "warnings": [],
        }


class FakeProjectService:
    async def get_master_track(self) -> dict:
        return {
            "ok": True,
            "master_track": {
                "guid": MASTER_GUID,
                "volume": 1.0,
                "pan": 0.0,
                "mute": False,
            },
            "warnings": [],
        }

    async def get_project_snapshot(self) -> dict:
        return {
            "ok": True,
            "snapshot": {
                "project": {
                    "path": "/sessions/master.rpp",
                    "name": "Master",
                    "dirty": False,
                    "state_change_count": 7,
                }
            },
            "warnings": [],
        }


class FakeBridgeClient:
    def __init__(self, response: BridgeResponse | None = None) -> None:
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
        assert self.response is not None
        return self.response


def service(bridge: FakeBridgeClient | None = None) -> MasteringPlanService:
    return MasteringPlanService(
        bridge or FakeBridgeClient(),
        FakeFxService(),
        FakeProjectService(),
    )


async def test_preview_plan_binds_current_source_project_chain_and_parameters(
    tmp_path: Path,
) -> None:
    source = tmp_path / "mix.wav"
    source.write_bytes(b"approved mix")
    plan_service = service()

    first = await plan_service.preview_plan(
        session_payload(source),
        MASTER_GUID,
        [operation()],
    )
    second = await plan_service.preview_plan(
        session_payload(source),
        MASTER_GUID,
        [operation()],
    )

    assert first["ok"] is True
    plan = first["plan"]
    assert plan["approval_hash"] == second["plan"]["approval_hash"]
    assert plan["plan_id"] == f"mp_{plan['approval_hash'][:24]}"
    assert plan["source_sha256"] == hashlib.sha256(b"approved mix").hexdigest()
    assert len(plan["project_snapshot_sha256"]) == 64
    assert len(plan["master_chain_sha256"]) == 64


async def test_preview_plan_normalizes_public_fx_operation_type(tmp_path: Path) -> None:
    source = tmp_path / "mix.wav"
    source.write_bytes(b"approved mix")
    public_operation = {
        "type": "set_fx_enabled",
        "fx_identity": operation()["fx_identity"],
        "enabled": False,
        "rationale": "Bypass the existing limiter for comparison",
        "expected_effect": "The limiter becomes bypassed without parameter changes",
    }

    result = await service().preview_plan(
        session_payload(source),
        MASTER_GUID,
        [public_operation],
    )

    assert result["ok"] is True
    assert result["plan"]["operations"][0]["action"] == "set_enabled"


async def test_preview_plan_rejects_changed_source(tmp_path: Path) -> None:
    source = tmp_path / "mix.wav"
    source.write_bytes(b"approved mix")
    session = session_payload(source)
    source.write_bytes(b"changed mix")

    result = await service().preview_plan(session, MASTER_GUID, [operation()])

    assert result["ok"] is False
    assert result["error"]["code"] == ErrorCode.MASTERING_SOURCE_CHANGED


async def test_preview_plan_rejects_non_master_owner(tmp_path: Path) -> None:
    source = tmp_path / "mix.wav"
    source.write_bytes(b"approved mix")

    result = await service().preview_plan(
        session_payload(source), "{TRACK-GUID}", [operation()]
    )

    assert result["ok"] is False
    assert result["error"]["code"] == ErrorCode.INVALID_FX_REFERENCE


async def test_preview_plan_rejects_changed_parameter_name(tmp_path: Path) -> None:
    source = tmp_path / "mix.wav"
    source.write_bytes(b"approved mix")

    result = await service().preview_plan(
        session_payload(source),
        MASTER_GUID,
        [operation(parameter_name="Ceiling")],
    )

    assert result["ok"] is False
    assert result["error"]["code"] == ErrorCode.MASTERING_PLAN_STALE


async def test_preview_plan_rejects_duplicate_parameter_writes(
    tmp_path: Path,
) -> None:
    source = tmp_path / "mix.wav"
    source.write_bytes(b"approved mix")

    result = await service().preview_plan(
        session_payload(source),
        MASTER_GUID,
        [operation(), operation()],
    )

    assert result["ok"] is False
    assert result["error"]["code"] == ErrorCode.INVALID_MASTERING_REQUEST


async def test_preview_plan_rejects_parameter_noop(tmp_path: Path) -> None:
    source = tmp_path / "mix.wav"
    source.write_bytes(b"approved mix")
    no_op = operation()
    no_op["normalized_value"] = 0.5

    result = await service().preview_plan(
        session_payload(source),
        MASTER_GUID,
        [no_op],
    )

    assert result["ok"] is False
    assert result["error"]["code"] == ErrorCode.INVALID_MASTERING_REQUEST


async def test_apply_plan_revalidates_and_uses_one_undo_transaction(
    tmp_path: Path,
) -> None:
    source = tmp_path / "mix.wav"
    source.write_bytes(b"approved mix")
    bridge = FakeBridgeClient(
        BridgeResponse(
            id="request-1",
            ok=True,
            result={
                "approval_hash": "placeholder",
                "master_track_guid": MASTER_GUID,
                "applied_operation_count": 1,
                "fx": [
                    {
                        "identity": FX_IDENTITY,
                        "track_guid": MASTER_GUID,
                        "index": 0,
                        "name": "VST3: Limiter",
                        "enabled": True,
                        "offline": False,
                        "guid": FX_GUID,
                    }
                ],
                "fx_count": 1,
                "changes_applied": True,
            },
        )
    )
    plan_service = service(bridge)
    preview = await plan_service.preview_plan(
        session_payload(source), MASTER_GUID, [operation()]
    )
    approval_hash = preview["plan"]["approval_hash"]
    bridge.response = bridge.response.model_copy(
        update={
            "result": {
                **(bridge.response.result or {}),
                "approval_hash": approval_hash,
            }
        }
    )

    result = await plan_service.apply_plan(preview["plan"], approval_hash)

    assert result["ok"] is True
    assert bridge.command == "apply_mastering_fx_plan"
    assert bridge.options == CommandOptions(
        mutates_project=True,
        undo_label="Apply approved mastering FX plan",
    )
    assert bridge.args is not None
    assert bridge.args["approval_hash"] == approval_hash
    assert result["application"]["applied_operation_count"] == 1
    assert len(result["application"]["master_chain_sha256"]) == 64


async def test_apply_plan_rejects_wrong_approval_hash(tmp_path: Path) -> None:
    source = tmp_path / "mix.wav"
    source.write_bytes(b"approved mix")
    bridge = FakeBridgeClient()
    plan_service = service(bridge)
    preview = await plan_service.preview_plan(
        session_payload(source), MASTER_GUID, [operation()]
    )

    result = await plan_service.apply_plan(preview["plan"], "0" * 64)

    assert result["ok"] is False
    assert result["error"]["code"] == ErrorCode.MASTERING_PLAN_STALE
    assert bridge.command is None
