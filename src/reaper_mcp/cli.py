"""Command-line adapter for the complete REAPER MCP tool surface."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Sequence
from typing import Any

from mcp.shared.exceptions import McpError

from reaper_mcp.config import Settings, get_settings
from reaper_mcp.logging import configure_logging
from reaper_mcp.profiles import ProfiledFastMCP
from reaper_mcp.server import create_server


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser without creating a REAPER connection."""

    parser = argparse.ArgumentParser(
        prog="reaper-mcp-cli",
        description="Call REAPER MCP tools from a shell or script.",
    )
    parser.add_argument(
        "--profile",
        choices=("minimal", "production", "midi", "mixing", "full"),
        help="Override REAPER_MCP_TOOL_PROFILE for this invocation.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    _add_output_options(commands.add_parser("tools", help="List visible tools."))
    _add_output_options(
        commands.add_parser("capabilities", help="List active capabilities.")
    )
    _add_tool_command(
        commands.add_parser("health", help="Check REAPER health."), "health_check"
    )
    _add_tool_command(
        commands.add_parser("profile", help="Show the active tool profile."),
        "get_active_profile",
    )

    call = commands.add_parser(
        "call",
        help="Call any visible MCP tool with a JSON object of arguments.",
    )
    call.add_argument("tool_name", help="MCP tool name.")
    _add_call_options(call)

    project = commands.add_parser("project", help="Run project operations.")
    project_commands = project.add_subparsers(dest="project_command", required=True)
    _add_tool_command(
        project_commands.add_parser("snapshot", help="Read the project snapshot."),
        "get_project_snapshot",
    )

    tracks = commands.add_parser("tracks", help="Run track operations.")
    track_commands = tracks.add_subparsers(dest="tracks_command", required=True)
    _add_tool_command(
        track_commands.add_parser("list", help="List project tracks."), "list_tracks"
    )

    transport = commands.add_parser("transport", help="Control REAPER transport.")
    transport_commands = transport.add_subparsers(
        dest="transport_command", required=True
    )
    for command, tool_name in (
        ("play", "play"),
        ("stop", "stop"),
        ("pause", "pause"),
        ("record", "record"),
        ("stop-recording", "stop_recording"),
    ):
        _add_tool_command(
            transport_commands.add_parser(command, help=f"Call `{tool_name}`."),
            tool_name,
        )

    render = commands.add_parser("render", help="Run render operations.")
    render_commands = render.add_subparsers(dest="render_command", required=True)
    _add_tool_command(
        render_commands.add_parser("project", help="Render the project."),
        "render_project",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run one CLI command and return a shell-compatible exit code."""

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        settings = get_settings()
        if args.profile is not None:
            settings = settings.model_copy(update={"tool_profile": args.profile})
        configure_logging(settings.log_level)
        result, exit_code = asyncio.run(_run_command(args, settings))
    except (ValueError, json.JSONDecodeError) as exc:
        result = _error_payload("invalid_cli_request", str(exc))
        exit_code = 2

    print(_format_output(result, getattr(args, "pretty", False)))
    return exit_code


async def _run_command(
    args: argparse.Namespace, settings: Settings
) -> tuple[dict[str, Any], int]:
    """Execute one parsed command through the existing MCP server."""

    server = create_server(settings)
    if args.command == "tools":
        tools = await server.list_tools()
        return {
            "tools": [tool.model_dump(mode="json") for tool in tools],
            "count": len(tools),
        }, 0
    if args.command == "capabilities":
        return await _call_tool(server, "list_capabilities", {}), 0

    tool_name = _tool_name(args)
    arguments = _parse_arguments(args)
    result = await _call_tool(server, tool_name, arguments)
    return result, 1 if result.get("ok") is False else 0


async def _call_tool(
    server: ProfiledFastMCP, tool_name: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    """Call one visible MCP tool and normalize CLI errors."""

    try:
        _, structured_result = await server.call_tool(tool_name, arguments)
    except McpError as exc:
        return _error_payload("tool_not_found", str(exc))
    except ValueError as exc:
        return _error_payload("invalid_arguments", str(exc))

    if isinstance(structured_result, dict):
        return structured_result
    return {"result": structured_result}


def _tool_name(args: argparse.Namespace) -> str:
    """Resolve a generic call or convenience command to an MCP tool name."""

    if hasattr(args, "tool_name"):
        return args.tool_name
    raise ValueError("No MCP tool was selected.")


def _parse_arguments(args: argparse.Namespace) -> dict[str, Any]:
    """Parse either one JSON object or repeated simple key-value arguments."""

    arguments_json = getattr(args, "arguments_json", None)
    argument_pairs = getattr(args, "argument_pairs", None)
    if arguments_json is not None:
        parsed = json.loads(arguments_json)
        if not isinstance(parsed, dict):
            raise ValueError("--json must contain a JSON object.")
        return parsed
    if argument_pairs:
        parsed_pairs = [_parse_pair(pair) for pair in argument_pairs]
        return dict(parsed_pairs)
    return {}


def _parse_pair(pair: str) -> tuple[str, Any]:
    """Parse a `key=value` argument, decoding JSON scalar values when possible."""

    key, separator, raw_value = pair.partition("=")
    if not separator or not key:
        raise ValueError("Each --arg value must use the form key=value.")
    try:
        value = json.loads(raw_value)
    except json.JSONDecodeError:
        value = raw_value
    return key, value


def _add_output_options(parser: argparse.ArgumentParser) -> None:
    """Add output formatting options to a read-only command."""

    parser.add_argument("--pretty", action="store_true", help="Indent JSON output.")


def _add_call_options(parser: argparse.ArgumentParser) -> None:
    """Add complete JSON and scalar argument options to a tool command."""

    arguments = parser.add_mutually_exclusive_group()
    arguments.add_argument(
        "--json",
        dest="arguments_json",
        help="JSON object containing tool arguments.",
    )
    arguments.add_argument(
        "--arg",
        dest="argument_pairs",
        action="append",
        help="Tool argument in key=value form; repeat as needed.",
    )
    parser.add_argument("--pretty", action="store_true", help="Indent JSON output.")


def _add_tool_command(parser: argparse.ArgumentParser, tool_name: str) -> None:
    """Configure a convenience command to call one MCP tool."""

    parser.set_defaults(tool_name=tool_name)
    _add_call_options(parser)


def _format_output(payload: dict[str, Any], pretty: bool) -> str:
    """Serialize a CLI result as compact or readable JSON."""

    if pretty:
        return json.dumps(payload, indent=2, ensure_ascii=False)
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def _error_payload(code: str, message: str) -> dict[str, Any]:
    """Build the stable error shape shared by CLI, REST, and MCP callers."""

    return {"ok": False, "error": {"code": code, "message": message}}


if __name__ == "__main__":
    raise SystemExit(main())
