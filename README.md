<p align="center">
  <img src="assets/reaper-mcp-hero.png" alt="REAPER MCP producer workflow" width="1100">
</p>

<!-- Replace the hero image with the product demo video when it is ready. -->

<h1 align="center">REAPER MCP</h1>

<p align="center">
  A safe, producer-focused MCP server for controlling REAPER with AI,
  scripts, and the command line.
</p>

<p align="center">
  <a href="https://github.com/danishaft/reaper-mcp/blob/main/LICENSE">
    <img src="https://img.shields.io/badge/license-MIT-yellow.svg?style=flat-square" alt="MIT License">
  </a>
  <img src="https://img.shields.io/badge/python-3.11%2B-blue.svg?style=flat-square" alt="Python 3.11 or newer">
  <img src="https://img.shields.io/badge/Linux-verified-25a162.svg?style=flat-square" alt="Linux verified">
  <img src="https://img.shields.io/badge/macOS-not%20yet%20verified-lightgrey.svg?style=flat-square" alt="macOS not yet verified">
  <img src="https://img.shields.io/badge/Windows-not%20yet%20verified-lightgrey.svg?style=flat-square" alt="Windows not yet verified">
  <img src="https://img.shields.io/badge/MCP-stdio%20%7C%20REST-6f42c1.svg?style=flat-square" alt="MCP stdio and REST">
  <img src="https://img.shields.io/badge/CLI-supported-6f42c1.svg?style=flat-square" alt="CLI supported">
  <img src="https://img.shields.io/badge/tools-146-6f42c1.svg?style=flat-square" alt="146 tools">
</p>

<p align="center">
  <a href="#quick-start">Quick start</a> ·
  <a href="#interfaces">Interfaces</a> ·
  <a href="docs/reaper-mcp-product-architecture-spec.md">Architecture</a> ·
  <a href="docs/reaper-mcp-product-reality-audit.md">Acceptance audit</a>
</p>

## What it is

REAPER MCP connects an AI client or local script to a real REAPER project. It
keeps the producer in control with typed requests, stable project identities,
preflight validation, one-step undo, default-deny file policies, and truthful
structured results.

The server runs locally. Python owns the MCP tools, services, safety checks,
profiles, and workflows. A Lua bridge runs inside REAPER and executes the
approved ReaScript commands.

## What producers can do

| Workflow | Capabilities |
| --- | --- |
| **Build** | Create tracks, MIDI items, song starters, chord progressions, and arpeggios |
| **Arrange** | Move and split media items, manage takes, markers, regions, tempo, and time signatures |
| **Mix** | Control levels, pan, mute, solo, recording inputs, routing, sidechains, FX, presets, and automation |
| **Edit MIDI** | Add, update, delete, transpose, nudge, quantize, humanize, scale-snap, and shape notes |
| **Manage projects** | Save projects, templates, folders, grid, metronome, playback, freeze, and undo/redo |
| **Analyze** | Inspect WAV files, calculate take loudness, and inspect project state |
| **Render** | Render approved WAV output with path checks and completion verification |

The default `production` profile exposes 142 stable tools. The `full` profile
exposes all 146 tools, including experimental render lifecycle operations.

## Interfaces

All interfaces use the same services, profiles, safety rules, error model, and
Lua bridge. They are different ways to reach the same product.

| Interface | Best for | Start |
| --- | --- | --- |
| **MCP** | Claude, Codex, Cursor, and other AI clients | `uv run reaper-mcp` |
| **CLI** | Producers, shell scripts, automation, and CI | `uv run reaper-mcp-cli` |
| **REST** | Local apps, integrations, and future video or web clients | `REAPER_MCP_TRANSPORT=http uv run reaper-mcp` |

## Quick start

REAPER MCP currently targets Python 3.11 or newer, `uv`, and a local REAPER
installation. Linux with REAPER 7.66 is the live-verified environment.

### Install

```bash
git clone https://github.com/danishaft/reaper-mcp.git
cd reaper-mcp
uv sync
uv run reaper-mcp-install
```

Open REAPER, load `reaper_mcp_bridge.lua` from the Actions list, and run it as
a ReaScript. Then start the MCP server:

```bash
uv run reaper-mcp
```

Check the bridge before making changes:

```bash
uv run reaper-mcp-cli health
```

## MCP setup

Add the server to an MCP client that supports stdio transport:

```json
{
  "mcpServers": {
    "reaper-mcp": {
      "command": "uv",
      "args": [
        "--directory",
        "/home/you/projects/reaper-mcp",
        "run",
        "reaper-mcp"
      ],
      "env": {
        "REAPER_MCP_BRIDGE_DIR": "/tmp/reaper-mcp-bridge"
      }
    }
  }
}
```

The server exposes the `production` profile by default. Use the profile tools
or set `REAPER_MCP_TOOL_PROFILE` to choose `minimal`, `midi`, `mixing`, or
`full`.

## CLI usage

The CLI covers every visible MCP tool through `call`. The aliases are shortcuts
for common producer operations; they do not create a second implementation.

```bash
# Discover the active tool surface.
uv run reaper-mcp-cli tools --pretty

# Call any tool with a JSON object.
uv run reaper-mcp-cli call set_tempo --json '{"bpm": 96}'

# Use readable producer-facing aliases.
uv run reaper-mcp-cli project snapshot
uv run reaper-mcp-cli tracks list
uv run reaper-mcp-cli transport play
uv run reaper-mcp-cli transport stop

# Use the complete profile when an experimental tool is required.
uv run reaper-mcp-cli --profile full tools --pretty
```

Use `--arg key=value` for simple scalar arguments and `--json` for nested
requests. Output is compact JSON by default and supports `--pretty`.

## REST usage

The REST adapter is optional and loopback-only because it has no authentication
layer. It reuses the MCP registry and returns the same structured tool results.

```bash
export REAPER_MCP_TRANSPORT=http
export REAPER_MCP_HTTP_HOST=127.0.0.1
export REAPER_MCP_HTTP_PORT=8765
uv run reaper-mcp
```

Available endpoints:

```text
GET  /api/health
GET  /api/tools
POST /api/tools/{tool_name}
```

Example:

```bash
curl http://127.0.0.1:8765/api/tools/get_active_profile
curl -X POST http://127.0.0.1:8765/api/tools/get_project_snapshot \
  -H 'content-type: application/json' \
  -d '{}'
```

## Safety model

The bridge and services enforce the following rules before REAPER executes a
mutation:

- Stable REAPER GUIDs identify tracks, items, takes, FX, envelopes, and sends.
- Mutations are validated and wrapped in named REAPER undo actions.
- Stale target fingerprints return structured conflicts instead of guessing.
- Audio, project, template, analysis, and render paths use explicit allowlists.
- Render success requires a stable, non-empty output and verified restoration.
- Hidden profile tools cannot be called through stale client discovery.
- Bridge failures report structured errors instead of claiming success.

## Configuration

Runtime settings use the `REAPER_MCP_` prefix. The important paths are:

| Variable | Purpose |
| --- | --- |
| `REAPER_MCP_BRIDGE_DIR` | Shared Python and Lua bridge directory |
| `REAPER_MCP_TOOL_PROFILE` | Active tool profile |
| `REAPER_MCP_TRANSPORT` | `stdio` or `http` |
| `REAPER_MCP_ALLOWED_MEDIA_SOURCE_ROOTS` | Audio files that may be inserted |
| `REAPER_MCP_ALLOWED_PROJECT_ROOTS` | Projects that may be saved as |
| `REAPER_MCP_ALLOWED_RENDER_ROOTS` | Directories allowed for WAV output |
| `REAPER_MCP_ALLOWED_TEMPLATE_ROOTS` | Directories allowed for templates |
| `REAPER_MCP_ALLOWED_AUDIO_ROOTS` | WAV files allowed for analysis |
| `REAPER_MCP_REAPER_EXECUTABLE` | REAPER binary used by isolated rendering |

All allowlists default to empty. See the [full configuration](README.md#configuration)
and [engineering standards](docs/reaper-mcp-engineering-standards.md) for the
complete configuration contract.

## Architecture

```text
MCP clients     CLI        Local REST apps
     |           |              |
     +-----------+--------------+
                     |
              Python adapters
                     |
          Profiles, services, safety
                     |
                File bridge
                     |
             Lua bridge in REAPER
                     |
                 ReaScript API
```

Read the [product and architecture specification](docs/reaper-mcp-product-architecture-spec.md)
for the full component model and request flow. The [implementation roadmap](docs/reaper-mcp-implementation-roadmap.md)
tracks the release work. The [product reality audit](docs/reaper-mcp-product-reality-audit.md)
separates implemented, unit-tested, and live-accepted behavior.

## Verified status

The current Linux verification covers the bridge, project and track operations,
transport, media, MIDI, FX, routing, automation, takes, arrangement, tempo,
templates, analysis, workflows, interfaces, and isolated project rendering.

Run the local checks:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

The native REAPER render action lifecycle remains experimental because action
`42230` can block the Lua event loop. The isolated external render path is the
verified render path. See the audit before relying on experimental render jobs.

## Demo projects

The [demo directory](demo/) contains lightweight REAPER project fixtures and
source notices. Downloaded audio and generated peak files stay local because
they are large or subject to separate distribution terms.

## Project layout

```text
src/reaper_mcp/       Python server, services, models, and adapters
lua/                  REAPER Lua bridge
tests/unit/           Fast tests without REAPER
tests/integration/    Opt-in live REAPER acceptance tests
docs/                 Product, architecture, roadmap, and engineering truth
demo/                 Local producer workflow fixtures
```

## License

REAPER MCP is available under the MIT License. See [LICENSE](LICENSE) and
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for attribution details.
