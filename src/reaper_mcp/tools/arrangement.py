"""MCP marker and region tool registration."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from reaper_mcp.services.arrangement_service import ArrangementService


def register_arrangement_tools(server: FastMCP, service: ArrangementService) -> None:
    """Register REAPER marker and region MCP tools."""

    @server.tool(
        name="list_markers",
        description=(
            "Return project markers in timeline order. "
            "This tool does not change the REAPER project."
        ),
    )
    async def list_markers() -> dict[str, Any]:
        return await service.list_markers()

    @server.tool(
        name="create_marker",
        description=(
            "Create one project marker at a timeline position in seconds. "
            "This mutates the project in one named undo block."
        ),
    )
    async def create_marker(
        start_seconds: float,
        name: str = "",
        color: int = 0,
    ) -> dict[str, Any]:
        return await service.create_marker(
            start_seconds=start_seconds,
            name=name,
            color=color,
        )

    @server.tool(
        name="delete_marker",
        description=(
            "Delete one project marker by REAPER marker ID with optional expected "
            "name and start position guards. This mutates the project in one "
            "named undo block."
        ),
    )
    async def delete_marker(
        marker_id: int,
        expected_name: str | None = None,
        expected_start_seconds: float | None = None,
    ) -> dict[str, Any]:
        return await service.delete_marker(
            marker_id=marker_id,
            expected_name=expected_name,
            expected_start_seconds=expected_start_seconds,
        )

    @server.tool(
        name="list_regions",
        description=(
            "Return project regions in timeline order. "
            "This tool does not change the REAPER project."
        ),
    )
    async def list_regions() -> dict[str, Any]:
        return await service.list_regions()

    @server.tool(
        name="create_region",
        description=(
            "Create one project region between two timeline positions in seconds. "
            "This mutates the project in one named undo block."
        ),
    )
    async def create_region(
        start_seconds: float,
        end_seconds: float,
        name: str = "",
        color: int = 0,
    ) -> dict[str, Any]:
        return await service.create_region(
            start_seconds=start_seconds,
            end_seconds=end_seconds,
            name=name,
            color=color,
        )

    @server.tool(
        name="delete_region",
        description=(
            "Delete one project region by REAPER region ID with optional expected "
            "name, start position, and end position guards. This mutates the "
            "project in one named undo block."
        ),
    )
    async def delete_region(
        region_id: int,
        expected_name: str | None = None,
        expected_start_seconds: float | None = None,
        expected_end_seconds: float | None = None,
    ) -> dict[str, Any]:
        return await service.delete_region(
            region_id=region_id,
            expected_name=expected_name,
            expected_start_seconds=expected_start_seconds,
            expected_end_seconds=expected_end_seconds,
        )
