"""MCP high-level workflow tool registration."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from reaper_mcp.models.workflow import SongStarterMode
from reaper_mcp.services.workflow_service import WorkflowService


def register_workflow_tools(server: FastMCP, service: WorkflowService) -> None:
    """Register bounded music-production workflows."""

    @server.tool(
        name="create_song_starter",
        description=(
            "Create Drums, Bass, Chords, and Lead MIDI parts plus one region in a "
            "4/4 REAPER project. The deterministic major or minor pattern runs as "
            "one mutation and one named undo step, and returns all created GUIDs."
        ),
    )
    async def create_song_starter(
        name: str = "Song Starter",
        start_measure: int = 1,
        bars: int = 8,
        root_note: int = 60,
        mode: SongStarterMode = "major",
    ) -> dict[str, Any]:
        return await service.create_song_starter(
            name=name,
            start_measure=start_measure,
            bars=bars,
            root_note=root_note,
            mode=mode,
        )
