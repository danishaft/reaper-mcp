"""MCP project navigation and save tool registration."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from reaper_mcp.services.navigation_service import NavigationService


def register_navigation_tools(server: FastMCP, service: NavigationService) -> None:
    """Register project cursor, range, loop, and save tools."""

    @server.tool(name="get_project_navigation")
    async def get_project_navigation() -> dict[str, Any]:
        """Return cursor, time selection, loop, path, and dirty state."""

        return await service.get_project_navigation()

    @server.tool(name="set_edit_cursor")
    async def set_edit_cursor(
        position_seconds: float,
        move_view: bool = True,
        seek_playback: bool = False,
    ) -> dict[str, Any]:
        """Move the edit cursor without changing project content."""

        return await service.set_edit_cursor(position_seconds, move_view, seek_playback)

    @server.tool(name="set_time_selection")
    async def set_time_selection(
        start_seconds: float, end_seconds: float
    ) -> dict[str, Any]:
        """Set a non-empty project time selection in seconds."""

        return await service.set_time_selection(start_seconds, end_seconds)

    @server.tool(name="clear_time_selection")
    async def clear_time_selection() -> dict[str, Any]:
        """Clear the project time selection without changing loop points."""

        return await service.clear_time_selection()

    @server.tool(name="set_loop_points")
    async def set_loop_points(
        start_seconds: float, end_seconds: float
    ) -> dict[str, Any]:
        """Set non-empty project loop points without changing the time selection."""

        return await service.set_loop_points(start_seconds, end_seconds)

    @server.tool(name="set_loop_enabled")
    async def set_loop_enabled(enabled: bool) -> dict[str, Any]:
        """Set REAPER repeat playback explicitly."""

        return await service.set_loop_enabled(enabled)

    @server.tool(name="save_project")
    async def save_project() -> dict[str, Any]:
        """Save an already named project without opening a dialog."""

        return await service.save_project()

    @server.tool(name="save_project_as")
    async def save_project_as(
        project_path: str, overwrite: bool = False
    ) -> dict[str, Any]:
        """Save to an allowed .rpp path and make it the active project path."""

        return await service.save_project_as(project_path, overwrite)
