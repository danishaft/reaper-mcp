"""Fingerprint and validate explicit mastering plans before mutation."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from reaper_mcp.bridge.base import BridgeClient
from reaper_mcp.errors import ErrorCode
from reaper_mcp.models.bridge import CommandOptions, ErrorResponse
from reaper_mcp.models.mastering import (
    MasteringPlan,
    MasteringPlanApplication,
    PreviewMasteringPlanRequest,
    SetMasteringFxParameter,
    VerifiedMasteringPlanApplication,
)
from reaper_mcp.services._bridge_result import (
    bridge_error,
    invalid_payload,
    validation_error,
)
from reaper_mcp.services.fx_service import FxService
from reaper_mcp.services.project_service import ProjectService


class MasteringPlanService:
    """Create approval hashes from current source, project, chain, and parameters."""

    def __init__(
        self,
        bridge_client: BridgeClient,
        fx_service: FxService,
        project_service: ProjectService,
    ) -> None:
        self.bridge_client = bridge_client
        self.fx_service = fx_service
        self.project_service = project_service

    async def preview_plan(
        self,
        session: dict[str, Any],
        master_track_guid: str,
        operations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Return a complete non-mutating plan bound to current state."""

        try:
            request = PreviewMasteringPlanRequest(
                session=session,
                master_track_guid=master_track_guid,
                operations=operations,
            )
        except ValidationError as exc:
            return validation_error(
                exc,
                ErrorCode.INVALID_MASTERING_REQUEST,
                "The mastering plan request is invalid.",
                "Use the complete current session and exact guarded FX identities.",
            )

        source_path = request.session.source.measurement.path
        try:
            source_sha256 = await asyncio.to_thread(self._sha256, source_path)
        except OSError as exc:
            return self._stale(
                ErrorCode.MASTERING_SOURCE_CHANGED,
                "The approved mastering source is no longer readable.",
                {"source_path": str(source_path), "reason": str(exc)},
            )
        expected_source_sha256 = request.session.source.measurement.source_sha256
        if source_sha256 != expected_source_sha256:
            return self._stale(
                ErrorCode.MASTERING_SOURCE_CHANGED,
                "The approved mastering source has changed.",
                {
                    "expected_sha256": expected_source_sha256,
                    "actual_sha256": source_sha256,
                },
            )

        master = await self.project_service.get_master_track()
        if not master["ok"]:
            return master
        actual_master_guid = master["master_track"]["guid"]
        if request.master_track_guid != actual_master_guid:
            return self._stale(
                ErrorCode.INVALID_FX_REFERENCE,
                "The supplied FX owner is not the current master track.",
                {
                    "expected_master_track_guid": actual_master_guid,
                    "actual_track_guid": request.master_track_guid,
                },
            )

        project = await self.project_service.get_project_snapshot()
        if not project["ok"]:
            return project
        chain = await self.fx_service.list_track_fx(request.master_track_guid)
        if not chain["ok"]:
            return chain
        chain_state, chain_error = await self._master_chain_state(
            request.master_track_guid,
            chain["fx"],
        )
        if chain_error is not None:
            return chain_error
        assert chain_state is not None
        parameters_by_identity = {
            item["fx"]["identity"]: item["parameters"] for item in chain_state["slots"]
        }
        chain_by_identity = {fx["identity"]: fx for fx in chain["fx"]}
        for operation in request.operations:
            current_fx = chain_by_identity.get(operation.fx_identity.expected_identity)
            if current_fx is None:
                return self._stale(
                    ErrorCode.MASTERING_PLAN_STALE,
                    "A planned FX is not in the current master chain.",
                    {
                        "fx_identity": operation.fx_identity.expected_identity,
                    },
                )
            identity_error = self._validate_fx_identity(
                operation.fx_identity.model_dump(mode="json"),
                current_fx,
            )
            if identity_error is not None:
                return identity_error
            if isinstance(operation, SetMasteringFxParameter):
                parameter_error = self._validate_parameter(
                    operation,
                    parameters_by_identity[operation.fx_identity.expected_identity],
                )
                if parameter_error is not None:
                    return parameter_error
            elif current_fx["enabled"] == operation.enabled:
                return self._stale(
                    ErrorCode.INVALID_MASTERING_REQUEST,
                    "The mastering plan contains an FX enabled-state no-op.",
                    {"fx_identity": operation.fx_identity.expected_identity},
                )

        project_hash = self._canonical_sha256(
            self._project_fingerprint_payload(project["snapshot"])
        )
        chain_hash = self._canonical_sha256(chain_state)
        plan_payload = {
            "session": request.session.model_dump(mode="json"),
            "master_track_guid": request.master_track_guid,
            "source_sha256": source_sha256,
            "project_snapshot_sha256": project_hash,
            "master_chain_sha256": chain_hash,
            "operations": [
                operation.model_dump(mode="json") for operation in request.operations
            ],
            "warnings": [
                "The FFmpeg backend remains experimental until the licensed "
                "EBU compliance suite passes."
            ],
        }
        approval_hash = self._canonical_sha256(plan_payload)
        plan = MasteringPlan(
            plan_id=f"mp_{approval_hash[:24]}",
            approval_hash=approval_hash,
            **plan_payload,
        )
        return {
            "ok": True,
            "plan": plan.model_dump(mode="json"),
            "warnings": plan.warnings,
        }

    async def apply_plan(
        self,
        plan: dict[str, Any],
        approval_hash: str,
    ) -> dict[str, Any]:
        """Revalidate and apply one exact plan in one named undo transaction."""

        try:
            accepted_plan = MasteringPlan.model_validate(plan)
        except ValidationError as exc:
            return validation_error(
                exc,
                ErrorCode.INVALID_MASTERING_REQUEST,
                "The mastering plan is invalid.",
                "Pass the complete plan returned by preview_mastering_plan.",
            )
        if approval_hash != accepted_plan.approval_hash:
            return self._stale(
                ErrorCode.MASTERING_PLAN_STALE,
                "The supplied approval hash does not match the plan.",
                {
                    "expected_approval_hash": accepted_plan.approval_hash,
                    "actual_approval_hash": approval_hash,
                },
            )

        refreshed = await self.preview_plan(
            accepted_plan.session.model_dump(mode="json"),
            accepted_plan.master_track_guid,
            [
                operation.model_dump(mode="json")
                for operation in accepted_plan.operations
            ],
        )
        if not refreshed["ok"]:
            return refreshed
        current_hash = refreshed["plan"]["approval_hash"]
        if current_hash != accepted_plan.approval_hash:
            return self._stale(
                ErrorCode.MASTERING_PLAN_STALE,
                "The source, project, chain, or plan changed after preview.",
                {
                    "expected_approval_hash": accepted_plan.approval_hash,
                    "current_approval_hash": current_hash,
                },
            )

        response = await self.bridge_client.execute(
            "apply_mastering_fx_plan",
            args={
                "approval_hash": approval_hash,
                "master_track_guid": accepted_plan.master_track_guid,
                "operations": [
                    operation.model_dump(mode="json")
                    for operation in accepted_plan.operations
                ],
            },
            options=CommandOptions(
                mutates_project=True,
                undo_label="Apply approved mastering FX plan",
            ),
        )
        if not response.ok:
            return bridge_error(response)
        try:
            application = MasteringPlanApplication.model_validate(response.result or {})
        except ValidationError as exc:
            return invalid_payload(response, exc, "mastering plan application")
        chain_state, chain_error = await self._master_chain_state(
            application.master_track_guid,
            [fx.model_dump(mode="json") for fx in application.fx],
        )
        if chain_error is not None:
            return chain_error
        assert chain_state is not None
        chain_sha256 = self._canonical_sha256(chain_state)
        verified_application = VerifiedMasteringPlanApplication(
            **application.model_dump(mode="json"),
            master_chain_sha256=chain_sha256,
        )
        return {
            "ok": True,
            "application": verified_application.model_dump(mode="json"),
            "warnings": response.warnings,
        }

    async def current_master_chain_fingerprint(
        self,
        master_track_guid: str,
    ) -> dict[str, Any]:
        """Return the complete current master-chain fingerprint."""

        master = await self.project_service.get_master_track()
        if not master["ok"]:
            return master
        if master["master_track"]["guid"] != master_track_guid:
            return self._stale(
                ErrorCode.MASTERING_PLAN_STALE,
                "The master track GUID changed.",
                {
                    "expected_master_track_guid": master_track_guid,
                    "actual_master_track_guid": master["master_track"]["guid"],
                },
            )
        chain = await self.fx_service.list_track_fx(master_track_guid)
        if not chain["ok"]:
            return chain
        chain_state, chain_error = await self._master_chain_state(
            master_track_guid,
            chain["fx"],
        )
        if chain_error is not None:
            return chain_error
        assert chain_state is not None
        return {
            "ok": True,
            "master_chain_sha256": self._canonical_sha256(chain_state),
            "warnings": chain.get("warnings", []),
        }

    def _validate_parameter(
        self,
        operation: SetMasteringFxParameter,
        parameters: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        parameter = next(
            (item for item in parameters if item["index"] == operation.parameter_index),
            None,
        )
        if parameter is None:
            return self._stale(
                ErrorCode.FX_PARAMETER_NOT_FOUND,
                "The planned FX parameter does not exist.",
                {"parameter_index": operation.parameter_index},
            )
        if parameter["name"] != operation.expected_parameter_name:
            return self._stale(
                ErrorCode.MASTERING_PLAN_STALE,
                "The planned FX parameter name has changed.",
                {
                    "expected_name": operation.expected_parameter_name,
                    "actual_name": parameter["name"],
                    "parameter_index": operation.parameter_index,
                },
            )
        if math.isclose(
            parameter["normalized_value"],
            operation.normalized_value,
            abs_tol=1e-9,
        ):
            return self._stale(
                ErrorCode.INVALID_MASTERING_REQUEST,
                "The mastering plan contains a parameter no-op.",
                {
                    "fx_identity": operation.fx_identity.expected_identity,
                    "parameter_index": operation.parameter_index,
                },
            )
        return None

    async def _master_chain_state(
        self,
        master_track_guid: str,
        fx: list[dict[str, Any]],
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        slots = []
        for snapshot in fx:
            canonical_snapshot = {
                key: value for key, value in snapshot.items() if key != "fx_identity"
            }
            identity = {
                "track_guid": master_track_guid,
                "index": canonical_snapshot["index"],
                "expected_identity": canonical_snapshot["identity"],
                "expected_name": canonical_snapshot["name"],
                "expected_guid": canonical_snapshot.get("guid"),
            }
            parameter_result = await self.fx_service.get_fx_parameters(identity)
            if not parameter_result["ok"]:
                return None, parameter_result
            slots.append(
                {
                    "fx": canonical_snapshot,
                    "parameters": parameter_result["parameters"],
                }
            )
        return {
            "master_track_guid": master_track_guid,
            "slots": slots,
        }, None

    def _validate_fx_identity(
        self,
        expected: dict[str, Any],
        actual: dict[str, Any],
    ) -> dict[str, Any] | None:
        comparisons = {
            "track_guid": expected["track_guid"],
            "index": expected["index"],
            "name": expected["expected_name"],
            "guid": expected["expected_guid"],
        }
        for field, expected_value in comparisons.items():
            if expected_value is not None and actual.get(field) != expected_value:
                return self._stale(
                    ErrorCode.MASTERING_PLAN_STALE,
                    "A planned FX identity no longer matches the master chain.",
                    {
                        "field": field,
                        "expected": expected_value,
                        "actual": actual.get(field),
                    },
                )
        return None

    @staticmethod
    def _project_fingerprint_payload(snapshot: dict[str, Any]) -> dict[str, Any]:
        """Exclude UI/playback state that cannot change master processing."""

        return {
            "project": snapshot.get("project", {}),
            "tempo": snapshot.get("tempo", {}),
            "tracks": snapshot.get("tracks", []),
            "markers": snapshot.get("markers", []),
            "regions": snapshot.get("regions", []),
        }

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _canonical_sha256(payload: dict[str, Any]) -> str:
        encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode()
        return hashlib.sha256(encoded).hexdigest()

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
                suggested_action="Refresh the session and preview a new plan.",
            ).model_dump(mode="json"),
            "warnings": [],
        }
