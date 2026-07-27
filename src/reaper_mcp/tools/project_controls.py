"""MCP project control tool registration."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from reaper_mcp.services.project_controls_service import ProjectControlsService


def register_project_control_tools(
    server: FastMCP, service: ProjectControlsService
) -> None:
    """Register project control tools."""

    @server.tool(name="undo", description="Undo the last REAPER project change.")
    async def undo() -> dict[str, Any]:
        return await service.undo()

    @server.tool(name="redo", description="Redo the last undone REAPER project change.")
    async def redo() -> dict[str, Any]:
        return await service.redo()

    @server.tool(
        name="get_grid_settings",
        description="Read project grid and snap settings.",
    )
    async def get_grid_settings() -> dict[str, Any]:
        return await service.get_grid()

    @server.tool(
        name="set_grid_settings",
        description="Set project grid and snap settings.",
    )
    async def set_grid_settings(
        division: float,
        swing: float = 0.0,
        swing_mode: int = 0,
        snap_enabled: bool = True,
    ) -> dict[str, Any]:
        return await service.set_grid(division, swing, swing_mode, snap_enabled)

    @server.tool(name="get_metronome", description="Read the REAPER metronome state.")
    async def get_metronome() -> dict[str, Any]:
        return await service.get_metronome()

    @server.tool(name="set_metronome", description="Set the REAPER metronome state.")
    async def set_metronome(enabled: bool) -> dict[str, Any]:
        return await service.set_metronome(enabled)

    @server.tool(name="get_playback_rate", description="Read project playback rate.")
    async def get_playback_rate() -> dict[str, Any]:
        return await service.get_playback_rate()

    @server.tool(name="set_playback_rate", description="Set project playback rate.")
    async def set_playback_rate(rate: float) -> dict[str, Any]:
        return await service.set_playback_rate(rate)
