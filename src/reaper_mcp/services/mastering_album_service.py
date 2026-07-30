"""Prepare and approve an isolated multi-song mastering sequence."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from contextlib import suppress
from pathlib import Path
from statistics import median
from typing import Any, Protocol
from uuid import uuid4

from pydantic import ValidationError

from reaper_mcp.errors import ErrorCode
from reaper_mcp.models.audio_program_analysis import AudioProgramAnalysisResult
from reaper_mcp.models.bridge import ErrorResponse
from reaper_mcp.models.mastering import (
    AlbumPqTrack,
    AlbumSequenceAsset,
    AlbumTrackIntent,
    AlbumTransitionAnalysis,
    ApprovedMasteringAlbum,
    ApproveMasteringAlbumRequest,
    CreateMasteringAlbumRequest,
    MasteringAlbumProject,
)
from reaper_mcp.services._bridge_result import validation_error
from reaper_mcp.services.audio_measurement_backend import (
    CommandOutputLimitError,
    CommandTimedOutError,
    MeasurementBackendUnavailableError,
)
from reaper_mcp.services.mastering_album_backend import (
    AlbumAssetBackend,
    AlbumBackendError,
)
from reaper_mcp.services.mastering_audition_service import IsolatedProjectService


class ProgramAnalysisService(Protocol):
    """Run source-integrity-checked full-program analysis."""

    async def analyze_file(self, audio_path: str) -> dict[str, Any]:
        """Analyze one local audio file."""


class MasteringAlbumService:
    """Prepare measured album continuity evidence in a child REAPER project."""

    def __init__(
        self,
        backend: AlbumAssetBackend,
        program_analysis_service: ProgramAnalysisService,
        project_service: IsolatedProjectService,
        *,
        allowed_source_roots: list[Path] | None = None,
        allowed_project_roots: list[Path] | None = None,
    ) -> None:
        self.backend = backend
        self.program_analysis_service = program_analysis_service
        self.project_service = project_service
        self.allowed_source_roots = [
            root.expanduser().resolve() for root in (allowed_source_roots or [])
        ]
        self.allowed_project_roots = [
            root.expanduser().resolve() for root in (allowed_project_roots or [])
        ]

    async def prepare(
        self,
        metadata: dict[str, Any],
        sequence_mode: str,
        tracks: list[dict[str, Any]],
        project_path: str,
        manifest_path: str,
        *,
        continuity_limits: dict[str, Any] | None = None,
        pq_preview_requested: bool = True,
    ) -> dict[str, Any]:
        """Analyze songs and create an isolated sequence or remove partials."""

        try:
            request = CreateMasteringAlbumRequest(
                metadata=metadata,
                sequence_mode=sequence_mode,
                tracks=tracks,
                continuity_limits=continuity_limits or {},
                project_path=Path(project_path).expanduser().resolve(strict=False),
                manifest_path=Path(manifest_path).expanduser().resolve(strict=False),
                pq_preview_requested=pq_preview_requested,
            )
        except ValidationError as exc:
            return validation_error(
                exc,
                ErrorCode.INVALID_MASTERING_REQUEST,
                "The mastering album request is invalid.",
                "Use ordered unique approvals and mode-compatible gap intent.",
            )
        path_error = self.project_service.validate_project_destination(
            request.project_path
        )
        if path_error is not None:
            return path_error
        manifest_error = self._validate_manifest_path(request.manifest_path)
        if manifest_error is not None:
            return manifest_error
        asset_directory = request.project_path.with_suffix(".album-assets")
        if asset_directory.exists():
            return self._error(
                ErrorCode.PROJECT_PATH_NOT_ALLOWED,
                "The album asset directory already exists.",
                {"asset_directory": str(asset_directory)},
                "Choose a new album project path.",
            )

        source_error = await self._validate_sources(request.tracks)
        if source_error is not None:
            return source_error
        format_error = self._validate_formats(request.tracks)
        if format_error is not None:
            return format_error

        created_files: list[Path] = []
        assets: list[AlbumSequenceAsset] = []
        backend_result = None
        cursor_seconds = 0.0
        try:
            analyses = await self._analyze_sources(request.tracks)
            asset_directory.mkdir()
            for track, analysis in zip(request.tracks, analyses, strict=True):
                measurement = track.approval.candidate.measurement
                duration = measurement.bounds.measured_duration_seconds
                if (
                    track.fade_in_seconds > duration
                    or track.fade_out_seconds > duration
                ):
                    raise AlbumBackendError(
                        f"Track {track.metadata.sequence_number} fade exceeds "
                        "its measured duration."
                    )
                filename = f"{track.metadata.sequence_number:02d}.wav"
                asset_path = asset_directory / filename
                created_files.append(asset_path)
                technical = measurement.technical
                assert technical.sample_rate_hz is not None
                backend_result = await self.backend.create_asset(
                    Path(track.approval.candidate.render.primary_output_path),
                    asset_path,
                    sample_rate_hz=technical.sample_rate_hz,
                    duration_seconds=duration,
                    gap_before_seconds=track.gap_before_seconds,
                    fade_in_seconds=track.fade_in_seconds,
                    fade_out_seconds=track.fade_out_seconds,
                )
                source_path = Path(track.approval.candidate.render.primary_output_path)
                source_sha256 = await asyncio.to_thread(self._sha256, source_path)
                if source_sha256 != track.approval.candidate.rendered_sha256:
                    raise AlbumBackendError(
                        f"Track {track.metadata.sequence_number} changed "
                        "during album preparation."
                    )
                index_start = cursor_seconds + track.gap_before_seconds
                program_end = index_start + duration
                assets.append(
                    AlbumSequenceAsset(
                        sequence_number=track.metadata.sequence_number,
                        candidate_id=track.approval.candidate.candidate_id,
                        approval_id=track.approval.approval_id,
                        source_path=source_path,
                        source_sha256=source_sha256,
                        asset_path=asset_path,
                        asset_sha256=await asyncio.to_thread(self._sha256, asset_path),
                        asset_start_seconds=cursor_seconds,
                        index_start_seconds=index_start,
                        program_end_seconds=program_end,
                        gap_before_seconds=track.gap_before_seconds,
                        fade_in_seconds=track.fade_in_seconds,
                        fade_out_seconds=track.fade_out_seconds,
                        measurement=measurement,
                        program_analysis=analysis,
                    )
                )
                cursor_seconds = program_end

            project_result = await self.project_service.create_media_sequence_project(
                [asset.asset_path for asset in assets],
                request.project_path,
            )
            if not project_result["ok"]:
                self._cleanup(created_files, asset_directory)
                return project_result
            created_files.append(request.project_path)
            assert backend_result is not None
            transitions = self._transitions(assets, request)
            pq_preview = (
                self._pq_preview(request.tracks, assets)
                if request.pq_preview_requested
                else []
            )
            loudness = [
                float(asset.measurement.loudness.integrated_lufs)
                for asset in assets
                if asset.measurement.loudness.integrated_lufs is not None
            ]
            if len(loudness) != len(assets):
                raise AlbumBackendError(
                    "Every album track requires integrated loudness."
                )
            warnings = self._warnings(transitions, request)
            project = project_result["project"]
            manifest_payload = {
                "metadata": request.metadata.model_dump(mode="json"),
                "sequence_mode": request.sequence_mode,
                "project_path": request.project_path,
                "project_sha256": project["project_sha256"],
                "assets": [asset.model_dump(mode="json") for asset in assets],
                "transitions": [
                    transition.model_dump(mode="json") for transition in transitions
                ],
                "pq_preview": [
                    pq_track.model_dump(mode="json") for pq_track in pq_preview
                ],
                "total_duration_seconds": cursor_seconds,
                "median_integrated_lufs": median(loudness),
                "integrated_loudness_span_lu": max(loudness) - min(loudness),
                "backend": {
                    "name": backend_result.backend_name,
                    "executable": backend_result.executable_path,
                    "version": backend_result.version,
                },
                "reaper_executable": project["reaper_executable"],
                "ddp_available": False,
                "warnings": warnings,
            }
            self._write_manifest_atomic(
                request.manifest_path,
                manifest_payload,
                created_files,
            )
            manifest_sha256 = await asyncio.to_thread(
                self._sha256, request.manifest_path
            )
            payload = {
                "metadata": request.metadata,
                "sequence_mode": request.sequence_mode,
                "project_path": request.project_path,
                "project_sha256": project["project_sha256"],
                "manifest_path": request.manifest_path,
                "manifest_sha256": manifest_sha256,
                "asset_directory": asset_directory,
                "assets": assets,
                "transitions": transitions,
                "pq_preview": pq_preview,
                "total_duration_seconds": cursor_seconds,
                "median_integrated_lufs": median(loudness),
                "integrated_loudness_span_lu": max(loudness) - min(loudness),
                "sample_rate_hz": assets[0].measurement.technical.sample_rate_hz,
                "channel_layout": assets[0].measurement.technical.channel_layout,
                "backend_name": backend_result.backend_name,
                "backend_executable": backend_result.executable_path,
                "backend_version": backend_result.version,
                "reaper_executable": project["reaper_executable"],
                "warnings": warnings,
            }
            fingerprint = self._canonical_sha256(
                {key: self._jsonable(value) for key, value in payload.items()}
            )
            album = MasteringAlbumProject(
                album_id=f"al_{fingerprint[:24]}",
                **payload,
            )
        except (
            AlbumBackendError,
            MeasurementBackendUnavailableError,
            CommandTimedOutError,
            CommandOutputLimitError,
            OSError,
            ValidationError,
        ) as exc:
            self._cleanup(created_files, asset_directory)
            return self._error(
                ErrorCode.MASTERING_ALBUM_FAILED,
                "The mastering album transaction failed.",
                {"reason": str(exc)},
                "Fix the approvals, analysis, sequence, or backend and retry.",
            )
        return {
            "ok": True,
            "album": album.model_dump(mode="json"),
            "warnings": album.warnings,
        }

    async def approve(
        self,
        album: dict[str, Any],
        approved_by: str,
        judgment_notes: list[str],
        listening_confirmed: bool,
    ) -> dict[str, Any]:
        """Approve a still-current album only after engineer listening."""

        try:
            request = ApproveMasteringAlbumRequest(
                album=album,
                approved_by=approved_by,
                judgment_notes=judgment_notes,
                listening_confirmed=listening_confirmed,
            )
        except ValidationError as exc:
            return validation_error(
                exc,
                ErrorCode.INVALID_MASTERING_REQUEST,
                "The mastering album approval is invalid.",
                "Provide the prepared album and explicit listening evidence.",
            )
        stale = await self._validate_prepared_album(request.album)
        if stale is not None:
            return stale
        payload = {
            "album": request.album.model_dump(mode="json"),
            "album_id": request.album.album_id,
            "album_manifest_sha256": request.album.manifest_sha256,
            "approved_by": request.approved_by,
            "judgment_notes": request.judgment_notes,
            "listening_confirmed": request.listening_confirmed,
        }
        fingerprint = self._canonical_sha256(payload)
        approval = ApprovedMasteringAlbum(
            album_approval_id=f"aa_{fingerprint[:24]}",
            **payload,
        )
        return {
            "ok": True,
            "approval": approval.model_dump(mode="json"),
            "warnings": ["Album sequence approval does not enable DDP generation."],
        }

    async def _analyze_sources(
        self,
        tracks: list[AlbumTrackIntent],
    ) -> list[AudioProgramAnalysisResult]:
        analyses = []
        for track in tracks:
            candidate = track.approval.candidate
            result = await self.program_analysis_service.analyze_file(
                candidate.render.primary_output_path
            )
            if not result["ok"]:
                raise AlbumBackendError(result["error"]["message"])
            analysis = AudioProgramAnalysisResult.model_validate(result["analysis"])
            if analysis.source_sha256 != candidate.rendered_sha256:
                raise AlbumBackendError(
                    f"Track {track.metadata.sequence_number} analysis hash "
                    "does not match its approved candidate."
                )
            analyses.append(analysis)
        return analyses

    async def _validate_sources(
        self,
        tracks: list[AlbumTrackIntent],
    ) -> dict[str, Any] | None:
        for track in tracks:
            candidate = track.approval.candidate
            path = Path(candidate.render.primary_output_path).resolve(strict=False)
            if not any(path.is_relative_to(root) for root in self.allowed_source_roots):
                return self._error(
                    ErrorCode.RENDER_OUTPUT_NOT_ALLOWED,
                    "An album candidate is outside allowed source roots.",
                    {"path": str(path)},
                    "Use approved candidates inside allowed render roots.",
                )
            if not path.is_file():
                return self._source_changed(path, "candidate file is missing")
            actual_sha256 = await asyncio.to_thread(self._sha256, path)
            if (
                actual_sha256 != candidate.rendered_sha256
                or candidate.measurement.source_sha256 != candidate.rendered_sha256
            ):
                return self._source_changed(path, "candidate fingerprint changed")
        return None

    def _validate_formats(
        self,
        tracks: list[AlbumTrackIntent],
    ) -> dict[str, Any] | None:
        formats = {
            (
                track.approval.candidate.measurement.technical.sample_rate_hz,
                track.approval.candidate.measurement.technical.channel_layout,
            )
            for track in tracks
        }
        if len(formats) != 1 or None in next(iter(formats)):
            return self._error(
                ErrorCode.INVALID_MASTERING_REQUEST,
                "Album candidates require one matching known audio format.",
                {"formats": [list(item) for item in formats]},
                "Deliver matching approved PCM candidates before sequencing.",
            )
        return None

    @staticmethod
    def _transitions(
        assets: list[AlbumSequenceAsset],
        request: CreateMasteringAlbumRequest,
    ) -> list[AlbumTransitionAnalysis]:
        transitions = []
        limits = request.continuity_limits
        for previous, current in zip(assets, assets[1:], strict=False):
            previous_lufs = previous.measurement.loudness.integrated_lufs
            current_lufs = current.measurement.loudness.integrated_lufs
            assert previous_lufs is not None and current_lufs is not None
            loudness_delta = current_lufs - previous_lufs
            previous_peak = previous.measurement.peaks.true_peak_dbtp
            current_peak = current.measurement.peaks.true_peak_dbtp
            previous_plr = previous.measurement.dynamics.peak_to_loudness_ratio_db
            current_plr = current.measurement.dynamics.peak_to_loudness_ratio_db
            previous_bands = {
                band.name: band.balance_to_full_range_db
                for band in previous.program_analysis.bands
            }
            current_bands = {
                band.name: band.balance_to_full_range_db
                for band in current.program_analysis.bands
            }
            band_deltas = {
                name: current_bands[name] - previous_bands[name]
                for name in previous_bands.keys() & current_bands.keys()
            }
            flags = []
            if (
                limits.maximum_adjacent_loudness_delta_lu is not None
                and abs(loudness_delta) > limits.maximum_adjacent_loudness_delta_lu
            ):
                flags.append("adjacent_loudness_delta")
            plr_delta = (
                current_plr - previous_plr
                if current_plr is not None and previous_plr is not None
                else None
            )
            if (
                limits.maximum_adjacent_plr_delta_db is not None
                and plr_delta is not None
                and abs(plr_delta) > limits.maximum_adjacent_plr_delta_db
            ):
                flags.append("adjacent_plr_delta")
            if limits.maximum_adjacent_band_balance_delta_db is not None and any(
                abs(value) > limits.maximum_adjacent_band_balance_delta_db
                for value in band_deltas.values()
            ):
                flags.append("adjacent_band_balance_delta")
            transitions.append(
                AlbumTransitionAnalysis(
                    from_sequence_number=previous.sequence_number,
                    to_sequence_number=current.sequence_number,
                    gap_seconds=current.gap_before_seconds,
                    integrated_loudness_delta_lu=loudness_delta,
                    true_peak_delta_db=(
                        current_peak - previous_peak
                        if current_peak is not None and previous_peak is not None
                        else None
                    ),
                    plr_delta_db=plr_delta,
                    band_balance_deltas_db=band_deltas,
                    continuity_flags=flags,
                )
            )
        return transitions

    @staticmethod
    def _pq_preview(
        tracks: list[AlbumTrackIntent],
        assets: list[AlbumSequenceAsset],
    ) -> list[AlbumPqTrack]:
        return [
            AlbumPqTrack(
                sequence_number=track.metadata.sequence_number,
                index_01_frames=round(asset.index_start_seconds * 75.0),
                index_01_seconds=round(asset.index_start_seconds * 75.0) / 75.0,
                pregap_frames=round(track.gap_before_seconds * 75.0),
                title=track.metadata.title,
                performer=track.metadata.artist,
                isrc=track.metadata.isrc,
            )
            for track, asset in zip(tracks, assets, strict=True)
        ]

    @staticmethod
    def _warnings(
        transitions: list[AlbumTransitionAnalysis],
        request: CreateMasteringAlbumRequest,
    ) -> list[str]:
        warnings = [
            "Continuity values are measurements, not an artistic ranking; the "
            "engineer must listen to and approve the sequence.",
            "PQ and CD-Text are previews only. DDP generation remains unavailable "
            "until independent verification is implemented.",
        ]
        flagged = [
            transition.to_sequence_number
            for transition in transitions
            if transition.continuity_flags
        ]
        if flagged:
            warnings.append(
                "Engineer-supplied continuity limits were exceeded before tracks: "
                + ", ".join(str(sequence) for sequence in flagged)
                + "."
            )
        if request.sequence_mode == "continuous":
            warnings.append(
                "Continuous mode preserves zero-gap order; it does not create "
                "crossfades or overlap approved song files."
            )
        return warnings

    def _validate_manifest_path(self, path: Path) -> dict[str, Any] | None:
        if path.suffix.lower() != ".json":
            return self._path_error(path, "Album manifests must use .json.")
        if not any(path.is_relative_to(root) for root in self.allowed_project_roots):
            return self._path_error(
                path, "The album manifest is outside allowed project roots."
            )
        if not path.parent.is_dir():
            return self._path_error(
                path, "The album manifest parent directory does not exist."
            )
        if path.exists():
            return self._path_error(path, "The album manifest already exists.")
        return None

    async def _validate_prepared_album(
        self,
        album: MasteringAlbumProject,
    ) -> dict[str, Any] | None:
        paths = [
            (album.project_path, album.project_sha256),
            (album.manifest_path, album.manifest_sha256),
            *((asset.source_path, asset.source_sha256) for asset in album.assets),
            *((asset.asset_path, asset.asset_sha256) for asset in album.assets),
        ]
        for path, expected_sha256 in paths:
            if not path.is_file():
                return self._source_changed(path, "album evidence is missing")
            actual_sha256 = await asyncio.to_thread(self._sha256, path)
            if actual_sha256 != expected_sha256:
                return self._source_changed(path, "album evidence changed")
        return None

    @staticmethod
    def _write_manifest_atomic(
        path: Path,
        payload: dict[str, Any],
        created_files: list[Path],
    ) -> None:
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        created_files.append(temporary)
        temporary.write_text(
            json.dumps(
                payload,
                indent=2,
                sort_keys=True,
                ensure_ascii=True,
                default=str,
            )
            + "\n",
            encoding="utf-8",
        )
        os.rename(temporary, path)
        created_files.append(path)

    @staticmethod
    def _cleanup(files: list[Path], directory: Path) -> None:
        for path in reversed(files):
            path.unlink(missing_ok=True)
        with suppress(OSError):
            directory.rmdir()

    def _source_changed(self, path: Path, reason: str) -> dict[str, Any]:
        return self._error(
            ErrorCode.MASTERING_SOURCE_CHANGED,
            "Approved album evidence is unavailable or changed.",
            {"path": str(path), "reason": reason},
            "Prepare and listen to a new album sequence.",
        )

    def _path_error(self, path: Path, message: str) -> dict[str, Any]:
        return self._error(
            ErrorCode.PROJECT_PATH_NOT_ALLOWED,
            message,
            {"path": str(path)},
            "Choose new paths inside REAPER_MCP_ALLOWED_PROJECT_ROOTS.",
        )

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _jsonable(value: Any) -> Any:
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, list):
            return [MasteringAlbumService._jsonable(item) for item in value]
        return value

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
