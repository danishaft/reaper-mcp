from pathlib import Path

from reaper_mcp.config import Settings


def test_settings_load_allowed_media_source_roots_from_env(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv(
        "REAPER_MCP_ALLOWED_MEDIA_SOURCE_ROOTS",
        f'["{tmp_path}"]',
    )

    settings = Settings()

    assert settings.allowed_media_source_roots == [tmp_path]


def test_settings_load_allowed_render_roots_from_env(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv(
        "REAPER_MCP_ALLOWED_RENDER_ROOTS",
        f'["{tmp_path}"]',
    )

    settings = Settings()

    assert settings.allowed_render_roots == [tmp_path]


def test_settings_require_explicit_render_background_confirmation(monkeypatch) -> None:
    monkeypatch.setenv("REAPER_MCP_RENDER_BACKGROUND_CONFIRMED", "true")

    settings = Settings()

    assert settings.render_background_confirmed is True


def test_settings_load_log_level_from_env(monkeypatch) -> None:
    monkeypatch.setenv("REAPER_MCP_LOG_LEVEL", "DEBUG")

    settings = Settings()

    assert settings.log_level == "DEBUG"
