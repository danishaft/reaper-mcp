"""MCP project tool registration."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from reaper_mcp.services.project_service import ProjectService


def register_project_tools(server: FastMCP, service: ProjectService) -> None:
    """Register read-only project MCP tools."""

    @server.tool(
        name="get_project_snapshot",
        description=(
            "Return a read-only snapshot of the active REAPER project, including "
            "project metadata, transport state, tracks, and markers or regions."
        ),
    )
    async def get_project_snapshot() -> dict[str, Any]:
        return await service.get_project_snapshot()

    @server.tool(
        name="list_tracks",
        description=(
            "Return all tracks in REAPER UI order with stable track GUIDs. "
            "This tool does not change the REAPER project."
        ),
    )
    async def list_tracks() -> dict[str, Any]:
        return await service.list_tracks()

    @server.tool(
        name="create_track",
        description=(
            "Create one REAPER track with a stable track GUID in the response. "
            "This mutates the project in one named undo block unless dry_run is true."
        ),
    )
    async def create_track(
        name: str = "Track",
        index: int | None = None,
        color: int | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        return await service.create_track(
            name=name,
            index=index,
            color=color,
            dry_run=dry_run,
        )

    @server.tool(
        name="rename_track",
        description=(
            "Rename one REAPER track by stable track GUID. "
            "This mutates the project in one named undo block."
        ),
    )
    async def rename_track(track_guid: str, name: str) -> dict[str, Any]:
        return await service.rename_track(track_guid=track_guid, name=name)

    @server.tool(
        name="set_track_color",
        description=(
            "Set one REAPER track color by stable track GUID. "
            "This mutates the project in one named undo block."
        ),
    )
    async def set_track_color(track_guid: str, color: int) -> dict[str, Any]:
        return await service.set_track_color(track_guid=track_guid, color=color)

    @server.tool(
        name="set_track_mute",
        description=(
            "Set one REAPER track mute state by stable track GUID. "
            "This mutates the project in one named undo block."
        ),
    )
    async def set_track_mute(track_guid: str, muted: bool) -> dict[str, Any]:
        return await service.set_track_mute(track_guid=track_guid, muted=muted)

    @server.tool(
        name="set_track_solo",
        description=(
            "Set one REAPER track solo state by stable track GUID. "
            "This mutates the project in one named undo block."
        ),
    )
    async def set_track_solo(track_guid: str, soloed: bool) -> dict[str, Any]:
        return await service.set_track_solo(track_guid=track_guid, soloed=soloed)

    @server.tool(
        name="set_track_arm",
        description=(
            "Set one REAPER track record-arm state by stable track GUID. "
            "This mutates the project in one named undo block."
        ),
    )
    async def set_track_arm(track_guid: str, armed: bool) -> dict[str, Any]:
        return await service.set_track_arm(track_guid=track_guid, armed=armed)

    @server.tool(
        name="set_track_volume",
        description=(
            "Set one track's linear gain from 0.0 to 4.0 by stable track GUID. "
            "This mutates the project in one named undo block."
        ),
    )
    async def set_track_volume(track_guid: str, volume: float) -> dict[str, Any]:
        return await service.set_track_volume(track_guid=track_guid, volume=volume)

    @server.tool(
        name="set_track_pan",
        description=(
            "Set one track's pan from -1.0 left to 1.0 right by stable track "
            "GUID. This mutates the project in one named undo block."
        ),
    )
    async def set_track_pan(track_guid: str, pan: float) -> dict[str, Any]:
        return await service.set_track_pan(track_guid=track_guid, pan=pan)

    @server.tool(
        name="set_track_recording",
        description=(
            "Set one track's recording input and input monitoring by stable GUID. "
            "This mutates the project in one named undo block."
        ),
    )
    async def set_track_recording(
        track_guid: str,
        recording_input: int,
        input_monitoring: bool = False,
    ) -> dict[str, Any]:
        return await service.set_track_recording(
            track_guid, recording_input, input_monitoring
        )

    @server.tool(
        name="set_track_folder_depth",
        description=(
            "Set a track's folder depth to -1, 0, or 1 by stable GUID. "
            "This mutates the project in one named undo block."
        ),
    )
    async def set_track_folder_depth(
        track_guid: str, folder_depth: int
    ) -> dict[str, Any]:
        return await service.set_track_folder_depth(track_guid, folder_depth)

    @server.tool(
        name="delete_track",
        description=(
            "Delete one REAPER track by stable track GUID. "
            "This mutates the project in one named undo block."
        ),
    )
    async def delete_track(track_guid: str) -> dict[str, Any]:
        return await service.delete_track(track_guid=track_guid)

    @server.tool(
        name="get_master_track",
        description="Return master volume, pan, mute state, and stable GUID.",
    )
    async def get_master_track() -> dict[str, Any]:
        return await service.get_master_track()

    @server.tool(
        name="set_master_volume",
        description=(
            "Set linear master gain from 0.0 to 4.0. "
            "This mutates the project in one named undo block."
        ),
    )
    async def set_master_volume(volume: float) -> dict[str, Any]:
        return await service.set_master_volume(volume)

    @server.tool(
        name="set_master_pan",
        description=(
            "Set master pan from -1.0 left to 1.0 right. "
            "This mutates the project in one named undo block."
        ),
    )
    async def set_master_pan(pan: float) -> dict[str, Any]:
        return await service.set_master_pan(pan)

    @server.tool(
        name="set_master_mute",
        description=(
            "Set master mute explicitly. "
            "This mutates the project in one named undo block."
        ),
    )
    async def set_master_mute(muted: bool) -> dict[str, Any]:
        return await service.set_master_mute(muted)
