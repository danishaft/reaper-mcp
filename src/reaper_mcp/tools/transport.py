"""MCP transport tool registration."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from reaper_mcp.services.transport_service import TransportService


def register_transport_tools(server: FastMCP, service: TransportService) -> None:
    """Register REAPER transport MCP tools."""

    @server.tool(
        name="play",
        description="Start REAPER playback. This does not change project structure.",
    )
    async def play() -> dict[str, Any]:
        return await service.play()

    @server.tool(
        name="stop",
        description=(
            "Stop REAPER playback only. If REAPER is recording, use "
            "stop_recording so the recording stop is undoable."
        ),
    )
    async def stop() -> dict[str, Any]:
        return await service.stop()

    @server.tool(
        name="stop_recording",
        description=(
            "Stop an active REAPER recording. This can create media items and "
            "mutates the project in one named undo block."
        ),
    )
    async def stop_recording() -> dict[str, Any]:
        return await service.stop_recording()

    @server.tool(
        name="pause",
        description="Pause REAPER transport.",
    )
    async def pause() -> dict[str, Any]:
        return await service.pause()

    @server.tool(
        name="record",
        description="Start REAPER recording. This changes transport state.",
    )
    async def record() -> dict[str, Any]:
        return await service.record()
