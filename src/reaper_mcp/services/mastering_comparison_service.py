"""Loudness-matched candidate comparison and explicit engineer approval."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from reaper_mcp.errors import ErrorCode
from reaper_mcp.models.mastering import (
    ApprovedMasteringCandidate,
    ApproveMasteringCandidateRequest,
    CandidateComparisonEntry,
    MasteringCandidate,
    MasteringCandidateComparison,
)
from reaper_mcp.services._bridge_result import validation_error


class MasteringComparisonService:
    """Prepare attenuation-only A/B evidence without claiming to hear it."""

    async def compare_candidates(
        self,
        candidate_a: dict[str, Any],
        candidate_b: dict[str, Any],
    ) -> dict[str, Any]:
        """Return exact non-destructive gains for two compatible candidates."""

        try:
            candidates = [
                MasteringCandidate.model_validate(candidate_a),
                MasteringCandidate.model_validate(candidate_b),
            ]
        except ValidationError as exc:
            return self._validation_error(exc, "candidate comparison")
        if candidates[0].candidate_id == candidates[1].candidate_id:
            return self._invalid("Two different candidates are required.")
        if candidates[0].source_sha256 != candidates[1].source_sha256:
            return self._invalid(
                "Candidates must derive from the same approved source."
            )
        loudness = [
            candidate.measurement.loudness.integrated_lufs for candidate in candidates
        ]
        if any(value is None for value in loudness):
            return self._invalid(
                "Both candidates require integrated loudness measurements."
            )
        measured_loudness = [float(value) for value in loudness if value is not None]
        reference_lufs = min(measured_loudness)
        entries = []
        for candidate, integrated_lufs in zip(
            candidates, measured_loudness, strict=True
        ):
            gain_db = reference_lufs - integrated_lufs
            true_peak = candidate.measurement.peaks.true_peak_dbtp
            entries.append(
                CandidateComparisonEntry(
                    candidate_id=candidate.candidate_id,
                    label=candidate.label,
                    rendered_path=Path(candidate.render.primary_output_path),
                    integrated_lufs=integrated_lufs,
                    audition_gain_db=gain_db,
                    predicted_true_peak_dbtp=(
                        true_peak + gain_db if true_peak is not None else None
                    ),
                )
            )
        payload = {
            "source_sha256": candidates[0].source_sha256,
            "method": "integrated_lufs_attenuation_only",
            "reference_lufs": reference_lufs,
            "entries": [entry.model_dump(mode="json") for entry in entries],
            "warnings": [
                "This comparison reports level matching only. The engineer must "
                "listen and record the artistic judgment."
            ],
        }
        fingerprint = self._canonical_sha256(payload)
        comparison = MasteringCandidateComparison(
            comparison_id=f"cmp_{fingerprint[:24]}",
            **payload,
        )
        return {
            "ok": True,
            "comparison": comparison.model_dump(mode="json"),
            "warnings": comparison.warnings,
        }

    async def approve_candidate(
        self,
        candidate: dict[str, Any],
        comparison: dict[str, Any],
        approved_by: str,
        judgment_notes: list[str],
        listening_confirmed: bool,
    ) -> dict[str, Any]:
        """Record explicit human listening evidence for one candidate."""

        try:
            request = ApproveMasteringCandidateRequest(
                candidate=candidate,
                comparison=comparison,
                approved_by=approved_by,
                judgment_notes=judgment_notes,
                listening_confirmed=listening_confirmed,
            )
        except ValidationError as exc:
            return self._validation_error(exc, "candidate approval")
        payload = {
            "candidate": request.candidate.model_dump(mode="json"),
            "comparison_id": request.comparison.comparison_id,
            "approved_by": request.approved_by,
            "judgment_notes": request.judgment_notes,
            "listening_confirmed": request.listening_confirmed,
        }
        fingerprint = self._canonical_sha256(payload)
        approval = ApprovedMasteringCandidate(
            approval_id=f"ca_{fingerprint[:24]}",
            **payload,
        )
        return {
            "ok": True,
            "approval": approval.model_dump(mode="json"),
            "warnings": [],
        }

    @staticmethod
    def _canonical_sha256(payload: dict[str, Any]) -> str:
        encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode()
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _invalid(message: str) -> dict[str, Any]:
        return {
            "ok": False,
            "error": {
                "code": ErrorCode.MASTERING_CANDIDATE_INVALID,
                "message": message,
                "details": {},
                "recoverable": True,
                "suggested_action": "Render and measure compatible candidates.",
            },
            "warnings": [],
        }

    @staticmethod
    def _validation_error(
        exc: ValidationError,
        subject: str,
    ) -> dict[str, Any]:
        return validation_error(
            exc,
            ErrorCode.MASTERING_CANDIDATE_INVALID,
            f"The mastering {subject} is invalid.",
            "Use complete measured candidates and explicit engineer evidence.",
        )
