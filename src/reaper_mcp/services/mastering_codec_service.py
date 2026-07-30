"""Create measured lossy encode/decode previews from approved masters."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from pydantic import ValidationError

from reaper_mcp.errors import ErrorCode
from reaper_mcp.models.audio_measurement import AudioMeasurementResult
from reaper_mcp.models.audio_program_analysis import AudioProgramAnalysisResult
from reaper_mcp.models.bridge import ErrorResponse
from reaper_mcp.models.mastering import (
    CodecPreviewDelta,
    CodecPreviewSpecification,
    CreateMasteringCodecPreviewRequest,
    MasteringCodecPreview,
)
from reaper_mcp.services._bridge_result import validation_error
from reaper_mcp.services.audio_measurement_backend import (
    AsyncioCommandRunner,
    CommandOutputLimitError,
    CommandRunner,
    CommandTimedOutError,
    MeasurementBackendUnavailableError,
)


class CodecPreviewBackendError(RuntimeError):
    """A lossy encode/decode preview could not be created."""


@dataclass(frozen=True)
class CodecBackendResult:
    """Resolved FFmpeg and encoder evidence."""

    backend_name: str
    encoder_name: str
    executable_path: Path
    version: str


class CodecPreviewBackend(Protocol):
    """Encode and decode one preview through an explicit codec."""

    async def encode_decode(
        self,
        source_path: Path,
        encoded_path: Path,
        decoded_wav_path: Path,
        specification: CodecPreviewSpecification,
        *,
        sample_rate_hz: int,
    ) -> CodecBackendResult:
        """Create both preview files."""


class MeasurementService(Protocol):
    """Measure decoded preview loudness and peaks."""

    async def measure_file(self, audio_path: str) -> dict[str, Any]:
        """Measure one file."""


class ProgramAnalysisService(Protocol):
    """Measure technical, band, and silence facts."""

    async def analyze_file(self, audio_path: str) -> dict[str, Any]:
        """Analyze one file."""


class FfmpegCodecPreviewBackend:
    """Use accepted local FFmpeg encoders and decode to float WAV."""

    ENCODERS = {
        "aac": "aac",
        "mp3": "libmp3lame",
        "opus": "libopus",
    }

    def __init__(
        self,
        executable: str = "ffmpeg",
        *,
        timeout_seconds: float = 120.0,
        max_output_bytes: int = 8 * 1024 * 1024,
        runner: CommandRunner | None = None,
    ) -> None:
        self.executable = executable
        self.timeout_seconds = timeout_seconds
        self.max_output_bytes = max_output_bytes
        self.runner = runner or AsyncioCommandRunner()

    async def encode_decode(
        self,
        source_path: Path,
        encoded_path: Path,
        decoded_wav_path: Path,
        specification: CodecPreviewSpecification,
        *,
        sample_rate_hz: int,
    ) -> CodecBackendResult:
        """Encode once and decode the resulting bitstream once."""

        resolved = shutil.which(self.executable)
        if resolved is None:
            raise MeasurementBackendUnavailableError(
                f"FFmpeg executable was not found: {self.executable}"
            )
        executable = Path(resolved).resolve()
        version = await self._version(executable)
        encoder = self.ENCODERS[specification.format]
        encode_command = [
            str(executable),
            "-hide_banner",
            "-nostdin",
            "-n",
            "-i",
            str(source_path),
            "-map",
            "0:a:0",
            "-map_metadata",
            "-1",
            "-vn",
            "-sn",
            "-dn",
            "-ar",
            str(sample_rate_hz),
            "-ac",
            str(specification.channels),
            "-c:a",
            encoder,
            "-b:a",
            f"{specification.bitrate_kbps}k",
        ]
        if specification.format == "aac":
            encode_command.extend(["-movflags", "+faststart"])
        if specification.format == "opus":
            encode_command.extend(["-vbr", "on"])
        encode_command.append(str(encoded_path))
        await self._run_checked(encode_command, "encode")

        decode_command = [
            str(executable),
            "-hide_banner",
            "-nostdin",
            "-n",
            "-i",
            str(encoded_path),
            "-map",
            "0:a:0",
            "-map_metadata",
            "-1",
            "-ar",
            str(sample_rate_hz),
            "-ac",
            str(specification.channels),
            "-c:a",
            "pcm_f32le",
            str(decoded_wav_path),
        ]
        await self._run_checked(decode_command, "decode")
        for path in (encoded_path, decoded_wav_path):
            if not path.is_file() or path.stat().st_size <= 0:
                raise CodecPreviewBackendError(
                    f"FFmpeg did not create a non-empty preview: {path.name}"
                )
        return CodecBackendResult(
            backend_name="ffmpeg_lossy_encode_decode",
            encoder_name=encoder,
            executable_path=executable,
            version=version,
        )

    async def _run_checked(self, command: list[str], operation: str) -> None:
        try:
            completed = await self.runner.run(
                command,
                timeout_seconds=self.timeout_seconds,
                max_output_bytes=self.max_output_bytes,
            )
        except (CommandTimedOutError, CommandOutputLimitError) as exc:
            raise CodecPreviewBackendError(str(exc)) from exc
        if completed.returncode != 0:
            raise CodecPreviewBackendError(
                f"FFmpeg {operation} returned {completed.returncode}: "
                f"{self._last_line(completed.output)}"
            )

    async def _version(self, executable: Path) -> str:
        try:
            result = await self.runner.run(
                [str(executable), "-version"],
                timeout_seconds=min(self.timeout_seconds, 10.0),
                max_output_bytes=min(self.max_output_bytes, 64 * 1024),
            )
        except (CommandTimedOutError, CommandOutputLimitError) as exc:
            raise CodecPreviewBackendError(str(exc)) from exc
        first_line = result.output.splitlines()[0] if result.output else ""
        if result.returncode != 0 or not first_line.startswith("ffmpeg version "):
            raise CodecPreviewBackendError("The FFmpeg version check failed.")
        return first_line.removeprefix("ffmpeg version ").split(maxsplit=1)[0]

    @staticmethod
    def _last_line(output: str) -> str:
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        return lines[-1] if lines else "no diagnostic output"


class MasteringCodecService:
    """Create previews only from a still-current approved candidate."""

    def __init__(
        self,
        backend: CodecPreviewBackend,
        measurement_service: MeasurementService,
        program_analysis_service: ProgramAnalysisService,
        *,
        allowed_preview_roots: list[Path] | None = None,
    ) -> None:
        self.backend = backend
        self.measurement_service = measurement_service
        self.program_analysis_service = program_analysis_service
        self.allowed_preview_roots = [
            root.expanduser().resolve() for root in (allowed_preview_roots or [])
        ]

    async def create_preview(
        self,
        approval: dict[str, Any],
        specification: dict[str, Any],
    ) -> dict[str, Any]:
        """Publish encoded and decoded preview files after complete analysis."""

        resolved_specification = {
            **specification,
            "encoded_path": Path(specification.get("encoded_path", ""))
            .expanduser()
            .resolve(strict=False),
            "decoded_wav_path": Path(specification.get("decoded_wav_path", ""))
            .expanduser()
            .resolve(strict=False),
        }
        try:
            request = CreateMasteringCodecPreviewRequest(
                approval=approval,
                specification=resolved_specification,
            )
        except ValidationError as exc:
            return validation_error(
                exc,
                ErrorCode.INVALID_MASTERING_REQUEST,
                "The mastering codec preview request is invalid.",
                "Use an approved candidate and explicit codec preview paths.",
            )
        path_error = self._validate_paths(
            [
                request.specification.encoded_path,
                request.specification.decoded_wav_path,
            ]
        )
        if path_error is not None:
            return path_error
        candidate = request.approval.candidate
        source_path = Path(candidate.render.primary_output_path).resolve(strict=False)
        source_error = await self._validate_source(
            source_path,
            candidate.rendered_sha256,
        )
        if source_error is not None:
            return source_error
        technical = candidate.measurement.technical
        if technical.sample_rate_hz is None:
            return self._error(
                ErrorCode.MASTERING_CODEC_PREVIEW_FAILED,
                "The approved candidate has no measured sample rate.",
                {},
                "Remeasure and approve the candidate.",
            )
        resolved_sample_rate = request.specification.sample_rate_hz or (
            48_000
            if request.specification.format == "opus"
            else technical.sample_rate_hz
        )
        encoded_temporary = self._temporary_path(request.specification.encoded_path)
        decoded_temporary = self._temporary_path(request.specification.decoded_wav_path)
        created = [encoded_temporary, decoded_temporary]
        try:
            source_program_result = await self.program_analysis_service.analyze_file(
                str(source_path)
            )
            if not source_program_result["ok"]:
                raise CodecPreviewBackendError(
                    source_program_result["error"]["message"]
                )
            source_program = AudioProgramAnalysisResult.model_validate(
                source_program_result["analysis"]
            )
            if source_program.source_sha256 != candidate.rendered_sha256:
                raise CodecPreviewBackendError(
                    "Approved source analysis fingerprint does not match."
                )
            backend = await self.backend.encode_decode(
                source_path,
                encoded_temporary,
                decoded_temporary,
                request.specification,
                sample_rate_hz=resolved_sample_rate,
            )
            measured = await self.measurement_service.measure_file(
                str(decoded_temporary)
            )
            if not measured["ok"]:
                raise CodecPreviewBackendError(measured["error"]["message"])
            measurement = AudioMeasurementResult.model_validate(measured["measurement"])
            analyzed = await self.program_analysis_service.analyze_file(
                str(decoded_temporary)
            )
            if not analyzed["ok"]:
                raise CodecPreviewBackendError(analyzed["error"]["message"])
            program = AudioProgramAnalysisResult.model_validate(analyzed["analysis"])
            if measurement.source_sha256 != program.source_sha256:
                raise CodecPreviewBackendError(
                    "Decoded preview analysis hashes do not match."
                )
            source_sha256_after = await asyncio.to_thread(self._sha256, source_path)
            if source_sha256_after != candidate.rendered_sha256:
                raise CodecPreviewBackendError(
                    "The approved source changed during codec preview."
                )
            os.rename(
                encoded_temporary,
                request.specification.encoded_path,
            )
            created.append(request.specification.encoded_path)
            os.rename(
                decoded_temporary,
                request.specification.decoded_wav_path,
            )
            created.append(request.specification.decoded_wav_path)
            measurement = measurement.model_copy(
                update={"path": request.specification.decoded_wav_path}
            )
            program = program.model_copy(
                update={"path": request.specification.decoded_wav_path}
            )
            delta = self._delta(
                candidate.measurement,
                source_program,
                measurement,
                program,
            )
            payload = {
                "approval_id": request.approval.approval_id,
                "candidate_id": candidate.candidate_id,
                "specification": request.specification.model_dump(mode="json"),
                "source_sha256": candidate.rendered_sha256,
                "encoded_sha256": await asyncio.to_thread(
                    self._sha256, request.specification.encoded_path
                ),
                "encoded_size_bytes": (
                    request.specification.encoded_path.stat().st_size
                ),
                "decoded_sha256": measurement.source_sha256,
                "decoded_size_bytes": (
                    request.specification.decoded_wav_path.stat().st_size
                ),
                "backend_name": backend.backend_name,
                "encoder_name": backend.encoder_name,
                "backend_executable": backend.executable_path,
                "backend_version": backend.version,
                "resolved_sample_rate_hz": resolved_sample_rate,
                "measurement": measurement.model_dump(mode="json"),
                "program_analysis": program.model_dump(mode="json"),
                "delta": delta.model_dump(mode="json"),
            }
            fingerprint = self._canonical_sha256(payload)
            preview = MasteringCodecPreview(
                preview_id=f"cp_{fingerprint[:24]}",
                **payload,
            )
        except (
            CodecPreviewBackendError,
            MeasurementBackendUnavailableError,
            CommandTimedOutError,
            CommandOutputLimitError,
            OSError,
            ValidationError,
        ) as exc:
            self._cleanup(created)
            return self._error(
                ErrorCode.MASTERING_CODEC_PREVIEW_FAILED,
                "The mastering codec preview transaction failed.",
                {"reason": str(exc)},
                "Fix the encoder, source, paths, or analysis backend and retry.",
            )
        return {
            "ok": True,
            "preview": preview.model_dump(mode="json"),
            "warnings": [
                "This is an encode/decode audition preview, not a master "
                "deliverable or an artistic preference."
            ],
        }

    @staticmethod
    def _delta(
        source_measurement: AudioMeasurementResult,
        source_program: AudioProgramAnalysisResult,
        decoded_measurement: AudioMeasurementResult,
        decoded_program: AudioProgramAnalysisResult,
    ) -> CodecPreviewDelta:
        def difference(
            current: float | None,
            source: float | None,
        ) -> float | None:
            return (
                current - source if current is not None and source is not None else None
            )

        source_bands = {
            band.name: band.balance_to_full_range_db for band in source_program.bands
        }
        decoded_bands = {
            band.name: band.balance_to_full_range_db for band in decoded_program.bands
        }
        return CodecPreviewDelta(
            integrated_loudness_delta_lu=difference(
                decoded_measurement.loudness.integrated_lufs,
                source_measurement.loudness.integrated_lufs,
            ),
            sample_peak_delta_db=difference(
                decoded_measurement.peaks.sample_peak_dbfs,
                source_measurement.peaks.sample_peak_dbfs,
            ),
            true_peak_delta_db=difference(
                decoded_measurement.peaks.true_peak_dbtp,
                source_measurement.peaks.true_peak_dbtp,
            ),
            band_balance_deltas_db={
                name: decoded_bands[name] - source_bands[name]
                for name in source_bands.keys() & decoded_bands.keys()
            },
        )

    def _validate_paths(self, paths: list[Path]) -> dict[str, Any] | None:
        if len(set(paths)) != len(paths):
            return self._path_error(paths[0], "Preview paths must be unique.")
        for path in paths:
            if not any(
                path.is_relative_to(root) for root in self.allowed_preview_roots
            ):
                return self._path_error(
                    path, "A codec preview path is outside allowed roots."
                )
            if not path.parent.is_dir():
                return self._path_error(
                    path, "A codec preview parent directory does not exist."
                )
            if path.exists():
                return self._path_error(path, "A codec preview output exists.")
        return None

    async def _validate_source(
        self,
        path: Path,
        expected_sha256: str,
    ) -> dict[str, Any] | None:
        if not any(path.is_relative_to(root) for root in self.allowed_preview_roots):
            return self._path_error(
                path, "The approved candidate is outside allowed roots."
            )
        if not path.is_file():
            return self._changed(path, "candidate file is missing")
        actual_sha256 = await asyncio.to_thread(self._sha256, path)
        if actual_sha256 != expected_sha256:
            return self._changed(path, "candidate fingerprint changed")
        return None

    @staticmethod
    def _temporary_path(path: Path) -> Path:
        return path.with_name(f".{path.stem}.{uuid4().hex}.tmp{path.suffix.lower()}")

    @staticmethod
    def _cleanup(paths: list[Path]) -> None:
        for path in reversed(paths):
            path.unlink(missing_ok=True)

    def _changed(self, path: Path, reason: str) -> dict[str, Any]:
        return self._error(
            ErrorCode.MASTERING_SOURCE_CHANGED,
            "The approved candidate is unavailable or changed.",
            {"path": str(path), "reason": reason},
            "Render, compare, and approve the candidate again.",
        )

    def _path_error(self, path: Path, message: str) -> dict[str, Any]:
        return self._error(
            ErrorCode.RENDER_OUTPUT_NOT_ALLOWED,
            message,
            {"path": str(path)},
            "Choose new paths inside REAPER_MCP_ALLOWED_RENDER_ROOTS.",
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
            default=str,
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
