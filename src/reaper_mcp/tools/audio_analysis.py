"""MCP audio-analysis tool registration."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from reaper_mcp.services.audio_analysis_service import AudioAnalysisService
from reaper_mcp.services.audio_measurement_service import AudioMeasurementService
from reaper_mcp.services.audio_program_analysis_service import (
    AudioProgramAnalysisService,
)


def register_audio_analysis_tools(
    server: FastMCP,
    service: AudioAnalysisService,
    measurement_service: AudioMeasurementService,
    program_analysis_service: AudioProgramAnalysisService,
) -> None:
    """Register read-only local audio analysis tools."""

    @server.tool(
        name="analyze_audio_file",
        description=(
            "Measure an approved PCM WAV file for duration, level, clipping, "
            "stereo correlation, and spectral centroid."
        ),
    )
    async def analyze_audio_file(audio_path: str) -> dict[str, Any]:
        return await service.analyze_file(audio_path)

    @server.tool(
        name="calculate_take_loudness",
        description=(
            "Measure the approved WAV source behind a media take for peak, RMS, "
            "clipping, and related level metrics without changing the project."
        ),
    )
    async def calculate_take_loudness(take_guid: str) -> dict[str, Any]:
        return await service.calculate_take_loudness(take_guid)

    @server.tool(
        name="measure_audio_file",
        description=(
            "Measure an approved audio file over its full program or explicit "
            "bounds for LUFS-I, maximum momentary and short-term LUFS, LRA, "
            "sample peak, and true peak without changing the file or project."
        ),
    )
    async def measure_audio_file(
        audio_path: str,
        start_seconds: float = 0.0,
        end_seconds: float | None = None,
        normalization_targets_lufs: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        return await measurement_service.measure_file(
            audio_path,
            start_seconds=start_seconds,
            end_seconds=end_seconds,
            normalization_targets_lufs=normalization_targets_lufs,
        )

    @server.tool(
        name="analyze_audio_program",
        description=(
            "Run full-program FFmpeg analysis for per-channel DC offset, sample "
            "peak, clipping, RMS, four broad frequency bands, and leading, "
            "trailing, and interior silence without changing the source."
        ),
    )
    async def analyze_audio_program(audio_path: str) -> dict[str, Any]:
        return await program_analysis_service.analyze_file(audio_path)
