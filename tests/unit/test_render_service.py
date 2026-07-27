from pathlib import Path

import pytest

from reaper_mcp.models.bridge import BridgeResponse
from reaper_mcp.models.render import RenderOutputFile, RenderResult
from reaper_mcp.services.render_service import RenderService


class FakeBridgeClient:
    def __init__(
        self,
        response: BridgeResponse,
        job_response: BridgeResponse | None = None,
    ) -> None:
        self.response = response
        self.job_response = job_response
        self.command: str | None = None
        self.args: dict | None = None
        self.options = None

    async def execute(
        self,
        command: str,
        args: dict | None = None,
        options=None,
    ) -> BridgeResponse:
        self.command = command
        self.args = args
        self.options = options
        return self.response

    async def get_job(self, job_id: str) -> BridgeResponse | None:
        return self.job_response


def test_render_service_validates_output_inside_allowed_root(tmp_path: Path) -> None:
    output_path = tmp_path / "mix.wav"
    service = RenderService(allowed_render_roots=[tmp_path])

    result = service.validate_output_path(str(output_path))

    assert result["ok"] is True
    assert result["render_output"] == {
        "output_path": str(output_path.resolve()),
        "output_directory": str(tmp_path.resolve()),
        "filename": "mix.wav",
        "allowed_root": str(tmp_path.resolve()),
        "overwrite": False,
        "format": "wav",
    }


def test_render_service_requires_explicit_allowed_render_root(tmp_path: Path) -> None:
    output_path = tmp_path / "mix.wav"
    service = RenderService()

    result = service.validate_output_path(str(output_path))

    assert result["ok"] is False
    assert result["error"]["code"] == "render_output_not_allowed"


def test_render_service_rejects_output_outside_allowed_roots(
    tmp_path: Path,
) -> None:
    allowed_root = tmp_path / "allowed"
    blocked_root = tmp_path / "blocked"
    allowed_root.mkdir()
    blocked_root.mkdir()
    service = RenderService(allowed_render_roots=[allowed_root])

    result = service.validate_output_path(str(blocked_root / "mix.wav"))

    assert result["ok"] is False
    assert result["error"]["code"] == "render_output_not_allowed"


def test_render_service_rejects_existing_file_without_overwrite(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "mix.wav"
    output_path.write_bytes(b"RIFF")
    service = RenderService(allowed_render_roots=[tmp_path])

    result = service.validate_output_path(str(output_path))

    assert result["ok"] is False
    assert result["error"]["code"] == "render_output_exists"


def test_render_service_allows_existing_file_with_overwrite(tmp_path: Path) -> None:
    output_path = tmp_path / "mix.wav"
    output_path.write_bytes(b"RIFF")
    service = RenderService(allowed_render_roots=[tmp_path])

    result = service.validate_output_path(str(output_path), overwrite=True)

    assert result["ok"] is True
    assert result["render_output"]["overwrite"] is True


def test_render_service_rejects_non_wav_output_path(tmp_path: Path) -> None:
    output_path = tmp_path / "mix.mp3"
    service = RenderService(allowed_render_roots=[tmp_path])

    result = service.validate_output_path(str(output_path))

    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_render_request"


async def test_render_service_renders_project_to_allowed_output(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "mix.wav"
    bridge = FakeBridgeClient(
        BridgeResponse(
            id="request-1",
            ok=True,
            result={
                "job_id": "job-1",
                "scope": "project",
                "status": "started",
                "output_path": str(output_path.resolve()),
                "overwrite": False,
            },
        ),
        BridgeResponse(
            id="job-1",
            ok=True,
            result={
                "scope": "project",
                "status": "completed",
                "primary_output_path": str(output_path.resolve()),
                "output_files": [
                    {
                        "path": str(output_path.resolve()),
                        "size_bytes": 128,
                        "exists": True,
                    }
                ],
                "output_file_count": 1,
                "render_stats": "",
                "render_stats_summary": "",
                "transaction": {
                    "settings_restored": True,
                    "dirty_state_before": False,
                    "dirty_state_after": False,
                    "dirty_state_preserved": True,
                    "output_overwritten": False,
                    "trace": [
                        {"stage": "render_42230_started", "elapsed_ms": 0},
                        {"stage": "render_42230_returned", "elapsed_ms": 1},
                        {"stage": "transaction_verified", "elapsed_ms": 1},
                    ],
                },
            },
        ),
    )
    service = RenderService(
        bridge,
        allowed_render_roots=[tmp_path],
        render_background_confirmed=True,
    )

    result = await service.render_project(str(output_path))

    assert bridge.command == "render_project"
    assert bridge.args == {
        "render_output": {
            "output_path": str(output_path.resolve()),
            "output_directory": str(tmp_path.resolve()),
            "filename": "mix.wav",
            "allowed_root": str(tmp_path.resolve()),
            "overwrite": False,
            "format": "wav",
        },
        "output_path": str(output_path.resolve()),
        "overwrite": False,
        "format": "wav",
    }
    assert bridge.options is None
    assert result["ok"] is True
    assert result["render"]["output_files"][0]["size_bytes"] == 128


async def test_render_service_uses_isolated_reaper_process(tmp_path: Path) -> None:
    output_path = tmp_path / "isolated.wav"
    executable = tmp_path / "fake_reaper.py"
    executable.write_text(
        "import sys\n"
        "from pathlib import Path\n"
        "snapshot = Path(sys.argv[-1])\n"
        "(snapshot.parent / 'isolated.wav').write_bytes(b'RIFF')\n",
        encoding="utf-8",
    )
    bridge = FakeBridgeClient(
        BridgeResponse(
            id="request-1",
            ok=True,
            result={
                "status": "prepared",
                "transaction": {
                    "settings_restored": True,
                    "dirty_state_before": False,
                    "dirty_state_after": False,
                    "dirty_state_preserved": True,
                    "output_overwritten": False,
                    "trace": [
                        {"stage": "snapshot_captured", "elapsed_ms": 0},
                        {"stage": "snapshot_saved", "elapsed_ms": 1},
                    ],
                },
            },
        )
    )
    service = RenderService(
        bridge,
        allowed_render_roots=[tmp_path],
        external_render_enabled=True,
        reaper_executable=executable,
    )

    result = await service.render_project(str(output_path))

    assert result["ok"] is True
    assert output_path.read_bytes() == b"RIFF"
    assert {point["stage"] for point in result["render"]["transaction"]["trace"]} >= {
        "render_external_started",
        "render_external_returned",
        "transaction_verified",
    }

    overwritten = await service.render_project(str(output_path), overwrite=True)

    assert overwritten["ok"] is True
    assert overwritten["render"]["transaction"]["output_overwritten"] is True


async def test_render_service_returns_timeout_then_accepts_late_completion(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "late.wav"
    bridge = FakeBridgeClient(
        BridgeResponse(
            id="request-1",
            ok=True,
            result={
                "job_id": "job-late",
                "scope": "project",
                "status": "started",
                "output_path": str(output_path.resolve()),
                "overwrite": False,
            },
        ),
        BridgeResponse(
            id="job-late",
            ok=True,
            result={
                "job_id": "job-late",
                "scope": "project",
                "status": "started",
                "output_path": str(output_path.resolve()),
                "overwrite": False,
            },
        ),
    )
    service = RenderService(
        bridge,
        allowed_render_roots=[tmp_path],
        render_timeout_seconds=0.001,
        render_poll_interval_seconds=0.001,
        render_background_confirmed=True,
    )

    timed_out = await service.render_project(str(output_path))

    assert timed_out["ok"] is False
    assert timed_out["error"]["code"] == "render_timeout"
    assert timed_out["job"]["job_id"] == "job-late"

    bridge.job_response = BridgeResponse(
        id="job-late",
        ok=True,
        result={
            "scope": "project",
            "status": "completed",
            "primary_output_path": str(output_path.resolve()),
            "output_files": [
                {
                    "path": str(output_path.resolve()),
                    "size_bytes": 64,
                    "exists": True,
                }
            ],
            "output_file_count": 1,
            "transaction": {
                "settings_restored": True,
                "dirty_state_before": True,
                "dirty_state_after": True,
                "dirty_state_preserved": True,
                "trace": [
                    {"stage": "render_42230_started", "elapsed_ms": 0},
                    {"stage": "render_42230_returned", "elapsed_ms": 1},
                    {"stage": "transaction_verified", "elapsed_ms": 2},
                ],
            },
        },
    )

    late_result = await service.render_project_result("job-late")

    assert late_result["ok"] is True
    assert late_result["render"]["transaction"]["dirty_state_preserved"] is True


async def test_render_service_rejects_unrestored_completed_payload(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "invalid.wav"
    bridge = FakeBridgeClient(
        BridgeResponse(
            id="request-1",
            ok=True,
            result={
                "job_id": "job-invalid",
                "scope": "project",
                "status": "started",
                "output_path": str(output_path.resolve()),
            },
        ),
        BridgeResponse(
            id="job-invalid",
            ok=True,
            result={
                "scope": "project",
                "status": "completed",
                "primary_output_path": str(output_path.resolve()),
                "output_files": [
                    {
                        "path": str(output_path.resolve()),
                        "size_bytes": 1,
                        "exists": True,
                    }
                ],
                "output_file_count": 1,
                "transaction": {
                    "settings_restored": False,
                    "dirty_state_before": False,
                    "dirty_state_after": True,
                    "dirty_state_preserved": False,
                    "trace": [{"stage": "settings_restore_started", "elapsed_ms": 1}],
                },
            },
        ),
    )
    service = RenderService(
        bridge,
        allowed_render_roots=[tmp_path],
        render_background_confirmed=True,
    )

    result = await service.render_project_result("job-invalid")

    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_bridge_response"


async def test_render_service_rejects_project_output_before_bridge(
    tmp_path: Path,
) -> None:
    allowed_root = tmp_path / "allowed"
    blocked_root = tmp_path / "blocked"
    allowed_root.mkdir()
    blocked_root.mkdir()
    output_path = blocked_root / "mix.wav"
    bridge = FakeBridgeClient(BridgeResponse(id="request-1", ok=True, result={}))
    service = RenderService(bridge, allowed_render_roots=[allowed_root])

    result = await service.render_project(str(output_path))

    assert bridge.command is None
    assert result["ok"] is False
    assert result["error"]["code"] == "render_output_not_allowed"


def test_render_output_file_rejects_empty_completed_artifact() -> None:
    with pytest.raises(ValueError):
        RenderOutputFile(path="/tmp/empty.wav", size_bytes=0, exists=True)


def test_render_result_requires_completed_status() -> None:
    with pytest.raises(ValueError):
        RenderResult(
            scope="project",
            status="running",
            primary_output_path="/tmp/render.wav",
            output_files=[{"path": "/tmp/render.wav", "size_bytes": 1, "exists": True}],
            output_file_count=1,
            transaction={
                "settings_restored": True,
                "dirty_state_before": False,
                "dirty_state_after": False,
                "dirty_state_preserved": True,
                "trace": [
                    {"stage": "render_42230_started", "elapsed_ms": 0},
                    {"stage": "render_42230_returned", "elapsed_ms": 1},
                    {"stage": "transaction_verified", "elapsed_ms": 2},
                ],
            },
        )


async def test_render_service_passes_idempotency_key_to_bridge(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "idempotent.wav"
    bridge = FakeBridgeClient(
        BridgeResponse(
            id="request-1",
            ok=True,
            result={
                "job_id": "job-1",
                "scope": "project",
                "status": "started",
                "output_path": str(output_path.resolve()),
                "overwrite": False,
            },
        )
    )
    service = RenderService(
        bridge,
        allowed_render_roots=[tmp_path],
        render_background_confirmed=True,
    )

    result = await service.start_render_project(
        str(output_path),
        idempotency_key="render-once",
    )

    assert result["ok"] is True
    assert bridge.options is not None
    assert bridge.options.idempotency_key == "render-once"


async def test_render_service_requires_background_confirmation_before_bridge(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "blocked.wav"
    bridge = FakeBridgeClient(BridgeResponse(id="request-1", ok=True, result={}))
    service = RenderService(bridge, allowed_render_roots=[tmp_path])

    result = await service.start_render_project(str(output_path))

    assert result["ok"] is False
    assert result["error"]["code"] == "render_background_required"
    assert bridge.command is None
