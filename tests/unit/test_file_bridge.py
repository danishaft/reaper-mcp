import asyncio
import json
import logging
import os
import time
from pathlib import Path

import pytest

from reaper_mcp.bridge.file_bridge import FileBridgeClient
from reaper_mcp.errors import ErrorCode


def make_client(tmp_path: Path, timeout_seconds: float = 1.0) -> FileBridgeClient:
    return FileBridgeClient(
        bridge_dir=tmp_path,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=0.01,
        stale_after_seconds=300.0,
    )


async def wait_for_request(path: Path) -> Path:
    deadline = asyncio.get_running_loop().time() + 1.0
    while asyncio.get_running_loop().time() < deadline:
        requests = list((path / "requests").glob("*.json"))
        if requests:
            return requests[0]
        await asyncio.sleep(0.01)
    msg = "Timed out waiting for request file."
    raise AssertionError(msg)


@pytest.mark.asyncio
async def test_file_bridge_round_trips_response(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    task = asyncio.create_task(client.execute("health_check"))
    request_path = await wait_for_request(tmp_path)
    payload = json.loads(request_path.read_text(encoding="utf-8"))

    assert payload["command"] == "health_check"
    assert payload["args"] == {}
    assert payload["options"] == {
        "mutates_project": False,
        "undo_label": None,
        "dry_run": False,
        "idempotency_key": None,
    }

    response_path = tmp_path / "responses" / f"{payload['id']}.json"
    response_path.write_text(
        json.dumps(
            {
                "id": payload["id"],
                "ok": True,
                "result": {"status": "ok", "bridge_version": "0.1.0"},
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )

    response = await task

    assert response.ok is True
    assert response.result == {"status": "ok", "bridge_version": "0.1.0"}
    assert not request_path.exists()
    assert not response_path.exists()


@pytest.mark.asyncio
async def test_file_bridge_logs_structured_command_result(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="reaper_mcp.bridge")
    client = make_client(tmp_path)
    task = asyncio.create_task(
        client.execute("rename_track", {"track_guid": "{TRACK-1}"})
    )
    request_path = await wait_for_request(tmp_path)
    payload = json.loads(request_path.read_text(encoding="utf-8"))
    response_path = tmp_path / "responses" / f"{payload['id']}.json"
    response_path.write_text(
        json.dumps(
            {
                "id": payload["id"],
                "ok": True,
                "result": {"track_guid": "{TRACK-1}"},
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )

    await task

    record = caplog.records[-1]
    assert record.event == "bridge_command_completed"
    assert record.request_id == payload["id"]
    assert record.command == "rename_track"
    assert record.duration_ms >= 0
    assert record.result == "ok"
    assert record.error_code is None
    assert record.target_ids == {"args.track_guid": "{TRACK-1}"}


@pytest.mark.asyncio
async def test_file_bridge_times_out_with_structured_error(tmp_path: Path) -> None:
    client = make_client(tmp_path, timeout_seconds=0.02)

    response = await client.execute("health_check")

    assert response.ok is False
    assert response.error is not None
    assert response.error.code == ErrorCode.COMMAND_TIMEOUT


@pytest.mark.asyncio
async def test_file_bridge_logs_timeout_result(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="reaper_mcp.bridge")
    client = make_client(tmp_path, timeout_seconds=0.02)

    await client.execute("health_check")

    record = caplog.records[-1]
    assert record.result == "error"
    assert record.error_code == ErrorCode.COMMAND_TIMEOUT


@pytest.mark.asyncio
async def test_file_bridge_parses_invalid_envelope_error(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    task = asyncio.create_task(client.execute("health_check"))
    request_path = await wait_for_request(tmp_path)
    payload = json.loads(request_path.read_text(encoding="utf-8"))

    response_path = tmp_path / "responses" / f"{payload['id']}.json"
    response_path.write_text(
        json.dumps(
            {
                "id": payload["id"],
                "ok": False,
                "error": {
                    "code": "invalid_command_envelope",
                    "message": "Invalid command envelope.",
                    "details": {
                        "error": "Envelope command must be a non-empty string."
                    },
                    "recoverable": False,
                    "suggested_action": "Send a full command envelope.",
                },
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )

    response = await task

    assert response.ok is False
    assert response.error is not None
    assert response.error.code == ErrorCode.INVALID_COMMAND_ENVELOPE
    assert response.error.recoverable is False


@pytest.mark.asyncio
async def test_file_bridge_reports_stale_heartbeat_for_active_job(
    tmp_path: Path,
) -> None:
    client = FileBridgeClient(
        bridge_dir=tmp_path,
        timeout_seconds=1.0,
        poll_interval_seconds=0.01,
        stale_after_seconds=1.0,
    )
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    job_path = jobs_dir / "job-1.json"
    job_path.write_text(
        json.dumps(
            {
                "id": "job-1",
                "ok": True,
                "result": {
                    "job_id": "job-1",
                    "scope": "project",
                    "status": "running",
                    "output_path": str(tmp_path / "mix.wav"),
                    "overwrite": False,
                },
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )
    heartbeat = tmp_path / "bridge.heartbeat"
    heartbeat.write_text("old", encoding="utf-8")
    old_time = time.time() - 5
    os.utime(heartbeat, (old_time, old_time))

    response = await client.get_job("job-1")

    assert response is not None
    assert response.ok is False
    assert response.error is not None
    assert response.error.code == ErrorCode.BRIDGE_NOT_RUNNING
