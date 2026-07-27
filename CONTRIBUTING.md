# Contributing to REAPER MCP

REAPER MCP accepts focused changes that keep producer workflows safe,
observable, and easy to test.

## Development setup

Use Python 3.11 or newer and `uv`:

```bash
git clone https://github.com/danishaft/reaper-mcp.git
cd reaper-mcp
uv sync
```

The Lua bridge and a local REAPER installation are required only for live
acceptance. Unit and contract tests do not require REAPER.

## Checks before a pull request

Run the checks from the repository root:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv build
```

Live acceptance is opt-in. Start an isolated REAPER instance with the bridge
and acceptance-probe scripts, then run:

```bash
REAPER_MCP_LIVE_TEST=1 \
REAPER_MCP_BRIDGE_DIR=/tmp/reaper-mcp-bridge \
uv run pytest tests/integration
```

## Engineering expectations

- Keep MCP tools thin and put workflow logic in services.
- Validate paths and object identity before bridge execution.
- Keep mutating operations inside one named REAPER undo block.
- Use stable GUIDs instead of relying on mutable indices.
- Add focused tests for new behavior and failure paths.
- Update the README or relevant document when behavior changes.

Use small conventional commits, such as `feat(midi): add note humanization` or
`fix(bridge): reject stale response files`.

## Pull requests

Keep one coherent change per pull request. Include the user-visible behavior,
verification performed, and any live REAPER limitation that remains. The CI
matrix checks Python 3.11 through 3.13 on Linux, macOS, and Windows.
