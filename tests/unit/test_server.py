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
            tool_profile="production",
            bridge_timeout_seconds=0.01,
            bridge_poll_interval_seconds=0.001,
        )
    )

    tools = await server.list_tools()
    expected = set(MANAGEMENT_TOOLS)
    for name, capability_tools in CAPABILITY_TOOLS.items():
        if name not in {"mastering", "rendering", "vocal_tuning"}:
            expected.update(capability_tools)

    assert {tool.name for tool in tools} == expected
    assert len(tools) == 146
    assert "create_mastering_session" not in expected


async def test_default_profile_exposes_minimal_surface(tmp_path: Path) -> None:
    server = create_server(Settings(bridge_dir=tmp_path))

    tools = await server.list_tools()

    assert len(tools) == 26
    assert "get_project_snapshot" in {tool.name for tool in tools}
    assert "add_midi_notes" not in {tool.name for tool in tools}


async def test_full_profile_exposes_all_tools(tmp_path: Path) -> None:
    server = create_server(Settings(bridge_dir=tmp_path, tool_profile="full"))

    tools = await server.list_tools()
    expected = set(MANAGEMENT_TOOLS)
    for capability_tools in CAPABILITY_TOOLS.values():
        expected.update(capability_tools)

    assert {tool.name for tool in tools} == expected
    assert len(tools) == 170
    assert "create_mastering_session" in expected
    assert "analyze_audio_program" in expected
    assert "preview_mastering_plan" in expected
    assert "apply_mastering_plan" in expected
    assert "create_stereo_mastering_project" in expected
    assert "create_mastering_candidate" in expected
    assert "create_mastering_codec_preview" in expected
    assert "create_mastering_version_set" in expected
    assert "compare_mastering_candidates" in expected
    assert "prepare_mastering_audition" in expected
    assert "prepare_mastering_album" in expected
    assert "approve_mastering_album" in expected
    assert "approve_mastering_candidate" in expected
    assert "deliver_mastering_candidate" in expected
    assert "preview_vocal_tuning_plan" in expected
    assert "preview_vocal_tuning_preset_plan" in expected
    assert "apply_vocal_tuning_preset_plan" in expected
    assert "preview_vocal_tuning_plugin_plan" in expected
    assert "apply_vocal_tuning_plugin_plan" in expected


async def test_fx_tools_publish_guarded_identity_schema(tmp_path: Path) -> None:
    server = create_server(Settings(bridge_dir=tmp_path, tool_profile="mixing"))

    tools = {tool.name: tool for tool in await server.list_tools()}
    schema = tools["get_fx_parameters"].inputSchema
    assert schema["properties"]["fx_identity"] == {"$ref": "#/$defs/FxIdentity"}
    identity_schema = schema["$defs"]["FxIdentity"]

    assert identity_schema["properties"] == {
        "track_guid": {
            "minLength": 1,
            "title": "Track Guid",
            "type": "string",
        },
        "index": {"minimum": 0, "title": "Index", "type": "integer"},
        "expected_identity": {
            "minLength": 1,
            "title": "Expected Identity",
            "type": "string",
        },
        "expected_name": {
            "minLength": 1,
            "title": "Expected Name",
            "type": "string",
        },
        "expected_guid": {
            "anyOf": [{"type": "string"}, {"type": "null"}],
            "default": None,
            "title": "Expected Guid",
        },
    }
    assert identity_schema["required"] == [
        "track_guid",
        "index",
        "expected_identity",
        "expected_name",
    ]


async def test_media_track_move_publishes_source_guard_schema(tmp_path: Path) -> None:
    server = create_server(Settings(bridge_dir=tmp_path, tool_profile="mixing"))

    tools = {tool.name: tool for tool in await server.list_tools()}
    schema = tools["move_media_item_to_track"].inputSchema

    assert schema["required"] == [
        "item_guid",
        "destination_track_guid",
        "expected_source_track_guid",
    ]
    assert set(schema["properties"]) == {
        "item_guid",
        "destination_track_guid",
        "expected_source_track_guid",
    }


async def test_mastering_plan_tool_publishes_unambiguous_operation_shapes(
    tmp_path: Path,
) -> None:
    server = create_server(Settings(bridge_dir=tmp_path, tool_profile="full"))

    tools = {tool.name: tool for tool in await server.list_tools()}
    schema = tools["preview_mastering_plan"].inputSchema
    operation_items = schema["properties"]["operations"]["items"]

    assert operation_items["anyOf"] == [
        {"$ref": "#/$defs/SetMasteringFxParameter"},
        {"$ref": "#/$defs/SetMasteringFxEnabled"},
    ]
    assert schema["$defs"]["SetMasteringFxEnabled"]["properties"]["type"] == {
        "const": "set_enabled",
        "default": "set_enabled",
        "title": "Type",
        "type": "string",
    }
    assert "enabled" in schema["$defs"]["SetMasteringFxEnabled"]["required"]
    assert {
        "parameter_index",
        "normalized_value",
    } <= set(schema["$defs"]["SetMasteringFxParameter"]["required"])


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
    assert len(capabilities["capabilities"]) == 20
    assert status["active_profile"] == "minimal"
    assert "add_midi_notes" in enabled
    assert "add_midi_notes" not in disabled
    assert "list_track_fx" in mixing
    assert "measure_audio_file" in mixing
    assert "preview_vocal_tuning_plan" in mixing
    assert "add_midi_notes" not in mixing


async def test_vocal_tuning_tool_publishes_explicit_segment_schema(
    tmp_path: Path,
) -> None:
    server = create_server(Settings(bridge_dir=tmp_path, tool_profile="mixing"))

    tools = {tool.name: tool for tool in await server.list_tools()}
    schema = tools["preview_vocal_tuning_plan"].inputSchema
    segment = schema["$defs"]["PitchCorrectionSegment"]

    assert schema["properties"]["corrections"]["items"] == {
        "$ref": "#/$defs/PitchCorrectionSegment"
    }
    assert {
        "segment_id",
        "start_seconds",
        "end_seconds",
        "correction_cents",
        "rationale",
    } <= set(segment["required"])


async def test_vocal_tuning_preset_tool_requires_first_fx_slot(
    tmp_path: Path,
) -> None:
    server = create_server(Settings(bridge_dir=tmp_path, tool_profile="mixing"))

    tools = {tool.name: tool for tool in await server.list_tools()}
    schema = tools["preview_vocal_tuning_preset_plan"].inputSchema

    assert schema["properties"]["insert_index"]["const"] == 0
    assert schema["properties"]["preset_name"]["minLength"] == 1


async def test_vocal_tuning_plugin_tool_publishes_x42_settings(
    tmp_path: Path,
) -> None:
    server = create_server(Settings(bridge_dir=tmp_path, tool_profile="mixing"))

    tools = {tool.name: tool for tool in await server.list_tools()}
    schema = tools["preview_vocal_tuning_plugin_plan"].inputSchema
    settings = schema["$defs"]["X42AutoTuneSettings"]

    assert schema["properties"]["insert_index"]["const"] == 0
    assert {
        "root_pitch_class",
        "scale",
        "correction_amount",
        "smoothing_seconds",
        "bias",
    } <= set(settings["required"])


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
