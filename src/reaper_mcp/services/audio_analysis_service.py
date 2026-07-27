"""Read-only audio analysis for approved local WAV files."""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from reaper_mcp.bridge.base import BridgeClient
from reaper_mcp.errors import ErrorCode
from reaper_mcp.models.audio_analysis import AudioAnalysisResult, TakeLoudnessResult
from reaper_mcp.models.take import TakeGuidRequest
from reaper_mcp.services._bridge_result import (
    bridge_error,
    invalid_payload,
    validation_error,
)


class AudioAnalysisService:
    """Analyze PCM WAV files without changing REAPER or the source file."""

    def __init__(
        self,
        allowed_audio_roots: list[Path] | None = None,
        bridge_client: BridgeClient | None = None,
    ) -> None:
        self.allowed_audio_roots = [
            root.expanduser().resolve() for root in (allowed_audio_roots or [])
        ]
        self.bridge_client = bridge_client

    async def calculate_take_loudness(self, take_guid: str) -> dict[str, Any]:
        """Measure the approved audio source behind one REAPER take."""

        if self.bridge_client is None:
            return {
                "ok": False,
                "error": {
                    "code": ErrorCode.REAPER_NOT_AVAILABLE,
                    "message": "Take loudness analysis requires the REAPER bridge.",
                    "details": {},
                    "recoverable": True,
                    "suggested_action": "Start REAPER with the MCP bridge loaded.",
                },
                "warnings": [],
            }
        try:
            request = TakeGuidRequest(take_guid=take_guid)
        except ValidationError as exc:
            return validation_error(
                exc,
                ErrorCode.INVALID_TAKE_REQUEST,
                "The loudness request is invalid.",
                "Provide a current non-empty take GUID.",
            )
        response = await self.bridge_client.execute(
            "calculate_take_loudness",
            args=request.model_dump(mode="json"),
        )
        if not response.ok:
            return bridge_error(response)
        try:
            result = TakeLoudnessResult.model_validate(response.result or {})
        except ValidationError as exc:
            return invalid_payload(response, exc, "take loudness")
        payload = result.model_dump(mode="json")
        if result.source_path is not None:
            source_analysis = await self.analyze_file(str(result.source_path))
            if not source_analysis["ok"]:
                return source_analysis
            payload["analysis"] = source_analysis["analysis"]
        return {
            "ok": True,
            **payload,
            "warnings": [
                *response.warnings,
                (
                    "Measured the source WAV directly; REAPER native dry-run "
                    "loudness is modal."
                ),
            ],
        }

    async def analyze_file(self, audio_path: str) -> dict[str, Any]:
        """Return measured waveform and basic spectral metrics for one WAV file."""

        path = Path(audio_path).expanduser().resolve(strict=False)
        path_error = self._validate_path(path)
        if path_error is not None:
            return path_error
        try:
            result = self._analyze(path)
        except (OSError, EOFError, ValueError, wave.Error, struct.error) as exc:
            return {
                "ok": False,
                "error": {
                    "code": ErrorCode.AUDIO_ANALYSIS_FAILED,
                    "message": "The WAV file could not be analyzed.",
                    "details": {"audio_path": str(path), "reason": str(exc)},
                    "recoverable": True,
                    "suggested_action": (
                        "Choose an uncompressed PCM WAV file and retry."
                    ),
                },
                "warnings": [],
            }
        return {"ok": True, "analysis": result.model_dump(mode="json"), "warnings": []}

    def _analyze(self, path: Path) -> AudioAnalysisResult:
        with wave.open(str(path), "rb") as wav_file:
            channels = wav_file.getnchannels()
            sample_rate = wav_file.getframerate()
            frame_count = wav_file.getnframes()
            sample_width = wav_file.getsampwidth()
            if channels < 1 or sample_rate < 1:
                raise ValueError("WAV channel count and sample rate must be positive.")
            if sample_width not in {1, 2, 3, 4}:
                raise ValueError("Only 8, 16, 24, and 32-bit PCM WAV is supported.")
            raw_frames = wav_file.readframes(frame_count)

        samples = self._decode_samples(raw_frames, sample_width, channels)
        if not samples:
            return AudioAnalysisResult(
                path=path,
                channels=channels,
                sample_rate=sample_rate,
                frame_count=0,
                duration_seconds=0.0,
                peak_dbfs=-math.inf,
                rms_dbfs=-math.inf,
                clipping_samples=0,
                dc_offset=0.0,
                unsupported_metrics=["integrated_lufs", "true_peak_dbfs"],
            )

        frame_values = [sum(frame) / channels for frame in samples]
        peak = max(abs(value) for frame in samples for value in frame)
        mean_square = sum(value * value for value in frame_values) / len(frame_values)
        clipping_samples = sum(
            1 for frame in samples for value in frame if abs(value) >= 0.999
        )
        result = AudioAnalysisResult(
            path=path,
            channels=channels,
            sample_rate=sample_rate,
            frame_count=frame_count,
            duration_seconds=frame_count / sample_rate,
            peak_dbfs=self._dbfs(peak),
            rms_dbfs=self._dbfs(math.sqrt(mean_square)),
            clipping_samples=clipping_samples,
            dc_offset=sum(frame_values) / len(frame_values),
            stereo_correlation=self._stereo_correlation(samples)
            if channels == 2
            else None,
            spectral_centroid_hz=self._spectral_centroid(frame_values, sample_rate),
            unsupported_metrics=["integrated_lufs", "true_peak_dbfs"],
        )
        return result

    @staticmethod
    def _decode_samples(
        raw_frames: bytes, sample_width: int, channels: int
    ) -> list[tuple[float, ...]]:
        frame_width = sample_width * channels
        if len(raw_frames) % frame_width:
            raise EOFError("WAV data does not contain complete frames.")
        frames: list[tuple[float, ...]] = []
        for offset in range(0, len(raw_frames), frame_width):
            values = []
            for channel in range(channels):
                start = offset + channel * sample_width
                raw_value = raw_frames[start : start + sample_width]
                if sample_width == 1:
                    value = (raw_value[0] - 128) / 128.0
                else:
                    value = int.from_bytes(raw_value, "little", signed=True)
                    value /= float(1 << (sample_width * 8 - 1))
                values.append(max(-1.0, min(1.0, value)))
            frames.append(tuple(values))
        return frames

    @staticmethod
    def _stereo_correlation(samples: list[tuple[float, ...]]) -> float | None:
        if len(samples) < 2:
            return None
        left = [frame[0] for frame in samples]
        right = [frame[1] for frame in samples]
        left_mean = sum(left) / len(left)
        right_mean = sum(right) / len(right)
        numerator = sum(
            (left_value - left_mean) * (right_value - right_mean)
            for left_value, right_value in zip(left, right, strict=True)
        )
        left_energy = sum((value - left_mean) ** 2 for value in left)
        right_energy = sum((value - right_mean) ** 2 for value in right)
        denominator = math.sqrt(left_energy * right_energy)
        return numerator / denominator if denominator else None

    @staticmethod
    def _spectral_centroid(samples: list[float], sample_rate: int) -> float | None:
        window = samples[:1024]
        if len(window) < 2:
            return None
        size = len(window)
        weighted_frequency = 0.0
        magnitude_total = 0.0
        for bin_index in range(1, size // 2):
            real = 0.0
            imaginary = 0.0
            for sample_index, sample in enumerate(window):
                angle = 2.0 * math.pi * bin_index * sample_index / size
                window_function = 0.5 - 0.5 * math.cos(
                    2.0 * math.pi * sample_index / size
                )
                windowed_sample = sample * window_function
                real += windowed_sample * math.cos(angle)
                imaginary -= windowed_sample * math.sin(angle)
            magnitude = math.hypot(real, imaginary)
            frequency = bin_index * sample_rate / size
            weighted_frequency += frequency * magnitude
            magnitude_total += magnitude
        return weighted_frequency / magnitude_total if magnitude_total else 0.0

    @staticmethod
    def _dbfs(value: float) -> float:
        return 20.0 * math.log10(value) if value > 0.0 else -120.0

    def _validate_path(self, path: Path) -> dict[str, Any] | None:
        if path.suffix.lower() != ".wav":
            return self._path_error(
                path, "Audio analysis currently supports WAV files."
            )
        if not any(path.is_relative_to(root) for root in self.allowed_audio_roots):
            return self._path_error(path, "The audio path is outside allowed roots.")
        if not path.is_file():
            return self._path_error(path, "The audio file does not exist.")
        return None

    @staticmethod
    def _path_error(path: Path, message: str) -> dict[str, Any]:
        return {
            "ok": False,
            "error": {
                "code": ErrorCode.AUDIO_PATH_NOT_ALLOWED,
                "message": message,
                "details": {"audio_path": str(path)},
                "recoverable": True,
                "suggested_action": (
                    "Choose a WAV file inside REAPER_MCP_ALLOWED_AUDIO_ROOTS."
                ),
            },
            "warnings": [],
        }
