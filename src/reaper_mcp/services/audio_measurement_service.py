"""Read-only orchestration for standards-based audio measurement."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from reaper_mcp.errors import ErrorCode
from reaper_mcp.models.audio_measurement import AudioMeasurementRequest
from reaper_mcp.models.bridge import ErrorResponse
from reaper_mcp.services._bridge_result import validation_error
from reaper_mcp.services.audio_measurement_backend import (
    AudioMeasurementBackend,
    AudioMeasurementFailedError,
    MeasurementBackendUnavailableError,
)


class AudioMeasurementService:
    """Validate an approved source and delegate full-program measurement."""

    def __init__(
        self,
        backend: AudioMeasurementBackend,
        *,
        allowed_audio_roots: list[Path] | None = None,
    ) -> None:
        self.backend = backend
        self.allowed_audio_roots = [
            root.expanduser().resolve() for root in (allowed_audio_roots or [])
        ]

    async def measure_file(
        self,
        audio_path: str,
        *,
        start_seconds: float = 0.0,
        end_seconds: float | None = None,
        normalization_targets_lufs: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        """Measure one complete file or explicit interval without changing it."""

        path = Path(audio_path).expanduser().resolve(strict=False)
        path_error = self._validate_path(path)
        if path_error is not None:
            return path_error
        try:
            request = AudioMeasurementRequest(
                audio_path=path,
                start_seconds=start_seconds,
                end_seconds=end_seconds,
                normalization_targets_lufs=normalization_targets_lufs or {},
            )
        except ValidationError as exc:
            return validation_error(
                exc,
                ErrorCode.INVALID_AUDIO_MEASUREMENT_REQUEST,
                "The audio measurement request is invalid.",
                "Provide an approved audio file and valid forward time bounds.",
            )

        source_sha256 = await asyncio.to_thread(self._sha256, path)
        try:
            measurement = await self.backend.measure(request, source_sha256)
        except MeasurementBackendUnavailableError as exc:
            return self._error(
                ErrorCode.MEASUREMENT_BACKEND_UNAVAILABLE,
                "The configured audio measurement backend is unavailable.",
                {"audio_path": str(path), "reason": str(exc)},
                "Install FFmpeg or set REAPER_MCP_FFMPEG_EXECUTABLE correctly.",
            )
        except AudioMeasurementFailedError as exc:
            return self._error(
                ErrorCode.AUDIO_MEASUREMENT_FAILED,
                "The audio file could not be measured.",
                {"audio_path": str(path), "reason": str(exc)},
                (
                    "Check the file, bounds, FFmpeg compatibility, timeout, "
                    "and output limit."
                ),
            )
        source_sha256_after = await asyncio.to_thread(self._sha256, path)
        if source_sha256_after != source_sha256:
            return self._error(
                ErrorCode.MEASUREMENT_SOURCE_CHANGED,
                "The audio source changed while it was being measured.",
                {
                    "audio_path": str(path),
                    "sha256_before": source_sha256,
                    "sha256_after": source_sha256_after,
                },
                "Stop writes to the source, then measure the approved version again.",
            )
        measurement = measurement.model_copy(
            update={
                "quality": measurement.quality.model_copy(
                    update={"source_integrity_verified": True}
                )
            }
        )
        payload = measurement.model_dump(mode="json")
        return {
            "ok": True,
            "measurement": payload,
            "warnings": measurement.warnings,
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
                "Choose an existing file inside REAPER_MCP_ALLOWED_AUDIO_ROOTS.",
            )
        return None

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
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
            "error": ErrorResponse(
                code=code,
                message=message,
                details=details,
                recoverable=True,
                suggested_action=suggested_action,
            ).model_dump(mode="json"),
            "warnings": [],
        }
