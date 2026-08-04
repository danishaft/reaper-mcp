import json
from argparse import Namespace
from pathlib import Path

from reaper_mcp import cli
from reaper_mcp.config import Settings


def _settings(tmp_path: Path) -> Settings:
    return Settings(bridge_dir=tmp_path)


def test_cli_lists_all_visible_tools(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(tmp_path))

    exit_code = cli.main(["tools"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["count"] == 26
    assert any(tool["name"] == "render_project" for tool in payload["tools"]) is False


def test_cli_calls_existing_tool_with_pretty_output(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(tmp_path))

    exit_code = cli.main(["call", "get_active_profile", "--pretty"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert json.loads(output)["active_profile"] == "minimal"
    assert '\n  "active_profile"' in output


def test_cli_profile_override_exposes_full_surface(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(tmp_path))

    exit_code = cli.main(["--profile", "full", "tools"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["count"] == 172


def test_cli_reports_invalid_json(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(tmp_path))

    exit_code = cli.main(["call", "get_active_profile", "--json", "[]"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert payload["error"]["code"] == "invalid_cli_request"


def test_cli_returns_failure_for_unavailable_reaper(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(tmp_path))

    exit_code = cli.main(["health"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["ok"] is False


def test_cli_parses_repeated_scalar_arguments() -> None:
    arguments = cli._parse_arguments(
        Namespace(arguments_json=None, argument_pairs=["muted=true", "name=Vocals"])
    )

    assert arguments == {"muted": True, "name": "Vocals"}
