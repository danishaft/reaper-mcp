from pathlib import Path

import httpx
import pytest

from reaper_mcp.config import Settings
from reaper_mcp.rest import create_rest_app, validate_http_host
from reaper_mcp.server import create_server


@pytest.fixture
def rest_app(tmp_path: Path):
    server = create_server(Settings(bridge_dir=tmp_path))
    return create_rest_app(server)


async def test_rest_root_and_tool_discovery(rest_app) -> None:
    transport = httpx.ASGITransport(app=rest_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        root_response = await client.get("/")
        tools_response = await client.get("/api/tools")

    assert root_response.status_code == 200
    assert root_response.json()["transport"] == "http"
    assert tools_response.status_code == 200
    assert tools_response.json()["count"] == 142
    assert any(
        tool["name"] == "get_project_snapshot"
        for tool in tools_response.json()["tools"]
    )


async def test_rest_calls_existing_mcp_tool(rest_app) -> None:
    transport = httpx.ASGITransport(app=rest_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/tools/get_active_profile", json={})

    assert response.status_code == 200
    assert response.json()["active_profile"] == "production"


async def test_rest_rejects_invalid_arguments(rest_app) -> None:
    transport = httpx.ASGITransport(app=rest_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/tools/get_active_profile", json=[])

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_arguments"


async def test_rest_rejects_hidden_tools(rest_app) -> None:
    transport = httpx.ASGITransport(app=rest_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/tools/render_project_status", json={"job_id": "job-1"}
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "tool_not_found"


def test_http_host_must_be_loopback() -> None:
    validate_http_host("127.0.0.1")
    validate_http_host("::1")

    with pytest.raises(ValueError, match="loopback"):
        validate_http_host("0.0.0.0")
