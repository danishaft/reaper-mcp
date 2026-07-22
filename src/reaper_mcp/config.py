"""Runtime configuration for the REAPER MCP server."""

from pathlib import Path
from tempfile import gettempdir
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed server settings."""

    model_config = SettingsConfigDict(env_prefix="REAPER_MCP_")

    bridge_dir: Path = Field(
        default_factory=lambda: Path(gettempdir()) / "reaper-mcp-bridge"
    )
    bridge_timeout_seconds: float = 5.0
    bridge_poll_interval_seconds: float = 0.05
    bridge_stale_after_seconds: float = 300.0
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    tool_profile: Literal["minimal", "production", "midi", "mixing", "full"] = (
        "production"
    )
    render_timeout_seconds: float = 60.0
    render_poll_interval_seconds: float = 0.1
    render_background_confirmed: bool = False
    allowed_media_source_roots: list[Path] = Field(default_factory=list)
    allowed_project_roots: list[Path] = Field(default_factory=list)
    allowed_render_roots: list[Path] = Field(default_factory=list)


def get_settings() -> Settings:
    """Return settings loaded from environment variables."""

    return Settings()
