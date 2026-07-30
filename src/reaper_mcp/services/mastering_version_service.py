"""Group independently approved song versions without fabricating audio."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from reaper_mcp.errors import ErrorCode
from reaper_mcp.models.bridge import ErrorResponse
from reaper_mcp.models.mastering import (
    CreateMasteringVersionSetRequest,
    MasteringVersionSet,
)
from reaper_mcp.services._bridge_result import validation_error


class MasteringVersionService:
    """Create a current, typed catalog of approved release versions."""

    def __init__(
        self,
        *,
        allowed_source_roots: list[Path] | None = None,
    ) -> None:
        self.allowed_source_roots = [
            root.expanduser().resolve() for root in (allowed_source_roots or [])
        ]

    async def create_version_set(
        self,
        release_name: str,
        entries: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Verify every approved source and return a deterministic catalog."""

        try:
            request = CreateMasteringVersionSetRequest(
                release_name=release_name,
                entries=entries,
            )
        except ValidationError as exc:
            return validation_error(
                exc,
                ErrorCode.MASTERING_VERSION_SET_INVALID,
                "The mastering version set is invalid.",
                "Use unique approved candidates and exactly one main version.",
            )
        for entry in request.entries:
            candidate = entry.approval.candidate
            path = Path(candidate.render.primary_output_path).resolve(strict=False)
            if not any(path.is_relative_to(root) for root in self.allowed_source_roots):
                return self._error(
                    ErrorCode.RENDER_OUTPUT_NOT_ALLOWED,
                    "A mastering version is outside allowed source roots.",
                    {"path": str(path), "role": entry.role},
                    "Use approved candidates inside allowed render roots.",
                )
            if not path.is_file():
                return self._changed(path, entry.role, "file is missing")
            actual_sha256 = await asyncio.to_thread(self._sha256, path)
            if (
                actual_sha256 != candidate.rendered_sha256
                or candidate.measurement.source_sha256 != candidate.rendered_sha256
            ):
                return self._changed(path, entry.role, "fingerprint changed")

        payload = {
            "release_name": request.release_name,
            "entries": [entry.model_dump(mode="json") for entry in request.entries],
        }
        fingerprint = self._canonical_sha256(payload)
        version_set = MasteringVersionSet(
            version_set_id=f"vs_{fingerprint[:24]}",
            **payload,
        )
        return {
            "ok": True,
            "version_set": version_set.model_dump(mode="json"),
            "warnings": [
                "Each role remains a separately approved source. This catalog "
                "does not derive a clean, instrumental, or radio edit."
            ],
        }

    def _changed(
        self,
        path: Path,
        role: str,
        reason: str,
    ) -> dict[str, Any]:
        return self._error(
            ErrorCode.MASTERING_SOURCE_CHANGED,
            "An approved mastering version is unavailable or changed.",
            {"path": str(path), "role": role, "reason": reason},
            "Render, compare, and approve the current version again.",
        )

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _canonical_sha256(payload: dict[str, Any]) -> str:
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode()
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _error(
        code: ErrorCode,
        message: str,
        details: dict[str, Any],
        suggested_action: str,
    ) -> dict[str, Any]:
        return {
            "ok": False,
            "error": ErrorResponse(
                code=code,
                message=message,
                details=details,
                recoverable=True,
                suggested_action=suggested_action,
            ).model_dump(mode="json"),
            "warnings": [],
        }
