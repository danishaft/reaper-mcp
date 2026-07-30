"""Generate, measure, QC, and manifest approved mastering deliverables."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
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
    CreateDeliveryRequest,
    DeliveryArtifact,
    DeliveryBackendInfo,
    DeliveryManifest,
    DeliveryQcCheck,
    DeliverySpecification,
)
from reaper_mcp.services._bridge_result import validation_error
from reaper_mcp.services.audio_measurement_backend import (
    AsyncioCommandRunner,
    CommandOutputLimitError,
    CommandRunner,
    CommandTimedOutError,
    MeasurementBackendUnavailableError,
)


class DeliveryBackendError(RuntimeError):
    """FFmpeg or FFprobe could not create verified delivery evidence."""


@dataclass(frozen=True)
class TranscodeResult:
    """Transcoder identity and observed output metadata."""

    backend: DeliveryBackendInfo
    metadata: dict[str, str]


class DeliveryBackend(Protocol):
    """Create one temporary artifact for final-file verification."""

    async def transcode(
        self,
        source_path: Path,
        output_path: Path,
        specification: DeliverySpecification,
        applied_dither: str,
    ) -> TranscodeResult:
        """Write an artifact and return observed backend evidence."""


class AudioFileMeasurementService(Protocol):
    """Measure a local audio file and return the stable service result."""

    async def measure_file(self, audio_path: str) -> dict[str, Any]:
        """Measure one file."""


class AudioFileProgramAnalysisService(Protocol):
    """Run full-program technical analysis for one audio file."""

    async def analyze_file(self, audio_path: str) -> dict[str, Any]:
        """Analyze one file."""


class FfmpegDeliveryBackend:
    """Create one PCM WAV conversion in one bounded FFmpeg pass."""

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

    async def transcode(
        self,
        source_path: Path,
        output_path: Path,
        specification: DeliverySpecification,
        applied_dither: str,
    ) -> TranscodeResult:
        """Write one temporary WAV and read its actual metadata."""

        executable = self._resolve(self.executable)
        ffprobe = self._resolve_probe(executable)
        version = await self._version(executable)
        command = self._command(
            executable,
            source_path,
            output_path,
            specification,
            applied_dither,
        )
        try:
            completed = await self.runner.run(
                command,
                timeout_seconds=self.timeout_seconds,
                max_output_bytes=self.max_output_bytes,
            )
        except (CommandTimedOutError, CommandOutputLimitError) as exc:
            raise DeliveryBackendError(str(exc)) from exc
        if completed.returncode != 0:
            raise DeliveryBackendError(
                f"FFmpeg returned {completed.returncode}: "
                f"{self._last_line(completed.output)}"
            )
        if not output_path.is_file() or output_path.stat().st_size <= 0:
            raise DeliveryBackendError("FFmpeg did not create a non-empty WAV.")
        metadata = await self._probe_metadata(ffprobe, output_path)
        return TranscodeResult(
            backend=DeliveryBackendInfo(
                name="ffmpeg_pcm_wav",
                executable_path=executable,
                version=version,
            ),
            metadata=metadata,
        )

    def _resolve(self, executable: str) -> Path:
        resolved = shutil.which(executable)
        if resolved is None:
            raise MeasurementBackendUnavailableError(
                f"FFmpeg executable was not found: {executable}"
            )
        return Path(resolved).resolve()

    @staticmethod
    def _resolve_probe(executable: Path) -> Path:
        sibling = executable.with_name(
            "ffprobe.exe" if executable.suffix.lower() == ".exe" else "ffprobe"
        )
        if sibling.is_file():
            return sibling
        resolved = shutil.which("ffprobe")
        if resolved is None:
            raise MeasurementBackendUnavailableError("FFprobe was not found.")
        return Path(resolved).resolve()

    async def _version(self, executable: Path) -> str:
        try:
            result = await self.runner.run(
                [str(executable), "-version"],
                timeout_seconds=min(self.timeout_seconds, 10.0),
                max_output_bytes=min(self.max_output_bytes, 64 * 1024),
            )
        except (CommandTimedOutError, CommandOutputLimitError) as exc:
            raise DeliveryBackendError(str(exc)) from exc
        first_line = result.output.splitlines()[0] if result.output else ""
        if result.returncode != 0 or not first_line.startswith("ffmpeg version "):
            raise DeliveryBackendError("The FFmpeg version check failed.")
        return first_line.removeprefix("ffmpeg version ").split(maxsplit=1)[0]

    async def _probe_metadata(self, ffprobe: Path, output_path: Path) -> dict[str, str]:
        try:
            result = await self.runner.run(
                [
                    str(ffprobe),
                    "-v",
                    "error",
                    "-show_entries",
                    "format_tags",
                    "-of",
                    "json",
                    str(output_path),
                ],
                timeout_seconds=min(self.timeout_seconds, 30.0),
                max_output_bytes=min(self.max_output_bytes, 1024 * 1024),
            )
        except (CommandTimedOutError, CommandOutputLimitError) as exc:
            raise DeliveryBackendError(str(exc)) from exc
        if result.returncode != 0:
            raise DeliveryBackendError("FFprobe metadata verification failed.")
        try:
            payload = json.loads(result.output)
        except json.JSONDecodeError as exc:
            raise DeliveryBackendError("FFprobe returned invalid JSON.") from exc
        tags = payload.get("format", {}).get("tags", {})
        return {str(key).lower(): str(value) for key, value in tags.items()}

    @staticmethod
    def _command(
        executable: Path,
        source_path: Path,
        output_path: Path,
        specification: DeliverySpecification,
        applied_dither: str,
    ) -> list[str]:
        sample_format, codec, output_bits = {
            16: ("s16", "pcm_s16le", None),
            24: ("s32", "pcm_s24le", 24),
            "32_float": ("flt", "pcm_f32le", None),
        }[specification.bit_depth]
        filter_parts = [
            f"osr={specification.sample_rate_hz}",
            "resampler=soxr",
            "precision=28",
            f"osf={sample_format}",
            f"dither_method={applied_dither}",
        ]
        if output_bits is not None:
            filter_parts.append(f"output_sample_bits={output_bits}")
        arguments = [
            str(executable),
            "-hide_banner",
            "-nostdin",
            "-n",
            "-i",
            str(source_path),
            "-map_metadata",
            "-1",
            "-af",
            "aresample=" + ":".join(filter_parts),
            "-ar",
            str(specification.sample_rate_hz),
            "-ac",
            str(specification.channels),
            "-c:a",
            codec,
        ]
        for key, value in sorted(specification.metadata.items()):
            if not re.fullmatch(r"[A-Za-z0-9_.-]+", key):
                raise DeliveryBackendError(f"Unsupported metadata key: {key}")
            arguments.extend(["-metadata", f"{key}={value}"])
        arguments.append(str(output_path))
        return arguments

    @staticmethod
    def _last_line(output: str) -> str:
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        return lines[-1] if lines else "no diagnostic output"


class MasteringDeliveryService:
    """Publish final artifacts only after every final-file QC check passes."""

    def __init__(
        self,
        backend: DeliveryBackend,
        measurement_service: AudioFileMeasurementService,
        program_analysis_service: AudioFileProgramAnalysisService,
        *,
        allowed_delivery_roots: list[Path] | None = None,
    ) -> None:
        self.backend = backend
        self.measurement_service = measurement_service
        self.program_analysis_service = program_analysis_service
        self.allowed_delivery_roots = [
            root.expanduser().resolve() for root in (allowed_delivery_roots or [])
        ]

    async def deliver(
        self,
        approval: dict[str, Any],
        specifications: list[dict[str, Any]],
        manifest_path: str,
        summary_path: str,
    ) -> dict[str, Any]:
        """Generate all outputs as one cleanup-on-failure transaction."""

        try:
            request = CreateDeliveryRequest(
                approval=approval,
                specifications=specifications,
                manifest_path=Path(manifest_path).expanduser().resolve(strict=False),
                summary_path=Path(summary_path).expanduser().resolve(strict=False),
            )
        except ValidationError as exc:
            return validation_error(
                exc,
                ErrorCode.INVALID_MASTERING_REQUEST,
                "The mastering delivery request is invalid.",
                "Use an approved candidate, unique outputs, and valid specifications.",
            )
        paths = [
            *(specification.output_path for specification in request.specifications),
            request.manifest_path,
            request.summary_path,
        ]
        path_error = self._validate_paths(paths)
        if path_error is not None:
            return path_error

        candidate = request.approval.candidate
        source_path = Path(candidate.render.primary_output_path)
        source_error = await self._validate_source(
            source_path, candidate.rendered_sha256
        )
        if source_error is not None:
            return source_error
        created: list[Path] = []
        artifacts: list[DeliveryArtifact] = []
        backend_info = None
        try:
            for specification in request.specifications:
                dither = self._resolve_dither(candidate.measurement, specification)
                temporary_path = specification.output_path.with_name(
                    f".{specification.output_path.stem}.{uuid4().hex}.tmp.wav"
                )
                created.append(temporary_path)
                transcode = await self.backend.transcode(
                    source_path,
                    temporary_path,
                    specification,
                    dither,
                )
                backend_info = transcode.backend
                measured = await self.measurement_service.measure_file(
                    str(temporary_path)
                )
                if not measured["ok"]:
                    raise DeliveryBackendError(measured["error"]["message"])
                measurement = AudioMeasurementResult.model_validate(
                    measured["measurement"]
                )
                analyzed = await self.program_analysis_service.analyze_file(
                    str(temporary_path)
                )
                if not analyzed["ok"]:
                    raise DeliveryBackendError(analyzed["error"]["message"])
                program_analysis = AudioProgramAnalysisResult.model_validate(
                    analyzed["analysis"]
                )
                checks = self._qc_checks(
                    candidate.measurement,
                    measurement,
                    program_analysis,
                    specification,
                    transcode.metadata,
                )
                if not all(check.passed for check in checks):
                    raise DeliveryBackendError(
                        "Final-file QC failed: "
                        + ", ".join(check.name for check in checks if not check.passed)
                    )
                current_source_sha256 = await asyncio.to_thread(
                    self._sha256_file, source_path
                )
                if current_source_sha256 != candidate.rendered_sha256:
                    raise DeliveryBackendError(
                        "The approved candidate changed during delivery."
                    )
                os.rename(temporary_path, specification.output_path)
                created.append(specification.output_path)
                measurement = measurement.model_copy(
                    update={"path": specification.output_path}
                )
                program_analysis = program_analysis.model_copy(
                    update={"path": specification.output_path}
                )
                artifacts.append(
                    DeliveryArtifact(
                        specification=specification,
                        applied_dither=dither,
                        path=specification.output_path,
                        sha256=measurement.source_sha256,
                        size_bytes=specification.output_path.stat().st_size,
                        measurement=measurement,
                        program_analysis=program_analysis,
                        qc_checks=checks,
                        qc_passed=True,
                    )
                )
            assert backend_info is not None
            manifest_payload = {
                "approval_id": request.approval.approval_id,
                "candidate_id": candidate.candidate_id,
                "approved_by": request.approval.approved_by,
                "source_sha256": candidate.source_sha256,
                "rendered_candidate_sha256": candidate.rendered_sha256,
                "backend": backend_info.model_dump(mode="json"),
                "artifacts": [
                    artifact.model_dump(mode="json") for artifact in artifacts
                ],
                "manifest_path": request.manifest_path,
                "summary_path": request.summary_path,
            }
            manifest_hash = self._canonical_sha256(manifest_payload)
            manifest = DeliveryManifest(
                manifest_id=f"dm_{manifest_hash[:24]}",
                **manifest_payload,
            )
            self._write_records(manifest)
            created.extend([request.manifest_path, request.summary_path])
        except (
            DeliveryBackendError,
            MeasurementBackendUnavailableError,
            CommandTimedOutError,
            CommandOutputLimitError,
            OSError,
            ValidationError,
        ) as exc:
            self._cleanup(created)
            return self._error(
                ErrorCode.DELIVERY_QC_FAILED,
                "The mastering delivery transaction failed.",
                {"reason": str(exc)},
                "Correct the specification or backend issue and retry.",
            )
        return {
            "ok": True,
            "manifest": manifest.model_dump(mode="json"),
            "warnings": [],
        }

    def _resolve_dither(
        self,
        source: AudioMeasurementResult,
        specification: DeliverySpecification,
    ) -> str:
        technical = source.technical
        if technical.sample_rate_hz is None or technical.effective_bit_depth is None:
            raise DeliveryBackendError(
                "Source sample rate and effective bit depth are required."
            )
        target_depth = (
            32 if specification.bit_depth == "32_float" else specification.bit_depth
        )
        source_is_float = bool(
            (technical.codec and "f32" in technical.codec)
            or (technical.sample_format and technical.sample_format.startswith("flt"))
        )
        quantizes = specification.bit_depth != "32_float" and (
            source_is_float
            or technical.effective_bit_depth > target_depth
            or technical.sample_rate_hz != specification.sample_rate_hz
        )
        resolved = "triangular" if quantizes else "none"
        if specification.dither != "auto" and specification.dither != resolved:
            raise DeliveryBackendError(
                f"Dither policy must resolve to {resolved} for this conversion."
            )
        return resolved

    @staticmethod
    def _qc_checks(
        source: AudioMeasurementResult,
        output: AudioMeasurementResult,
        program: AudioProgramAnalysisResult,
        specification: DeliverySpecification,
        metadata: dict[str, str],
    ) -> list[DeliveryQcCheck]:
        technical = output.technical
        target_depth = (
            32 if specification.bit_depth == "32_float" else specification.bit_depth
        )
        expected_layout = "mono" if specification.channels == 1 else "stereo"
        duration_delta = abs(
            source.bounds.measured_duration_seconds
            - output.bounds.measured_duration_seconds
        )
        program_duration_delta = abs(
            output.bounds.measured_duration_seconds - program.duration_seconds
        )
        checks = [
            DeliveryQcCheck(
                name="sample_rate",
                passed=technical.sample_rate_hz == specification.sample_rate_hz,
                expected=str(specification.sample_rate_hz),
                actual=str(technical.sample_rate_hz),
            ),
            DeliveryQcCheck(
                name="bit_depth",
                passed=technical.effective_bit_depth == target_depth,
                expected=str(target_depth),
                actual=str(technical.effective_bit_depth),
            ),
            DeliveryQcCheck(
                name="channel_layout",
                passed=technical.channel_layout == expected_layout,
                expected=expected_layout,
                actual=str(technical.channel_layout),
            ),
            DeliveryQcCheck(
                name="duration",
                passed=duration_delta <= 0.05,
                expected="within 0.05 seconds of approved candidate",
                actual=f"delta={duration_delta:.6f}",
            ),
            DeliveryQcCheck(
                name="program_duration",
                passed=program_duration_delta <= 0.05,
                expected="within 0.05 seconds of loudness measurement",
                actual=f"delta={program_duration_delta:.6f}",
            ),
            DeliveryQcCheck(
                name="artifact_hash",
                passed=output.source_sha256 == program.source_sha256,
                expected=output.source_sha256,
                actual=program.source_sha256,
            ),
            DeliveryQcCheck(
                name="clipping",
                passed=not program.clipping_detected,
                expected="no decoded sample at 0 dBFS",
                actual=(
                    f"detected={program.clipping_detected}; "
                    f"peak={program.sample_peak_dbfs} dBFS"
                ),
            ),
            DeliveryQcCheck(
                name="dc_offset",
                passed=(
                    program.maximum_absolute_dc_offset
                    <= specification.maximum_absolute_dc_offset
                ),
                expected=f"<= {specification.maximum_absolute_dc_offset}",
                actual=str(program.maximum_absolute_dc_offset),
            ),
        ]
        if specification.maximum_leading_silence_seconds is not None:
            checks.append(
                DeliveryQcCheck(
                    name="leading_silence",
                    passed=(
                        program.silence.leading_silence_seconds
                        <= specification.maximum_leading_silence_seconds
                    ),
                    expected=(
                        f"<= {specification.maximum_leading_silence_seconds} seconds"
                    ),
                    actual=(f"{program.silence.leading_silence_seconds} seconds"),
                )
            )
        if specification.maximum_trailing_silence_seconds is not None:
            checks.append(
                DeliveryQcCheck(
                    name="trailing_silence",
                    passed=(
                        program.silence.trailing_silence_seconds
                        <= specification.maximum_trailing_silence_seconds
                    ),
                    expected=(
                        f"<= {specification.maximum_trailing_silence_seconds} seconds"
                    ),
                    actual=(f"{program.silence.trailing_silence_seconds} seconds"),
                )
            )
        if specification.true_peak_ceiling_dbtp is not None:
            actual = output.peaks.true_peak_dbtp
            checks.append(
                DeliveryQcCheck(
                    name="true_peak_ceiling",
                    passed=(
                        actual is not None
                        and actual <= specification.true_peak_ceiling_dbtp
                    ),
                    expected=f"<= {specification.true_peak_ceiling_dbtp} dBTP",
                    actual=f"{actual} dBTP",
                )
            )
        integrated = output.loudness.integrated_lufs
        if specification.integrated_lufs_min is not None:
            checks.append(
                DeliveryQcCheck(
                    name="integrated_loudness_min",
                    passed=(
                        integrated is not None
                        and integrated >= specification.integrated_lufs_min
                    ),
                    expected=f">= {specification.integrated_lufs_min} LUFS",
                    actual=f"{integrated} LUFS",
                )
            )
        if specification.integrated_lufs_max is not None:
            checks.append(
                DeliveryQcCheck(
                    name="integrated_loudness_max",
                    passed=(
                        integrated is not None
                        and integrated <= specification.integrated_lufs_max
                    ),
                    expected=f"<= {specification.integrated_lufs_max} LUFS",
                    actual=f"{integrated} LUFS",
                )
            )
        for key, expected in specification.metadata.items():
            actual = metadata.get(key.lower())
            checks.append(
                DeliveryQcCheck(
                    name=f"metadata:{key}",
                    passed=actual == expected,
                    expected=expected,
                    actual=str(actual),
                )
            )
        return checks

    def _validate_paths(self, paths: list[Path]) -> dict[str, Any] | None:
        for path in paths:
            allowed = any(
                path.is_relative_to(root) for root in self.allowed_delivery_roots
            )
            if not allowed:
                return self._error(
                    ErrorCode.RENDER_OUTPUT_NOT_ALLOWED,
                    "A delivery path is outside allowed roots.",
                    {"path": str(path)},
                    "Choose paths inside REAPER_MCP_ALLOWED_RENDER_ROOTS.",
                )
            if not path.parent.is_dir():
                return self._error(
                    ErrorCode.RENDER_OUTPUT_NOT_ALLOWED,
                    "A delivery parent directory does not exist.",
                    {"path": str(path)},
                    "Create the approved destination directory and retry.",
                )
            if path.exists():
                return self._error(
                    ErrorCode.RENDER_OUTPUT_EXISTS,
                    "A delivery output already exists.",
                    {"path": str(path)},
                    "Choose a new output path.",
                )
        return None

    async def _validate_source(
        self,
        source_path: Path,
        expected_sha256: str,
    ) -> dict[str, Any] | None:
        if not source_path.is_file():
            return self._error(
                ErrorCode.MASTERING_SOURCE_CHANGED,
                "The approved candidate file is missing.",
                {"path": str(source_path)},
                "Restore or re-render and approve the candidate.",
            )
        actual_sha256 = await asyncio.to_thread(self._sha256_file, source_path)
        if actual_sha256 != expected_sha256:
            return self._error(
                ErrorCode.MASTERING_SOURCE_CHANGED,
                "The approved candidate file changed before delivery.",
                {
                    "expected_sha256": expected_sha256,
                    "actual_sha256": actual_sha256,
                },
                "Re-render, compare, and approve the current candidate.",
            )
        return None

    @staticmethod
    def _write_records(manifest: DeliveryManifest) -> None:
        manifest.manifest_path.write_text(
            manifest.model_dump_json(indent=2),
            encoding="utf-8",
        )
        rows = [
            "# Mastering delivery",
            "",
            f"Approval: {manifest.approval_id}",
            f"Candidate: {manifest.candidate_id}",
            f"Approved by: {manifest.approved_by}",
            "",
            "## Artifacts",
            "",
        ]
        for artifact in manifest.artifacts:
            rows.extend(
                [
                    f"- {artifact.specification.name}: {artifact.path}",
                    f"  - SHA-256: {artifact.sha256}",
                    f"  - Dither: {artifact.applied_dither}",
                    f"  - QC passed: {artifact.qc_passed}",
                ]
            )
        manifest.summary_path.write_text(
            "\n".join(rows) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _cleanup(paths: list[Path]) -> None:
        for path in reversed(paths):
            path.unlink(missing_ok=True)

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
    def _sha256_file(path: Path) -> str:
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
            "error": ErrorResponse(
                code=code,
                message=message,
                details=details,
                recoverable=True,
                suggested_action=suggested_action,
            ).model_dump(mode="json"),
            "warnings": [],
        }
