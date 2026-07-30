"""MCP track-template tool registration."""

from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from reaper_mcp.services.template_service import TemplateService


def register_template_tools(server: FastMCP, service: TemplateService) -> None:
    """Register track-template tools."""

    @server.tool(
        name="list_track_templates", description="List approved track templates."
    )
    async def list_track_templates() -> dict[str, Any]:
        return await service.list_templates()

    @server.tool(
        name="save_track_template",
        description="Save one track to an approved .RTrackTemplate path.",
    )
    async def save_track_template(
        track_guid: str, template_path: str
    ) -> dict[str, Any]:
        return await service.save_template(track_guid, template_path)

    @server.tool(
        name="apply_track_template",
        description="Apply an approved track template as a new track.",
    )
    async def apply_track_template(
        template_path: str, index: int | None = None
    ) -> dict[str, Any]:
        return await service.apply_template(template_path, index)

    @server.tool(
        name="delete_track_template",
        description=(
            "Delete one approved track-template file when its listed SHA-256 "
            "still matches."
        ),
    )
    async def delete_track_template(
        template_path: str,
        expected_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")],
    ) -> dict[str, Any]:
        return await service.delete_template(template_path, expected_sha256)
