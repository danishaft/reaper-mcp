"""Render and measure reproducible mastering candidates."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from reaper_mcp.errors import ErrorCode
from reaper_mcp.models.audio_measurement import AudioMeasurementResult
from reaper_mcp.models.bridge import ErrorResponse
from reaper_mcp.models.mastering import (
    CreateMasteringCandidateRequest,
    MasteringCandidate,
)
from reaper_mcp.models.render import RenderProjectResult
from reaper_mcp.services._bridge_result import validation_error
from reaper_mcp.services.audio_measurement_service import AudioMeasurementService
from reaper_mcp.services.mastering_plan_service import MasteringPlanService
from reaper_mcp.services.render_service import RenderService


class MasteringCandidateService:
    """Create a candidate only from current application evidence."""

    def __init__(
        self,
        plan_service: MasteringPlanService,
        render_service: RenderService,
        measurement_service: AudioMeasurementService,
    ) -> None:
        self.plan_service = plan_service
        self.render_service = render_service
        self.measurement_service = measurement_service

    async def create_candidate(
        self,
        plan: dict[str, Any],
        application: dict[str, Any],
        output_path: str,
        label: str,
        *,
        engineer_notes: list[str] | None = None,
    ) -> dict[str, Any]:
        """Render and measure one exact currently applied mastering plan."""

        try:
            request = CreateMasteringCandidateRequest(
                plan=plan,
                application=application,
                output_path=Path(output_path).expanduser().resolve(strict=False),
                label=label,
                engineer_notes=engineer_notes or [],
            )
        except ValidationError as exc:
            return validation_error(
                exc,
                ErrorCode.INVALID_MASTERING_REQUEST,
                "The mastering candidate request is invalid.",
                "Use one plan and its exact verified application evidence.",
            )
        current_chain = await self.plan_service.current_master_chain_fingerprint(
            request.plan.master_track_guid
        )
        if not current_chain["ok"]:
            return current_chain
        if (
            current_chain["master_chain_sha256"]
            != request.application.master_chain_sha256
        ):
            return self._stale(
                ErrorCode.MASTERING_PLAN_STALE,
                "The master chain changed after the approved plan was applied.",
                {
                    "expected_master_chain_sha256": (
                        request.application.master_chain_sha256
                    ),
                    "current_master_chain_sha256": current_chain["master_chain_sha256"],
                },
            )

        rendered = await self.render_service.render_project(
            str(request.output_path),
            overwrite=False,
        )
        if not rendered["ok"]:
            return rendered
        try:
            render = RenderProjectResult.model_validate(rendered["render"])
        except ValidationError as exc:
            return validation_error(
                exc,
                ErrorCode.INVALID_BRIDGE_RESPONSE,
                "The renderer returned an invalid candidate result.",
                "Inspect renderer diagnostics and retry the candidate.",
            )
        measured = await self.measurement_service.measure_file(
            render.primary_output_path
        )
        if not measured["ok"]:
            return measured
        try:
            measurement = AudioMeasurementResult.model_validate(measured["measurement"])
        except ValidationError as exc:
            return validation_error(
                exc,
                ErrorCode.INVALID_BRIDGE_RESPONSE,
                "The measurement service returned invalid candidate evidence.",
                "Measure the rendered candidate again.",
            )

        candidate_payload = {
            "label": request.label,
            "plan_id": request.plan.plan_id,
            "approval_hash": request.plan.approval_hash,
            "source_sha256": request.plan.source_sha256,
            "master_chain_sha256": request.application.master_chain_sha256,
            "render": render.model_dump(mode="json"),
            "rendered_sha256": measurement.source_sha256,
            "measurement": measurement.model_dump(mode="json"),
            "engineer_notes": request.engineer_notes,
        }
        fingerprint = self._canonical_sha256(candidate_payload)
        candidate = MasteringCandidate(
            candidate_id=f"mc_{fingerprint[:24]}",
            **candidate_payload,
        )
        return {
            "ok": True,
            "candidate": candidate.model_dump(mode="json"),
            "warnings": [
                *rendered.get("warnings", []),
                *measured.get("warnings", []),
            ],
        }

    @staticmethod
    def _stale(
        code: ErrorCode,
        message: str,
        details: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "ok": False,
            "error": ErrorResponse(
                code=code,
                message=message,
                details=details,
                recoverable=True,
                suggested_action="Refresh the applied plan and render again.",
            ).model_dump(mode="json"),
            "warnings": [],
        }

    @staticmethod
    def _canonical_sha256(payload: dict[str, Any]) -> str:
        encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode()
        return hashlib.sha256(encoded).hexdigest()
