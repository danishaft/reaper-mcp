"""Render safety, lifecycle, and result validation service."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from reaper_mcp.bridge.base import BridgeClient
from reaper_mcp.errors import ErrorCode
from reaper_mcp.models.bridge import BridgeResponse, CommandOptions, ErrorResponse
from reaper_mcp.models.render import (
    RenderJobStart,
    RenderJobStatus,
    RenderOutputPlan,
    RenderOutputRequest,
    RenderProjectRequest,
    RenderProjectResult,
)


class RenderService:
    """Validate render requests and manage confirmed render jobs."""

    def __init__(
        self,
        bridge_client: BridgeClient | None = None,
        *,
        allowed_render_roots: list[Path] | None = None,
        render_timeout_seconds: float = 60.0,
        render_poll_interval_seconds: float = 0.1,
        render_background_confirmed: bool = False,
    ) -> None:
        self.bridge_client = bridge_client
        self.allowed_render_roots = [
            root.expanduser().resolve() for root in (allowed_render_roots or [])
        ]
        self.render_timeout_seconds = render_timeout_seconds
        self.render_poll_interval_seconds = render_poll_interval_seconds
        self.render_background_confirmed = render_background_confirmed

    async def render_project(
        self,
        output_path: str,
        overwrite: bool = False,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Start a project render and wait for a confirmed result."""

        started = await self.start_render_project(
            output_path,
            overwrite,
            idempotency_key=idempotency_key,
        )
        if not started["ok"]:
            return started

        job = started["job"]
        deadline = time.monotonic() + self.render_timeout_seconds
        while time.monotonic() < deadline:
            status = await self.render_project_status(job["job_id"])
            if not status["ok"]:
                return status
            if status["job"]["status"] == "completed":
                return {
                    "ok": True,
                    "render": status["render"],
                    "warnings": status.get("warnings", []),
                }
            await asyncio.sleep(self.render_poll_interval_seconds)

        return self._timeout_result(job)

    async def start_render_project(
        self,
        output_path: str,
        overwrite: bool = False,
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Start a project render and return before the audio render completes."""

        if self.bridge_client is None:
            return self._missing_bridge_result()

        output_plan_result = self.validate_output_path(output_path, overwrite)
        if not output_plan_result["ok"]:
            return output_plan_result

        if not self.render_background_confirmed:
            return self._render_background_required_result()

        try:
            request = RenderProjectRequest(
                output_path=output_plan_result["render_output"]["output_path"],
                overwrite=overwrite,
                format=output_plan_result["render_output"]["format"],
            )
        except ValidationError as exc:
            return self._validation_error_result(exc)

        options = (
            CommandOptions(idempotency_key=idempotency_key) if idempotency_key else None
        )
        response = await self.bridge_client.execute(
            "render_project",
            args={
                "render_output": output_plan_result["render_output"],
                "output_path": request.output_path,
                "overwrite": request.overwrite,
                "format": request.format,
            },
            options=options,
        )
        if not response.ok:
            return self._error_result(response)

        try:
            job = RenderJobStart.model_validate(response.result or {})
        except ValidationError as exc:
            return self._invalid_payload_result(response, exc)

        return {
            "ok": True,
            "job": job.model_dump(mode="json"),
            "warnings": response.warnings,
        }

    async def render_project_status(self, job_id: str) -> dict[str, Any]:
        """Return running, completed, or failed status for a render job."""

        if self.bridge_client is None:
            return self._missing_bridge_result()
        if not job_id:
            return self._validation_error_result(
                ValueError("job_id must be a non-empty string.")
            )

        response = await self.bridge_client.get_job(job_id)
        if response is None:
            return self._job_not_found_result(job_id)

        if response.ok and (response.result or {}).get("status") == "started":
            try:
                started = RenderJobStart.model_validate(response.result or {})
            except ValidationError as exc:
                return self._invalid_payload_result(response, exc)
            status = RenderJobStatus(
                job_id=started.job_id,
                scope=started.scope,
                status="running",
                output_path=started.output_path,
                overwrite=started.overwrite,
            )
            return {"ok": True, "job": status.model_dump(mode="json")}

        if response.ok and (response.result or {}).get("status") == "running":
            try:
                running = RenderJobStatus.model_validate(response.result or {})
            except ValidationError as exc:
                return self._invalid_payload_result(response, exc)
            return {"ok": True, "job": running.model_dump(mode="json")}

        if not response.ok:
            status = RenderJobStatus(job_id=job_id, status="failed")
            return {
                "ok": False,
                "job": status.model_dump(mode="json"),
                "error": response.error.model_dump(mode="json")
                if response.error
                else None,
                "warnings": response.warnings,
            }

        try:
            result = RenderProjectResult.model_validate(response.result or {})
        except ValidationError as exc:
            return self._invalid_payload_result(response, exc)
        status = RenderJobStatus(
            job_id=job_id,
            scope=result.scope,
            status="completed",
            output_path=result.primary_output_path,
        )
        return {
            "ok": True,
            "job": status.model_dump(mode="json"),
            "render": result.model_dump(mode="json"),
            "warnings": response.warnings,
        }

    async def render_project_result(self, job_id: str) -> dict[str, Any]:
        """Return a completed render result or a structured lifecycle error."""

        status = await self.render_project_status(job_id)
        if not status["ok"]:
            return status
        if status["job"]["status"] != "completed":
            return {
                "ok": False,
                "job": status["job"],
                "error": ErrorResponse(
                    code=ErrorCode.RENDER_NOT_COMPLETE,
                    message="The render job has not completed.",
                    details={"job_id": job_id, "status": status["job"]["status"]},
                    recoverable=True,
                    suggested_action="Poll render_project_status and retry.",
                ).model_dump(mode="json"),
                "warnings": [],
            }
        return status

    def validate_output_path(
        self,
        output_path: str,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Return a validated render output plan or a structured error."""

        try:
            request = RenderOutputRequest(
                output_path=output_path,
                overwrite=overwrite,
                format="wav",
            )
        except ValidationError as exc:
            return self._validation_error_result(exc)

        resolved_output_path = (
            Path(request.output_path).expanduser().resolve(strict=False)
        )
        if not self._is_allowed_render_output(resolved_output_path):
            return self._render_output_not_allowed_result(resolved_output_path)

        parent = resolved_output_path.parent
        if resolved_output_path.suffix.lower() != ".wav":
            return self._invalid_output_path_result(
                resolved_output_path,
                "Only WAV render output paths are supported in this phase.",
            )
        if not parent.exists() or not parent.is_dir():
            return self._invalid_output_path_result(
                resolved_output_path,
                "The render output directory does not exist.",
            )
        if resolved_output_path.exists() and not resolved_output_path.is_file():
            return self._invalid_output_path_result(
                resolved_output_path,
                "The render output path exists and is not a file.",
            )
        if resolved_output_path.exists() and not request.overwrite:
            return self._invalid_output_path_result(
                resolved_output_path,
                "The render output file already exists and overwrite is false.",
                code=ErrorCode.RENDER_OUTPUT_EXISTS,
            )

        allowed_root = self._matching_allowed_root(resolved_output_path)
        if allowed_root is None:
            return self._render_output_not_allowed_result(resolved_output_path)

        plan = RenderOutputPlan(
            output_path=str(resolved_output_path),
            output_directory=str(parent),
            filename=resolved_output_path.name,
            allowed_root=str(allowed_root),
            overwrite=request.overwrite,
            format=request.format,
        )
        return {
            "ok": True,
            "render_output": plan.model_dump(mode="json"),
            "warnings": [],
        }

    def _timeout_result(self, job: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": False,
            "job": job,
            "error": ErrorResponse(
                code=ErrorCode.RENDER_TIMEOUT,
                message=(
                    "The render job did not complete before the configured timeout."
                ),
                details={
                    "job_id": job["job_id"],
                    "timeout_seconds": self.render_timeout_seconds,
                },
                recoverable=True,
                suggested_action=(
                    "Poll render_project_status or request render_project_result."
                ),
            ).model_dump(mode="json"),
            "warnings": [],
        }

    def _job_not_found_result(self, job_id: str) -> dict[str, Any]:
        return {
            "ok": False,
            "error": ErrorResponse(
                code=ErrorCode.RENDER_JOB_NOT_FOUND,
                message="The render job could not be found.",
                details={"job_id": job_id},
                recoverable=True,
                suggested_action="Start a new render job and retain its job ID.",
            ).model_dump(mode="json"),
            "warnings": [],
        }

    def _error_result(self, response: BridgeResponse) -> dict[str, Any]:
        return {
            "ok": False,
            "error": response.error.model_dump(mode="json") if response.error else None,
            "warnings": response.warnings,
        }

    def _invalid_payload_result(
        self, response: BridgeResponse, exc: ValidationError
    ) -> dict[str, Any]:
        return {
            "ok": False,
            "error": ErrorResponse(
                code=ErrorCode.INVALID_BRIDGE_RESPONSE,
                message="The Lua bridge returned an invalid render payload.",
                details={"errors": exc.errors(include_context=False)},
                recoverable=True,
                suggested_action="Restart the Lua bridge and retry the render.",
            ).model_dump(mode="json"),
            "warnings": response.warnings,
        }

    def _missing_bridge_result(self) -> dict[str, Any]:
        return {
            "ok": False,
            "error": ErrorResponse(
                code=ErrorCode.REAPER_NOT_AVAILABLE,
                message="Render execution requires a bridge client.",
                details={},
                recoverable=True,
                suggested_action="Create RenderService with a bridge client.",
            ).model_dump(mode="json"),
            "warnings": [],
        }

    def _render_background_required_result(self) -> dict[str, Any]:
        return {
            "ok": False,
            "error": ErrorResponse(
                code=ErrorCode.RENDER_BACKGROUND_REQUIRED,
                message=(
                    "Render execution requires REAPER background rendering "
                    "to be enabled and confirmed."
                ),
                details={
                    "environment_variable": ("REAPER_MCP_RENDER_BACKGROUND_CONFIRMED")
                },
                recoverable=True,
                suggested_action=(
                    "Enable Render in background in REAPER, then set "
                    "REAPER_MCP_RENDER_BACKGROUND_CONFIRMED=true."
                ),
            ).model_dump(mode="json"),
            "warnings": [],
        }

    def _validation_error_result(
        self, exc: ValidationError | ValueError
    ) -> dict[str, Any]:
        details: dict[str, Any]
        if isinstance(exc, ValidationError):
            details = {"errors": exc.errors(include_context=False)}
        else:
            details = {"error": str(exc)}
        return {
            "ok": False,
            "error": ErrorResponse(
                code=ErrorCode.INVALID_RENDER_REQUEST,
                message="The render request is invalid.",
                details=details,
                recoverable=True,
                suggested_action=(
                    "Check the render output path, overwrite flag, and job ID."
                ),
            ).model_dump(mode="json"),
            "warnings": [],
        }

    def _invalid_output_path_result(
        self,
        output_path: Path,
        message: str,
        *,
        code: ErrorCode = ErrorCode.INVALID_RENDER_REQUEST,
    ) -> dict[str, Any]:
        return {
            "ok": False,
            "error": ErrorResponse(
                code=code,
                message=message,
                details={"output_path": str(output_path)},
                recoverable=True,
                suggested_action=(
                    "Provide a file path inside an existing allowed render root."
                ),
            ).model_dump(mode="json"),
            "warnings": [],
        }

    def _render_output_not_allowed_result(self, output_path: Path) -> dict[str, Any]:
        return {
            "ok": False,
            "error": ErrorResponse(
                code=ErrorCode.RENDER_OUTPUT_NOT_ALLOWED,
                message="The render output path is outside the allowed render roots.",
                details={
                    "output_path": str(output_path),
                    "allowed_render_roots": [
                        str(root) for root in self.allowed_render_roots
                    ],
                },
                recoverable=True,
                suggested_action=(
                    "Set REAPER_MCP_ALLOWED_RENDER_ROOTS to include the render "
                    "output directory."
                ),
            ).model_dump(mode="json"),
            "warnings": [],
        }

    def _is_allowed_render_output(self, output_path: Path) -> bool:
        return self._matching_allowed_root(output_path) is not None

    def _matching_allowed_root(self, output_path: Path) -> Path | None:
        for root in self.allowed_render_roots:
            if output_path == root or output_path.is_relative_to(root):
                return root
        return None
