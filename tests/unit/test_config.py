import json
from pathlib import Path

from reaper_mcp.config import Settings


def test_settings_default_to_minimal_tool_profile() -> None:
    assert Settings().tool_profile == "minimal"


def test_settings_load_allowed_media_source_roots_from_env(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv(
        "REAPER_MCP_ALLOWED_MEDIA_SOURCE_ROOTS",
        json.dumps([str(tmp_path)]),
    )

    settings = Settings()

    assert settings.allowed_media_source_roots == [tmp_path]


def test_settings_load_allowed_render_roots_from_env(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv(
        "REAPER_MCP_ALLOWED_RENDER_ROOTS",
        json.dumps([str(tmp_path)]),
    )

    settings = Settings()

    assert settings.allowed_render_roots == [tmp_path]


def test_settings_load_allowed_audio_roots_from_env(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv(
        "REAPER_MCP_ALLOWED_AUDIO_ROOTS",
        json.dumps([str(tmp_path)]),
    )

    settings = Settings()

    assert settings.allowed_audio_roots == [tmp_path]


def test_settings_load_audio_measurement_limits_from_env(monkeypatch) -> None:
    monkeypatch.setenv("REAPER_MCP_FFMPEG_EXECUTABLE", "/opt/ffmpeg")
    monkeypatch.setenv("REAPER_MCP_AUDIO_MEASUREMENT_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("REAPER_MCP_AUDIO_MEASUREMENT_MAX_OUTPUT_BYTES", "131072")

    settings = Settings()

    assert settings.ffmpeg_executable == "/opt/ffmpeg"
    assert settings.audio_measurement_timeout_seconds == 45.0
    assert settings.audio_measurement_max_output_bytes == 131072


def test_settings_require_explicit_render_background_confirmation(monkeypatch) -> None:
    monkeypatch.setenv("REAPER_MCP_RENDER_BACKGROUND_CONFIRMED", "true")

    settings = Settings()

    assert settings.render_background_confirmed is True


def test_settings_load_log_level_from_env(monkeypatch) -> None:
    monkeypatch.setenv("REAPER_MCP_LOG_LEVEL", "DEBUG")

    settings = Settings()

    assert settings.log_level == "DEBUG"
