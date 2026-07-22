from pathlib import Path

import pytest
from mcp.shared.exceptions import McpError

from reaper_mcp.config import Settings
from reaper_mcp.profiles import CAPABILITY_TOOLS, MANAGEMENT_TOOLS
from reaper_mcp.server import create_server


async def test_production_profile_exposes_every_stable_capability(
    tmp_path: Path,
) -> None:
    server = create_server(
        Settings(
            bridge_dir=tmp_path,
            bridge_timeout_seconds=0.01,
            bridge_poll_interval_seconds=0.001,
        )
    )

    tools = await server.list_tools()
    expected = set(MANAGEMENT_TOOLS)
    for name, capability_tools in CAPABILITY_TOOLS.items():
        if name != "rendering":
            expected.update(capability_tools)

    assert {tool.name for tool in tools} == expected
    assert len(tools) == 104


async def test_full_profile_exposes_all_108_tools(tmp_path: Path) -> None:
    server = create_server(Settings(bridge_dir=tmp_path, tool_profile="full"))

    tools = await server.list_tools()
    expected = set(MANAGEMENT_TOOLS)
    for capability_tools in CAPABILITY_TOOLS.values():
        expected.update(capability_tools)

    assert {tool.name for tool in tools} == expected
    assert len(tools) == 108


async def test_disabled_tool_cannot_be_called_from_cached_discovery(
    tmp_path: Path,
) -> None:
    server = create_server(Settings(bridge_dir=tmp_path))

    with pytest.raises(McpError, match="not enabled"):
        await server.call_tool("render_project_status", {"job_id": "job-1"})


async def test_profile_management_changes_discovery(tmp_path: Path) -> None:
    server = create_server(Settings(bridge_dir=tmp_path, tool_profile="minimal"))

    initial = {tool.name for tool in await server.list_tools()}
    _, capabilities = await server.call_tool("list_capabilities", {})
    _, status = await server.call_tool("get_active_profile", {})
    await server.call_tool("enable_capability", {"capability": "midi"})
    enabled = {tool.name for tool in await server.list_tools()}
    await server.call_tool("disable_capability", {"capability": "midi"})
    disabled = {tool.name for tool in await server.list_tools()}
    await server.call_tool("set_active_profile", {"profile": "mixing"})
    mixing = {tool.name for tool in await server.list_tools()}

    assert "add_midi_notes" not in initial
    assert len(capabilities["capabilities"]) == 15
    assert status["active_profile"] == "minimal"
    assert "add_midi_notes" in enabled
    assert "add_midi_notes" not in disabled
    assert "list_track_fx" in mixing
    assert "add_midi_notes" not in mixing


async def test_health_check_tool_returns_bridge_not_running(tmp_path: Path) -> None:
    server = create_server(
        Settings(
            bridge_dir=tmp_path,
            bridge_timeout_seconds=0.01,
            bridge_poll_interval_seconds=0.001,
        )
    )

    _, structured_result = await server.call_tool("health_check", {})

    assert structured_result["ok"] is False
    assert structured_result["error"]["code"] == "bridge_not_running"
