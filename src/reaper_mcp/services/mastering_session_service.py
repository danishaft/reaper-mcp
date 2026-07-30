"""Read-only mastering session intake and source handoff."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import ValidationError

from reaper_mcp.errors import ErrorCode
from reaper_mcp.models.audio_measurement import AudioMeasurementResult
from reaper_mcp.models.bridge import ErrorResponse
from reaper_mcp.models.mastering import (
    CreateMasteringSessionRequest,
    MasteringIntent,
    MasteringProjectContext,
    MasteringSession,
    MasteringSource,
    MasteringWorkflowMode,
)
from reaper_mcp.models.project import ProjectSnapshot
from reaper_mcp.services._bridge_result import validation_error
from reaper_mcp.services.audio_measurement_service import AudioMeasurementService
from reaper_mcp.services.project_service import ProjectService


class MasteringSessionService:
    """Create a measured, fingerprinted handoff without changing REAPER."""

    def __init__(
        self,
        measurement_service: AudioMeasurementService,
        project_service: ProjectService,
    ) -> None:
        self.measurement_service = measurement_service
        self.project_service = project_service

    async def create_session(
        self,
        source_path: str,
        workflow_mode: MasteringWorkflowMode | str,
        desired_outcome: str,
        *,
        priorities: list[str] | None = None,
        reference_notes: list[str] | None = None,
        normalization_targets_lufs: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        """Measure a mix and bind it to project and artistic context."""

        try:
            request = CreateMasteringSessionRequest(
                source_path=source_path,
                workflow_mode=workflow_mode,
                desired_outcome=desired_outcome,
                priorities=priorities or [],
                reference_notes=reference_notes or [],
                normalization_targets_lufs=normalization_targets_lufs or {},
            )
        except ValidationError as exc:
            return validation_error(
                exc,
                ErrorCode.INVALID_MASTERING_REQUEST,
                "The mastering intent is invalid.",
                "Provide a concrete desired outcome and concise priorities.",
            )
        intent = MasteringIntent(
            desired_outcome=request.desired_outcome,
            priorities=request.priorities,
            reference_notes=request.reference_notes,
        )
        measured = await self.measurement_service.measure_file(
            request.source_path,
            normalization_targets_lufs=request.normalization_targets_lufs,
        )
        if not measured["ok"]:
            return measured
        try:
            measurement = AudioMeasurementResult.model_validate(measured["measurement"])
        except ValidationError as exc:
            return self._invalid_measurement(exc)

        project_context = None
        warnings = list(measured["warnings"])
        if request.workflow_mode == "current_project":
            project_result = await self.project_service.get_project_snapshot()
            if not project_result["ok"]:
                return project_result
            snapshot = ProjectSnapshot.model_validate(project_result["snapshot"])
            project_context = self._project_context(snapshot)
            warnings.extend(project_result["warnings"])

        source = MasteringSource(
            workflow_mode=request.workflow_mode,
            measurement=measurement,
            project_context=project_context,
        )
        session = MasteringSession(
            session_id=self._session_id(source, intent),
            source=source,
            intent=intent,
        )
        return {
            "ok": True,
            "session": session.model_dump(mode="json"),
            "warnings": warnings,
        }

    @classmethod
    def _project_context(cls, snapshot: ProjectSnapshot) -> MasteringProjectContext:
        return MasteringProjectContext(
            project_path=snapshot.project.path,
            project_name=snapshot.project.name,
            state_change_count=snapshot.project.state_change_count,
            snapshot_sha256=cls._canonical_sha256(snapshot.model_dump(mode="json")),
        )

    @classmethod
    def _session_id(cls, source: MasteringSource, intent: MasteringIntent) -> str:
        fingerprint = cls._canonical_sha256(
            {
                "source": source.model_dump(mode="json"),
                "intent": intent.model_dump(mode="json"),
            }
        )
        return f"ms_{fingerprint[:24]}"

    @staticmethod
    def _canonical_sha256(payload: dict[str, Any]) -> str:
        encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode()
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _invalid_measurement(exc: ValidationError) -> dict[str, Any]:
        return {
            "ok": False,
            "error": ErrorResponse(
                code=ErrorCode.INVALID_BRIDGE_RESPONSE,
                message="The measurement service returned an invalid result.",
                details={"errors": exc.errors(include_context=False)},
                recoverable=True,
                suggested_action="Measure the approved source again.",
            ).model_dump(mode="json"),
            "warnings": [],
        }
