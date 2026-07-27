"""MCP audio-analysis tool registration."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from reaper_mcp.services.audio_analysis_service import AudioAnalysisService


def register_audio_analysis_tools(
    server: FastMCP, service: AudioAnalysisService
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
