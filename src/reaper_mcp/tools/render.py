"""MCP render tool registration."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from reaper_mcp.services.render_service import RenderService


def register_render_tools(server: FastMCP, service: RenderService) -> None:
    """Register REAPER render MCP tools."""

    @server.tool(
        name="render_project",
        description=(
            "Render the full REAPER project to one allowed WAV output path. "
            "This writes a file but does not change the REAPER project."
        ),
    )
    async def render_project(
        output_path: str,
        overwrite: bool = False,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        return await service.render_project(
            output_path=output_path,
            overwrite=overwrite,
            idempotency_key=idempotency_key,
        )

    @server.tool(
        name="render_project_start",
        description=(
            "Start a full-project WAV render and return a job ID immediately. "
            "Use render_project_status or render_project_result to observe it."
        ),
    )
    async def render_project_start(
        output_path: str,
        overwrite: bool = False,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        return await service.start_render_project(
            output_path=output_path,
            overwrite=overwrite,
            idempotency_key=idempotency_key,
        )

    @server.tool(
        name="render_project_status",
        description="Return the current status of a full-project render job.",
    )
    async def render_project_status(job_id: str) -> dict[str, Any]:
        return await service.render_project_status(job_id)

    @server.tool(
        name="render_project_result",
        description=(
            "Return a validated completed result for a full-project render job. "
            "This never claims completion while the job is still running."
        ),
    )
    async def render_project_result(job_id: str) -> dict[str, Any]:
        return await service.render_project_result(job_id)
