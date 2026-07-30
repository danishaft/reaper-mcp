"""Runtime MCP tool profiles and capability visibility."""

from collections.abc import Sequence
from typing import Any, Literal, cast

from mcp import types
from mcp.server.fastmcp import FastMCP
from mcp.shared.exceptions import McpError

ToolProfile = Literal["minimal", "production", "midi", "mixing", "full"]

MANAGEMENT_TOOLS = frozenset(
    {
        "list_capabilities",
        "enable_capability",
        "disable_capability",
        "get_active_profile",
        "set_active_profile",
    }
)

CAPABILITY_TOOLS: dict[str, frozenset[str]] = {
    "core": frozenset(
        {
            "health_check",
            "get_reaper_version",
            "get_project_info",
            "get_bridge_status",
            "get_project_snapshot",
        }
    ),
    "tracks": frozenset(
        {
            "list_tracks",
            "create_track",
            "rename_track",
            "set_track_color",
            "set_track_mute",
            "set_track_solo",
            "set_track_arm",
            "set_track_volume",
            "set_track_pan",
            "set_track_recording",
            "set_track_folder_depth",
            "delete_track",
            "get_master_track",
            "set_master_volume",
            "set_master_pan",
            "set_master_mute",
        }
    ),
    "media": frozenset(
        {
            "list_media_items",
            "create_midi_item",
            "insert_audio_item",
            "move_media_item",
            "move_media_item_to_track",
            "resize_media_item",
            "duplicate_media_item",
            "split_media_item",
            "set_media_item_mute",
            "set_media_item_gain",
            "set_media_item_fade_in",
            "set_media_item_fade_out",
            "delete_media_item",
        }
    ),
    "midi": frozenset(
        {
            "get_midi_notes",
            "add_midi_note",
            "add_midi_notes",
            "update_midi_note",
            "delete_midi_notes",
            "list_midi_controller_events",
            "add_midi_controller_events",
            "update_midi_controller_event",
            "delete_midi_controller_events",
            "transpose_midi_notes",
            "nudge_midi_notes",
            "quantize_midi_notes",
            "humanize_midi_notes",
            "snap_midi_notes_to_scale",
            "shape_midi_note_velocities",
            "remove_midi_note_overlaps",
        }
    ),
    "transport": frozenset({"play", "stop", "stop_recording", "pause", "record"}),
    "fx": frozenset(
        {
            "list_available_fx",
            "list_track_fx",
            "list_take_fx",
            "add_fx",
            "add_take_fx",
            "remove_fx",
            "remove_take_fx",
            "set_fx_enabled",
            "set_take_fx_enabled",
            "get_fx_parameters",
            "set_fx_parameter",
            "get_fx_preset",
            "set_fx_preset",
            "get_fx_preset_index",
            "set_fx_preset_index",
            "navigate_fx_presets",
            "move_fx",
            "copy_fx_chain",
        }
    ),
    "freeze": frozenset({"get_track_freeze_state", "freeze_track", "unfreeze_track"}),
    "arrangement": frozenset(
        {
            "list_markers",
            "create_marker",
            "delete_marker",
            "list_regions",
            "create_region",
            "delete_region",
        }
    ),
    "automation": frozenset(
        {
            "list_track_envelopes",
            "ensure_track_envelope",
            "get_envelope_points",
            "add_envelope_points",
            "update_envelope_point",
            "delete_envelope_points",
            "delete_envelope_points_in_range",
            "get_track_automation_mode",
            "set_track_automation_mode",
        }
    ),
    "tempo": frozenset(
        {
            "get_tempo",
            "set_tempo",
            "get_time_signature",
            "set_time_signature",
            "list_tempo_markers",
            "create_tempo_marker",
            "update_tempo_marker",
            "delete_tempo_marker",
        }
    ),
    "takes": frozenset(
        {
            "list_item_takes",
            "add_empty_take",
            "set_active_take",
            "rename_take",
            "set_take_volume",
            "set_take_pan",
            "set_take_pitch",
            "set_take_playback_rate",
            "crop_to_active_take",
        }
    ),
    "navigation": frozenset(
        {
            "get_project_navigation",
            "set_edit_cursor",
            "set_time_selection",
            "clear_time_selection",
            "set_loop_points",
            "set_loop_enabled",
            "save_project",
            "save_project_as",
            "undo",
            "redo",
            "get_grid_settings",
            "set_grid_settings",
            "get_metronome",
            "set_metronome",
            "get_playback_rate",
            "set_playback_rate",
        }
    ),
    "routing": frozenset(
        {
            "list_track_sends",
            "create_track_send",
            "set_track_send",
            "remove_track_send",
            "setup_sidechain",
            "configure_reference_track",
        }
    ),
    "workflows": frozenset({"create_song_starter", "create_midi_pattern"}),
    "templates": frozenset(
        {
            "list_track_templates",
            "save_track_template",
            "apply_track_template",
            "delete_track_template",
        }
    ),
    "batch": frozenset({"batch_update_tracks"}),
    "analysis": frozenset(
        {
            "analyze_audio_file",
            "analyze_audio_program",
            "calculate_take_loudness",
            "measure_audio_file",
        }
    ),
    "vocal_tuning": frozenset(
        {
            "list_vocal_tuning_providers",
            "preview_vocal_tuning_plan",
            "apply_vocal_tuning_plan",
            "preview_vocal_tuning_preset_plan",
            "apply_vocal_tuning_preset_plan",
            "preview_vocal_tuning_plugin_plan",
            "apply_vocal_tuning_plugin_plan",
        }
    ),
    "mastering": frozenset(
        {
            "apply_mastering_plan",
            "approve_mastering_album",
            "approve_mastering_candidate",
            "compare_mastering_candidates",
            "create_mastering_candidate",
            "create_mastering_codec_preview",
            "create_mastering_session",
            "create_mastering_version_set",
            "create_stereo_mastering_project",
            "deliver_mastering_candidate",
            "prepare_mastering_audition",
            "prepare_mastering_album",
            "preview_mastering_plan",
        }
    ),
    "rendering": frozenset(
        {
            "render_project",
            "render_project_start",
            "render_project_status",
            "render_project_result",
        }
    ),
}

STABLE_CAPABILITIES = frozenset(CAPABILITY_TOOLS) - {
    "mastering",
    "rendering",
    "vocal_tuning",
}
PROFILE_CAPABILITIES: dict[ToolProfile, frozenset[str]] = {
    "minimal": frozenset({"core", "navigation"}),
    "production": STABLE_CAPABILITIES,
    "midi": frozenset(
        {
            "core",
            "tracks",
            "media",
            "midi",
            "transport",
            "arrangement",
            "automation",
            "tempo",
            "takes",
            "navigation",
            "workflows",
        }
    ),
    "mixing": frozenset(
        {
            "core",
            "tracks",
            "media",
            "transport",
            "fx",
            "freeze",
            "arrangement",
            "automation",
            "tempo",
            "takes",
            "navigation",
            "routing",
            "analysis",
            "vocal_tuning",
        }
    ),
    "full": frozenset(CAPABILITY_TOOLS),
}


class ToolProfileRegistry:
    """Own profile and capability overrides for one MCP server process."""

    def __init__(self, profile: ToolProfile = "production") -> None:
        self._profile = profile
        self._enabled_overrides: set[str] = set()
        self._disabled_overrides: set[str] = set()

    @property
    def profile(self) -> ToolProfile:
        return self._profile

    @property
    def active_capabilities(self) -> frozenset[str]:
        capabilities = set(PROFILE_CAPABILITIES[self._profile])
        capabilities.update(self._enabled_overrides)
        capabilities.difference_update(self._disabled_overrides)
        return frozenset(capabilities)

    @property
    def visible_tools(self) -> frozenset[str]:
        tools = set(MANAGEMENT_TOOLS)
        for capability in self.active_capabilities:
            tools.update(CAPABILITY_TOOLS[capability])
        return frozenset(tools)

    def set_profile(self, profile: str) -> dict[str, Any]:
        if profile not in PROFILE_CAPABILITIES:
            raise ValueError(f"Unknown tool profile: {profile}")
        self._profile = cast(ToolProfile, profile)
        self._enabled_overrides.clear()
        self._disabled_overrides.clear()
        return self.status()

    def enable(self, capability: str) -> dict[str, Any]:
        self._require_capability(capability)
        self._disabled_overrides.discard(capability)
        self._enabled_overrides.add(capability)
        return self.status()

    def disable(self, capability: str) -> dict[str, Any]:
        self._require_capability(capability)
        self._enabled_overrides.discard(capability)
        self._disabled_overrides.add(capability)
        return self.status()

    def status(self) -> dict[str, Any]:
        return {
            "active_profile": self._profile,
            "active_capabilities": sorted(self.active_capabilities),
            "enabled_overrides": sorted(self._enabled_overrides),
            "disabled_overrides": sorted(self._disabled_overrides),
            "visible_tool_count": len(self.visible_tools),
        }

    def capabilities(self) -> dict[str, Any]:
        active = self.active_capabilities
        return {
            **self.status(),
            "capabilities": [
                {
                    "name": name,
                    "enabled": name in active,
                    "tools": sorted(tools),
                    "tool_count": len(tools),
                }
                for name, tools in sorted(CAPABILITY_TOOLS.items())
            ],
            "profiles": {
                name: sorted(capabilities)
                for name, capabilities in PROFILE_CAPABILITIES.items()
            },
        }

    @staticmethod
    def _require_capability(capability: str) -> None:
        if capability not in CAPABILITY_TOOLS:
            raise ValueError(f"Unknown capability: {capability}")


class ProfiledFastMCP(FastMCP):
    """FastMCP server that filters discovery and calls through one registry."""

    def __init__(self, name: str, registry: ToolProfileRegistry) -> None:
        super().__init__(name)
        self.profile_registry = registry

    async def list_tools(self) -> list[types.Tool]:
        tools = await super().list_tools()
        visible = self.profile_registry.visible_tools
        return [tool for tool in tools if tool.name in visible]

    async def call_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> Sequence[types.ContentBlock] | dict[str, Any]:
        if name not in self.profile_registry.visible_tools:
            raise McpError(
                types.ErrorData(
                    code=-32601,
                    message=(
                        f"Tool '{name}' is not enabled in the active "
                        f"'{self.profile_registry.profile}' profile."
                    ),
                )
            )
        return await super().call_tool(name, arguments)
