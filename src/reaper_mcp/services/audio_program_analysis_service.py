"""Path policy and source-integrity checks for full-program analysis."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Any, Protocol

from reaper_mcp.errors import ErrorCode
from reaper_mcp.models.audio_program_analysis import AudioProgramAnalysisResult
from reaper_mcp.services.audio_measurement_backend import (
    CommandOutputLimitError,
    CommandTimedOutError,
    MeasurementBackendUnavailableError,
)
from reaper_mcp.services.audio_program_analysis_backend import (
    AudioProgramAnalysisError,
)


class AudioProgramAnalysisBackend(Protocol):
    """Analyze one whole audio file."""

    async def analyze(
        self,
        path: Path,
        source_sha256: str,
    ) -> AudioProgramAnalysisResult:
        """Return typed whole-program evidence."""


class AudioProgramAnalysisService:
    """Enforce source roots and byte identity around program analysis."""

    def __init__(
        self,
        backend: AudioProgramAnalysisBackend,
        *,
        allowed_audio_roots: list[Path] | None = None,
    ) -> None:
        self.backend = backend
        self.allowed_audio_roots = [
            root.expanduser().resolve() for root in (allowed_audio_roots or [])
        ]

    async def analyze_file(self, audio_path: str) -> dict[str, Any]:
        """Analyze one approved local audio file without changing it."""

        path = Path(audio_path).expanduser().resolve(strict=False)
        path_error = self._validate_path(path)
        if path_error is not None:
            return path_error
        try:
            source_sha256 = await asyncio.to_thread(self._sha256, path)
            analysis = await self.backend.analyze(path, source_sha256)
            source_sha256_after = await asyncio.to_thread(self._sha256, path)
        except (
            AudioProgramAnalysisError,
            MeasurementBackendUnavailableError,
            CommandTimedOutError,
            CommandOutputLimitError,
            OSError,
            ValueError,
        ) as exc:
            return self._error(
                ErrorCode.AUDIO_PROGRAM_ANALYSIS_FAILED,
                "Full-program technical analysis failed.",
                {"audio_path": str(path), "reason": str(exc)},
                "Check FFmpeg, the approved source, and the analysis timeout.",
            )
        if source_sha256_after != source_sha256:
            return self._error(
                ErrorCode.MEASUREMENT_SOURCE_CHANGED,
                "The audio source changed during full-program analysis.",
                {
                    "audio_path": str(path),
                    "expected_sha256": source_sha256,
                    "actual_sha256": source_sha256_after,
                },
                "Stop writes to the source and analyze it again.",
            )
        analysis = analysis.model_copy(update={"source_integrity_verified": True})
        return {
            "ok": True,
            "analysis": analysis.model_dump(mode="json"),
            "warnings": analysis.warnings,
        }

    def _validate_path(self, path: Path) -> dict[str, Any] | None:
        if not any(path.is_relative_to(root) for root in self.allowed_audio_roots):
            return self._error(
                ErrorCode.AUDIO_PATH_NOT_ALLOWED,
                "The audio path is outside allowed roots.",
                {"audio_path": str(path)},
                "Choose a file inside REAPER_MCP_ALLOWED_AUDIO_ROOTS.",
            )
        if not path.is_file():
            return self._error(
                ErrorCode.AUDIO_PATH_NOT_ALLOWED,
                "The audio file does not exist.",
                {"audio_path": str(path)},
                "Choose an existing approved audio file.",
            )
        return None

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _error(
        code: ErrorCode,
        message: str,
        details: dict[str, Any],
        suggested_action: str,
    ) -> dict[str, Any]:
        return {
            "ok": False,
            "error": {
                "code": code,
                "message": message,
                "details": details,
                "recoverable": True,
                "suggested_action": suggested_action,
            },
            "warnings": [],
        }
