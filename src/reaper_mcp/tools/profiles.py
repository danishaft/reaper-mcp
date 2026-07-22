"""MCP tool profile and capability management."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from reaper_mcp.profiles import ToolProfileRegistry


def register_profile_tools(server: FastMCP, registry: ToolProfileRegistry) -> None:
    """Register runtime tool discovery controls."""

    @server.tool(name="list_capabilities")
    def list_capabilities() -> dict[str, Any]:
        """List capability groups, profiles, and current visibility state."""

        return registry.capabilities()

    @server.tool(name="enable_capability")
    def enable_capability(capability: str) -> dict[str, Any]:
        """Expose one capability group in addition to the active profile."""

        return registry.enable(capability)

    @server.tool(name="disable_capability")
    def disable_capability(capability: str) -> dict[str, Any]:
        """Hide one capability group from the active profile."""

        return registry.disable(capability)

    @server.tool(name="get_active_profile")
    def get_active_profile() -> dict[str, Any]:
        """Return the active profile and capability overrides."""

        return registry.status()

    @server.tool(name="set_active_profile")
    def set_active_profile(profile: str) -> dict[str, Any]:
        """Select a profile and clear all prior capability overrides."""

        return registry.set_profile(profile)
