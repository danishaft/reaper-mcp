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
from reaper_mcp.models.mastering import (
    MasteringIntent,
    MasteringPlan,
    MasteringSession,
    MasteringSource,
    SetMasteringFxParameter,
    VerifiedMasteringPlanApplication,
)
from reaper_mcp.services.mastering_candidate_service import (
    MasteringCandidateService,
)

MASTER_GUID = "{MASTER-GUID}"
CHAIN_HASH = "c" * 64


def measurement(path: Path, source_sha256: str) -> AudioMeasurementResult:
    return AudioMeasurementResult(
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
            integrated_lufs=-12.0,
            momentary_max_lufs=-8.0,
            short_term_max_lufs=-10.0,
            loudness_range_lu=6.0,
        ),
        peaks=PeakMeasurement(
            sample_peak_dbfs=-1.2,
            true_peak_dbtp=-1.0,
        ),
        dynamics=DynamicsMeasurement(peak_to_loudness_ratio_db=11.0),
        stereo=StereoMeasurement(channel_layout="stereo"),
        quality=AudioMeasurementQuality(
            complete_loudness_metrics=True,
            sample_peak_available=True,
            true_peak_available=True,
            loudness_range_stable=True,
            source_integrity_verified=True,
        ),
    )


def plan_and_application(source: Path) -> tuple[dict, dict]:
    session = MasteringSession(
        session_id="ms_" + "a" * 24,
        source=MasteringSource(
            workflow_mode="stereo_mix",
            measurement=measurement(source, "a" * 64),
        ),
        intent=MasteringIntent(desired_outcome="Controlled and open"),
    )
    operation = SetMasteringFxParameter(
        action="set_parameter",
        fx_identity={
            "track_guid": MASTER_GUID,
            "index": 0,
            "expected_identity": f"{MASTER_GUID}:0:{{FX-GUID}}",
            "expected_name": "VST3: Limiter",
            "expected_guid": "{FX-GUID}",
        },
        parameter_index=2,
        expected_parameter_name="Threshold",
        normalized_value=0.42,
        rationale="Control transients",
        expected_effect="Lower peaks",
    )
    plan = MasteringPlan(
        plan_id="mp_" + "b" * 24,
        session=session,
        master_track_guid=MASTER_GUID,
        source_sha256="a" * 64,
        project_snapshot_sha256="b" * 64,
        master_chain_sha256="d" * 64,
        operations=[operation],
        approval_hash="e" * 64,
    )
    application = VerifiedMasteringPlanApplication(
        approval_hash=plan.approval_hash,
        master_track_guid=MASTER_GUID,
        applied_operation_count=1,
        fx=[
            {
                "identity": f"{MASTER_GUID}:0:{{FX-GUID}}",
                "track_guid": MASTER_GUID,
                "index": 0,
                "name": "VST3: Limiter",
                "enabled": True,
                "offline": False,
                "guid": "{FX-GUID}",
            }
        ],
        fx_count=1,
        changes_applied=True,
        master_chain_sha256=CHAIN_HASH,
    )
    return plan.model_dump(mode="json"), application.model_dump(mode="json")


class FakePlanService:
    def __init__(self, chain_hash: str = CHAIN_HASH) -> None:
        self.chain_hash = chain_hash

    async def current_master_chain_fingerprint(self, master_track_guid: str) -> dict:
        return {
            "ok": True,
            "master_chain_sha256": self.chain_hash,
            "warnings": [],
        }


class FakeRenderService:
    def __init__(self, output_path: Path) -> None:
        self.output_path = output_path
        self.calls = 0

    async def render_project(self, output_path: str, overwrite: bool) -> dict:
        self.calls += 1
        assert output_path == str(self.output_path)
        assert overwrite is False
        return {
            "ok": True,
            "render": {
                "scope": "project",
                "status": "completed",
                "primary_output_path": output_path,
                "output_files": [
                    {"path": output_path, "size_bytes": 2048, "exists": True}
                ],
                "output_file_count": 1,
                "transaction": {
                    "settings_restored": True,
                    "dirty_state_before": False,
                    "dirty_state_after": False,
                    "dirty_state_preserved": True,
                    "trace": [
                        {"stage": "render_external_started", "elapsed_ms": 0},
                        {"stage": "render_external_returned", "elapsed_ms": 1},
                        {"stage": "transaction_verified", "elapsed_ms": 2},
                    ],
                },
            },
            "warnings": [],
        }


class FakeMeasurementService:
    def __init__(self, output_path: Path) -> None:
        self.output_path = output_path

    async def measure_file(self, output_path: str) -> dict:
        return {
            "ok": True,
            "measurement": measurement(
                self.output_path,
                "f" * 64,
            ).model_dump(mode="json"),
            "warnings": [],
        }


async def test_candidate_renders_and_measures_actual_output(tmp_path: Path) -> None:
    source = tmp_path / "mix.wav"
    output = tmp_path / "candidate.wav"
    plan, application = plan_and_application(source)
    renderer = FakeRenderService(output)

    result = await MasteringCandidateService(
        FakePlanService(),
        renderer,
        FakeMeasurementService(output),
    ).create_candidate(
        plan,
        application,
        str(output),
        "Candidate A",
        engineer_notes=["Listen for vocal edge"],
    )

    assert result["ok"] is True
    candidate = result["candidate"]
    assert candidate["state"] == "verified"
    assert candidate["approval_state"] == "pending"
    assert candidate["rendered_sha256"] == "f" * 64
    assert candidate["measurement"]["path"] == str(output)
    assert renderer.calls == 1


async def test_candidate_rejects_changed_master_chain(tmp_path: Path) -> None:
    source = tmp_path / "mix.wav"
    output = tmp_path / "candidate.wav"
    plan, application = plan_and_application(source)
    renderer = FakeRenderService(output)

    result = await MasteringCandidateService(
        FakePlanService("0" * 64),
        renderer,
        FakeMeasurementService(output),
    ).create_candidate(plan, application, str(output), "Candidate A")

    assert result["ok"] is False
    assert result["error"]["code"] == ErrorCode.MASTERING_PLAN_STALE
    assert renderer.calls == 0
