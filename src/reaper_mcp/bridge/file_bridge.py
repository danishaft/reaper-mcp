"""File-based JSON bridge client for the REAPER Lua bridge."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import suppress
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from reaper_mcp.errors import ErrorCode
from reaper_mcp.models.bridge import (
    BridgeResponse,
    CommandEnvelope,
    CommandOptions,
    ErrorResponse,
)

LOGGER = logging.getLogger("reaper_mcp.bridge")
_MAX_LOGGED_TARGET_IDS = 32


class FileBridgeClient:
    """Send bridge commands through request and response JSON files."""

    def __init__(
        self,
        bridge_dir: Path,
        timeout_seconds: float,
        poll_interval_seconds: float,
        stale_after_seconds: float,
    ) -> None:
        self.bridge_dir = bridge_dir
        self.timeout_seconds = timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.stale_after_seconds = stale_after_seconds

    @property
    def requests_dir(self) -> Path:
        """Return the request directory."""

        return self.bridge_dir / "requests"

    @property
    def responses_dir(self) -> Path:
        """Return the response directory."""

        return self.bridge_dir / "responses"

    @property
    def jobs_dir(self) -> Path:
        """Return the asynchronous job directory."""

        return self.bridge_dir / "jobs"

    @property
    def heartbeat_path(self) -> Path:
        """Return the bridge heartbeat path."""

        return self.bridge_dir / "bridge.heartbeat"

    async def execute(
        self,
        command: str,
        args: dict[str, Any] | None = None,
        options: CommandOptions | None = None,
    ) -> BridgeResponse:
        """Build and send a command envelope."""

        envelope = CommandEnvelope(
            command=command,
            args=args or {},
            options=options or CommandOptions(),
        )
        return await self.send(envelope)

    async def send(self, envelope: CommandEnvelope) -> BridgeResponse:
        """Write a request file and wait for the matching response file."""

        started_at = time.monotonic()
        self._prepare_directories()
        self._cleanup_stale_files()

        request_path = self.requests_dir / f"{envelope.id}.json"
        response_path = self.responses_dir / f"{envelope.id}.json"
        self._write_json_atomic(request_path, envelope.model_dump(mode="json"))

        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            if response_path.exists():
                response = self._read_response(envelope.id, response_path)
                self._cleanup_completed_files(request_path, response_path)
                self._log_command(envelope, response, started_at)
                return response
            await asyncio.sleep(self.poll_interval_seconds)

        self._safe_unlink(request_path)
        heartbeat_is_stale = self._heartbeat_is_stale()
        if envelope.options.mutates_project:
            response = BridgeResponse(
                id=envelope.id,
                ok=False,
                error=ErrorResponse(
                    code=ErrorCode.OUTCOME_UNCERTAIN,
                    message=(
                        "The mutating command timed out after publication, so its "
                        "outcome is uncertain."
                    ),
                    details={
                        "timeout_seconds": self.timeout_seconds,
                        "heartbeat_is_stale": heartbeat_is_stale,
                    },
                    recoverable=True,
                    suggested_action=(
                        "Refresh the affected REAPER project state before deciding "
                        "whether to retry."
                    ),
                ),
            )
        elif heartbeat_is_stale:
            response = BridgeResponse(
                id=envelope.id,
                ok=False,
                error=ErrorResponse(
                    code=ErrorCode.BRIDGE_NOT_RUNNING,
                    message="The REAPER Lua bridge heartbeat is stale.",
                    details={
                        "heartbeat_path": str(self.heartbeat_path),
                        "stale_after_seconds": self.stale_after_seconds,
                    },
                    recoverable=True,
                    suggested_action="Restart the Lua bridge inside REAPER.",
                ),
            )
        else:
            response = BridgeResponse(
                id=envelope.id,
                ok=False,
                error=ErrorResponse(
                    code=ErrorCode.COMMAND_TIMEOUT,
                    message="Timed out waiting for the REAPER Lua bridge response.",
                    details={"timeout_seconds": self.timeout_seconds},
                    recoverable=True,
                    suggested_action="Confirm the Lua bridge is running in REAPER.",
                ),
            )
        self._log_command(envelope, response, started_at)
        return response

    async def get_job(self, job_id: str) -> BridgeResponse | None:
        """Read a completed asynchronous job without involving REAPER."""

        job_path = self.jobs_dir / f"{job_id}.json"
        if not job_path.exists():
            return None
        response = self._read_response(job_id, job_path)
        if response.ok and self._heartbeat_is_stale():
            result = response.result or {}
            if result.get("status") in {"started", "running"}:
                return BridgeResponse(
                    id=job_id,
                    ok=False,
                    error=ErrorResponse(
                        code=ErrorCode.BRIDGE_NOT_RUNNING,
                        message="The render bridge heartbeat is stale.",
                        details={
                            "job_id": job_id,
                            "heartbeat_path": str(self.heartbeat_path),
                        },
                        recoverable=True,
                        suggested_action=(
                            "Restart the Lua bridge and inspect the job output."
                        ),
                    ),
                )
        return response

    def _heartbeat_is_stale(self) -> bool:
        if not self.heartbeat_path.exists():
            return False
        try:
            return (
                time.time() - self.heartbeat_path.stat().st_mtime
                > self.stale_after_seconds
            )
        except OSError:
            return True

    def _prepare_directories(self) -> None:
        self.requests_dir.mkdir(parents=True, exist_ok=True)
        self.responses_dir.mkdir(parents=True, exist_ok=True)

    def _cleanup_stale_files(self) -> None:
        cutoff = time.time() - self.stale_after_seconds
        for directory in (self.requests_dir, self.responses_dir, self.jobs_dir):
            if not directory.exists():
                continue
            for path in directory.glob("*.json"):
                try:
                    if path.stat().st_mtime < cutoff:
                        path.unlink()
                except FileNotFoundError:
                    continue

    def _read_response(self, request_id: str, response_path: Path) -> BridgeResponse:
        try:
            payload = json.loads(response_path.read_text(encoding="utf-8"))
            response = BridgeResponse.model_validate(payload)
            if response.id != request_id:
                msg = (
                    f"Response id {response.id!r} does not match request id "
                    f"{request_id!r}."
                )
                raise ValueError(msg)
            return response
        except (OSError, ValueError, json.JSONDecodeError, ValidationError) as exc:
            return BridgeResponse(
                id=request_id,
                ok=False,
                error=ErrorResponse(
                    code=ErrorCode.INVALID_BRIDGE_RESPONSE,
                    message="The REAPER Lua bridge returned an invalid response.",
                    details={"response_path": str(response_path), "error": str(exc)},
                    recoverable=True,
                    suggested_action="Restart the Lua bridge and retry the command.",
                ),
            )

    def _cleanup_completed_files(self, request_path: Path, response_path: Path) -> None:
        self._safe_unlink(request_path)
        self._safe_unlink(response_path)

    def _log_command(
        self,
        envelope: CommandEnvelope,
        response: BridgeResponse,
        started_at: float,
    ) -> None:
        error_code = str(response.error.code) if response.error else None
        LOGGER.info(
            "bridge_command_completed",
            extra={
                "event": "bridge_command_completed",
                "request_id": envelope.id,
                "command": envelope.command,
                "duration_ms": round((time.monotonic() - started_at) * 1000, 3),
                "result": "ok" if response.ok else "error",
                "error_code": error_code,
                "target_ids": self._target_ids(envelope, response),
            },
        )

    def _target_ids(
        self,
        envelope: CommandEnvelope,
        response: BridgeResponse,
    ) -> dict[str, str | int]:
        targets: dict[str, str | int] = {}
        self._collect_target_ids(envelope.args, "args", targets)
        if envelope.options.mutates_project and response.ok and response.result:
            self._collect_target_ids(response.result, "result", targets)
        return targets

    def _collect_target_ids(
        self,
        value: object,
        path: str,
        targets: dict[str, str | int],
    ) -> None:
        if len(targets) >= _MAX_LOGGED_TARGET_IDS:
            return
        if isinstance(value, dict):
            for key, item in value.items():
                item_path = f"{path}.{key}"
                is_identifier = key == "guid" or key.endswith(("_guid", "_id"))
                if is_identifier and isinstance(item, (str, int)):
                    targets[item_path] = item
                elif isinstance(item, (dict, list)):
                    self._collect_target_ids(item, item_path, targets)
                if len(targets) >= _MAX_LOGGED_TARGET_IDS:
                    break
        elif isinstance(value, list):
            for index, item in enumerate(value):
                if isinstance(item, (dict, list)):
                    self._collect_target_ids(item, f"{path}[{index}]", targets)
                if len(targets) >= _MAX_LOGGED_TARGET_IDS:
                    break

    def _write_json_atomic(self, path: Path, payload: dict[str, Any]) -> None:
        temp_path = path.with_suffix(".json.tmp")
        temp_path.write_text(
            json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
            encoding="utf-8",
        )
        temp_path.replace(path)

    def _safe_unlink(self, path: Path) -> None:
        with suppress(FileNotFoundError):
            path.unlink()
