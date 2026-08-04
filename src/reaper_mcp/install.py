"""Install the packaged Lua bridge into REAPER's resource directory."""

from __future__ import annotations

import argparse
import os
import platform
import sys
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

BRIDGE_FILENAME = "reaper_mcp_bridge.lua"
BRIDGE_MODULE_DIRNAME = "reaper_mcp_bridge_modules"
PACKAGED_BRIDGE = ("resources", BRIDGE_FILENAME)
PACKAGED_BRIDGE_MODULES = ("resources", BRIDGE_MODULE_DIRNAME)


@dataclass(frozen=True)
class BridgeInstallResult:
    """Describe one bridge installation attempt."""

    resource_path: Path
    target_path: Path
    backup_path: Path | None
    module_paths: tuple[Path, ...]
    module_backup_paths: tuple[Path, ...]
    changed: bool


def default_reaper_resource_path(
    *,
    system: str | None = None,
    home: Path | None = None,
    environ: dict[str, str] | None = None,
) -> Path:
    """Return REAPER's conventional resource directory for the platform."""

    current_system = system or platform.system()
    current_home = home or Path.home()
    current_environ = environ or os.environ

    if current_system == "Darwin":
        return current_home / "Library" / "Application Support" / "REAPER"
    if current_system == "Windows":
        app_data = current_environ.get("APPDATA")
        if app_data:
            return Path(app_data) / "REAPER"
        return current_home / "AppData" / "Roaming" / "REAPER"
    if current_system == "Linux":
        return current_home / ".config" / "REAPER"
    raise ValueError(f"Unsupported operating system: {current_system}")


def load_bridge_source(source_path: Path | None = None) -> bytes:
    """Load the bridge from an override, an installed wheel, or the checkout."""

    if source_path is not None:
        return source_path.expanduser().resolve().read_bytes()

    packaged = files("reaper_mcp").joinpath(*PACKAGED_BRIDGE)
    if packaged.is_file():
        return packaged.read_bytes()

    checkout_bridge = Path(__file__).resolve().parents[2] / "lua" / BRIDGE_FILENAME
    if checkout_bridge.is_file():
        return checkout_bridge.read_bytes()
    raise FileNotFoundError("The packaged REAPER Lua bridge could not be found.")


def load_bridge_module_sources(
    source_path: Path | None = None,
) -> dict[str, bytes]:
    """Load optional Lua command modules beside the selected bridge."""

    if source_path is not None:
        module_dir = source_path.expanduser().resolve().parent / BRIDGE_MODULE_DIRNAME
        if not module_dir.is_dir():
            return {}
        return {
            path.name: path.read_bytes()
            for path in sorted(module_dir.glob("*.lua"))
            if path.is_file()
        }

    packaged = files("reaper_mcp").joinpath(*PACKAGED_BRIDGE_MODULES)
    if packaged.is_dir():
        return {
            entry.name: entry.read_bytes()
            for entry in sorted(packaged.iterdir(), key=lambda item: item.name)
            if entry.is_file() and entry.name.endswith(".lua")
        }

    checkout_dir = Path(__file__).resolve().parents[2] / "lua" / BRIDGE_MODULE_DIRNAME
    if checkout_dir.is_dir():
        return {
            path.name: path.read_bytes()
            for path in sorted(checkout_dir.glob("*.lua"))
            if path.is_file()
        }
    return {}


def _install_file(target_path: Path, content: bytes) -> tuple[bool, Path | None]:
    """Atomically install one bridge file and back up changed content."""

    if target_path.is_file() and target_path.read_bytes() == content:
        return False, None
    backup_path = None
    if target_path.exists():
        if not target_path.is_file():
            raise IsADirectoryError(f"Bridge target is not a file: {target_path}")
        backup_path = target_path.with_suffix(f"{target_path.suffix}.backup")
        backup_path.write_bytes(target_path.read_bytes())
    temporary_path = target_path.with_suffix(f"{target_path.suffix}.tmp")
    temporary_path.write_bytes(content)
    temporary_path.replace(target_path)
    return True, backup_path


def install_bridge(
    resource_path: Path | None = None,
    *,
    source_path: Path | None = None,
) -> BridgeInstallResult:
    """Install the bridge and preserve a changed existing target as a backup."""

    resolved_resource_path = (
        (resource_path or default_reaper_resource_path()).expanduser().resolve()
    )
    if not resolved_resource_path.is_dir():
        raise FileNotFoundError(
            f"REAPER resource directory does not exist: {resolved_resource_path}"
        )

    bridge_source = load_bridge_source(source_path)
    module_sources = load_bridge_module_sources(source_path)
    scripts_path = resolved_resource_path / "Scripts"
    scripts_path.mkdir(exist_ok=True)
    target_path = scripts_path / BRIDGE_FILENAME
    bridge_changed, backup_path = _install_file(target_path, bridge_source)

    module_paths: list[Path] = []
    module_backup_paths: list[Path] = []
    modules_changed = False
    if module_sources:
        module_dir = scripts_path / BRIDGE_MODULE_DIRNAME
        if module_dir.exists() and not module_dir.is_dir():
            raise NotADirectoryError(
                f"Bridge module target is not a directory: {module_dir}"
            )
        module_dir.mkdir(exist_ok=True)
        for filename, content in module_sources.items():
            module_path = module_dir / filename
            changed, module_backup_path = _install_file(module_path, content)
            modules_changed = modules_changed or changed
            module_paths.append(module_path)
            if module_backup_path is not None:
                module_backup_paths.append(module_backup_path)

    return BridgeInstallResult(
        resource_path=resolved_resource_path,
        target_path=target_path,
        backup_path=backup_path,
        module_paths=tuple(module_paths),
        module_backup_paths=tuple(module_backup_paths),
        changed=bridge_changed or modules_changed,
    )


def build_parser() -> argparse.ArgumentParser:
    """Create the bridge installer command-line parser."""

    parser = argparse.ArgumentParser(
        prog="reaper-mcp-install",
        description="Install the REAPER MCP Lua bridge.",
    )
    parser.add_argument(
        "--resource-path",
        type=Path,
        help="REAPER resource directory. Defaults to the platform convention.",
    )
    parser.add_argument(
        "--bridge-source",
        type=Path,
        help="Optional Lua bridge override for development.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the bridge installer command."""

    args = build_parser().parse_args(argv)
    try:
        result = install_bridge(args.resource_path, source_path=args.bridge_source)
    except (OSError, ValueError) as exc:
        print(f"reaper-mcp-install: {exc}", file=sys.stderr)
        return 1

    if result.changed:
        print(f"Installed REAPER MCP bridge: {result.target_path}")
        if result.module_paths:
            print(f"Installed {len(result.module_paths)} Lua command modules.")
        if result.backup_path:
            print(f"Backed up previous bridge: {result.backup_path}")
        for backup_path in result.module_backup_paths:
            print(f"Backed up previous bridge module: {backup_path}")
    else:
        print(f"REAPER MCP bridge is already current: {result.target_path}")
    print("Next steps:")
    print("1. Open REAPER and choose Actions > Show action list.")
    print("2. Choose New action > Load ReaScript, then select:")
    print(f"   {result.target_path}")
    print("3. Select reaper_mcp_bridge.lua in the action list and choose Run.")
    print("4. Start the server with: reaper-mcp")
    print("5. Verify the connection with: reaper-mcp-cli health")
    print("When running from source, prefix these commands with: uv run")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
