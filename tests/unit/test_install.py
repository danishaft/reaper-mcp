"""Tests for the packaged REAPER bridge installer."""

from pathlib import Path

import pytest

from reaper_mcp.install import (
    BRIDGE_FILENAME,
    BRIDGE_MODULE_DIRNAME,
    default_reaper_resource_path,
    install_bridge,
    load_bridge_module_sources,
    load_bridge_source,
    main,
)


@pytest.mark.parametrize(
    ("system", "expected"),
    [
        ("Linux", Path("/users/test/.config/REAPER")),
        ("Darwin", Path("/users/test/Library/Application Support/REAPER")),
        ("Windows", Path("C:/Users/test/AppData/Roaming/REAPER")),
    ],
)
def test_default_reaper_resource_path(system: str, expected: Path) -> None:
    assert (
        default_reaper_resource_path(
            system=system,
            home=Path("/users/test"),
            environ={"APPDATA": "C:/Users/test/AppData/Roaming"},
        )
        == expected
    )


def test_default_reaper_resource_path_rejects_unknown_platform() -> None:
    with pytest.raises(ValueError, match="Unsupported operating system"):
        default_reaper_resource_path(system="Plan9")


def test_install_bridge_is_idempotent_and_backs_up_changes(tmp_path: Path) -> None:
    resource_path = tmp_path / "REAPER"
    resource_path.mkdir()
    source_path = tmp_path / "bridge.lua"
    source_path.write_text("return 'first'\n", encoding="utf-8")
    module_dir = tmp_path / BRIDGE_MODULE_DIRNAME
    module_dir.mkdir()
    module_path = module_dir / "commands.lua"
    module_path.write_text("return 'module first'\n", encoding="utf-8")

    first = install_bridge(resource_path, source_path=source_path)
    second = install_bridge(resource_path, source_path=source_path)
    source_path.write_text("return 'second'\n", encoding="utf-8")
    module_path.write_text("return 'module second'\n", encoding="utf-8")
    third = install_bridge(resource_path, source_path=source_path)

    assert first.changed is True
    assert second.changed is False
    assert third.changed is True
    assert third.target_path.read_text(encoding="utf-8") == "return 'second'\n"
    assert len(third.module_paths) == 1
    assert third.module_paths[0].read_text(encoding="utf-8") == (
        "return 'module second'\n"
    )
    assert third.backup_path is not None
    assert third.backup_path.read_text(encoding="utf-8") == "return 'first'\n"
    assert len(third.module_backup_paths) == 1
    assert third.module_backup_paths[0].read_text(encoding="utf-8") == (
        "return 'module first'\n"
    )


def test_install_bridge_requires_existing_resource_directory(tmp_path: Path) -> None:
    source_path = tmp_path / "bridge.lua"
    source_path.write_text("return true\n", encoding="utf-8")

    with pytest.raises(FileNotFoundError, match="resource directory"):
        install_bridge(tmp_path / "missing", source_path=source_path)


def test_checkout_bridge_source_is_available() -> None:
    source = load_bridge_source()
    modules = load_bridge_module_sources()

    assert b"BRIDGE_VERSION" in source
    assert set(modules) == {
        "automation_navigation.lua",
        "command_execution.lua",
        "fx_arrangement_tempo.lua",
        "media_midi.lua",
        "project_routing_transport.lua",
        "render.lua",
        "vocal_tuning.lua",
    }


def test_main_installs_bridge(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    resource_path = tmp_path / "REAPER"
    resource_path.mkdir()
    source_path = tmp_path / "bridge.lua"
    source_path.write_text("return true\n", encoding="utf-8")

    result = main(
        [
            "--resource-path",
            str(resource_path),
            "--bridge-source",
            str(source_path),
        ]
    )

    assert result == 0
    assert (resource_path / "Scripts" / BRIDGE_FILENAME).is_file()
    assert "Installed REAPER MCP bridge" in capsys.readouterr().out
