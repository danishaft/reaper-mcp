"""Optional local HTTP adapter for the REAPER MCP server."""

from __future__ import annotations

from ipaddress import ip_address
from json import JSONDecodeError
from typing import Any

from mcp.shared.exceptions import McpError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from reaper_mcp.config import Settings
from reaper_mcp.profiles import ProfiledFastMCP

LOCAL_HTTP_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def validate_http_host(host: str) -> None:
    """Reject non-loopback HTTP bindings because the API has no auth layer."""

    if host in LOCAL_HTTP_HOSTS:
        return
    try:
        is_loopback = ip_address(host).is_loopback
    except ValueError as exc:
        raise ValueError("REAPER_MCP_HTTP_HOST must be a loopback address.") from exc
    if not is_loopback:
        raise ValueError("REAPER_MCP_HTTP_HOST must be a loopback address.")


def create_rest_app(server: ProfiledFastMCP) -> Starlette:
    """Create the HTTP adapter around one configured MCP server instance."""

    async def root(_: Request) -> JSONResponse:
        return JSONResponse(
            {
                "name": "reaper-mcp",
                "transport": "http",
                "endpoints": {
                    "health": "/api/health",
                    "tools": "/api/tools",
                    "call_tool": "/api/tools/{tool_name}",
                },
            }
        )

    async def health(_: Request) -> Response:
        return await _call_tool(server, "health_check", {})

    async def list_tools(_: Request) -> JSONResponse:
        tools = await server.list_tools()
        return JSONResponse(
            {
                "tools": [tool.model_dump(mode="json") for tool in tools],
                "count": len(tools),
            }
        )

    async def call_tool(request: Request) -> Response:
        tool_name = request.path_params["tool_name"]
        try:
            arguments = await request.json()
        except (JSONDecodeError, UnicodeDecodeError):
            return _error_response(
                "invalid_json",
                "The request body must contain valid JSON.",
                status_code=400,
            )
        if not isinstance(arguments, dict):
            return _error_response(
                "invalid_arguments",
                "The request body must be a JSON object.",
                status_code=400,
            )
        return await _call_tool(server, tool_name, arguments)

    return Starlette(
        routes=[
            Route("/", root, methods=["GET"]),
            Route("/api/health", health, methods=["GET"]),
            Route("/api/tools", list_tools, methods=["GET"]),
            Route("/api/tools/{tool_name}", call_tool, methods=["POST"]),
        ]
    )


async def _call_tool(
    server: ProfiledFastMCP, tool_name: str, arguments: dict[str, Any]
) -> Response:
    """Call a visible MCP tool and keep its structured result unchanged."""

    try:
        _, structured_result = await server.call_tool(tool_name, arguments)
    except McpError as exc:
        return _error_response("tool_not_found", str(exc), status_code=404)
    except ValueError as exc:
        return _error_response("invalid_arguments", str(exc), status_code=400)

    if isinstance(structured_result, dict):
        return JSONResponse(structured_result)
    return JSONResponse({"result": structured_result})


def _error_response(code: str, message: str, *, status_code: int) -> JSONResponse:
    """Return the stable error envelope used by the project."""

    return JSONResponse(
        {"ok": False, "error": {"code": code, "message": message}},
        status_code=status_code,
    )


def run_http_server(settings: Settings, server: ProfiledFastMCP) -> None:
    """Run the configured MCP server as a loopback-only HTTP application."""

    validate_http_host(settings.http_host)

    import uvicorn

    uvicorn.run(
        create_rest_app(server),
        host=settings.http_host,
        port=settings.http_port,
        log_level=settings.log_level.lower(),
    )
