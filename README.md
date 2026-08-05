<p align="center">
  <img src="assets/reaper-mcp-hero.png" alt="REAPER MCP producer workflow" width="1100">
</p>

<h1 align="center">REAPER MCP</h1>

<p align="center">
  A safe, producer-focused MCP server for controlling REAPER with AI,
  scripts, and the command line.
</p>

<p align="center">
  <a href="https://github.com/danishaft/reaper-mcp/actions/workflows/ci.yml">
    <img src="https://github.com/danishaft/reaper-mcp/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI status">
  </a>
  <a href="https://github.com/danishaft/reaper-mcp/blob/main/LICENSE">
    <img src="https://img.shields.io/badge/license-MIT-yellow.svg?style=flat-square" alt="MIT License">
  </a>
  <img src="https://img.shields.io/badge/python-3.11%2B-blue.svg?style=flat-square" alt="Python 3.11 or newer">
  <img src="https://img.shields.io/badge/Linux-verified-25a162.svg?style=flat-square" alt="Linux verified">
  <img src="https://img.shields.io/badge/macOS-CI%20tested-6f42c1.svg?style=flat-square" alt="macOS CI tested, REAPER unverified">
  <img src="https://img.shields.io/badge/Windows-CI%20tested-6f42c1.svg?style=flat-square" alt="Windows CI tested, REAPER unverified">
  <img src="https://img.shields.io/badge/MCP-stdio%20%7C%20REST-6f42c1.svg?style=flat-square" alt="MCP stdio and REST">
  <img src="https://img.shields.io/badge/CLI-supported-6f42c1.svg?style=flat-square" alt="CLI supported">
  <img src="https://img.shields.io/badge/tools-172-6f42c1.svg?style=flat-square" alt="172 tools">
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

The tool surface covers the production workflow from session creation through
delivery:

| Producer workflow | Representative tools | What it enables |
| --- | --- | --- |
| **Build** | `create_song_starter`, `create_track`, `create_midi_pattern` | Start a song with tracks, MIDI parts, and a region |
| **Arrange** | `move_media_item`, `split_media_item`, `list_fixed_lanes`, `select_fixed_lane` | Shape sections and safely audition one complete REAPER fixed lane |
| **Edit MIDI** | `add_midi_notes`, `quantize_midi_notes`, `humanize_midi_notes`, `snap_midi_notes_to_scale` | Write, correct, and vary musical performances |
| **Mix** | `set_track_volume`, `add_fx`, `setup_sidechain`, `configure_reference_track` | Balance tracks, build guarded processing chains, and audition references outside master FX |
| **Tune vocals** | `list_vocal_tuning_providers`, `preview_vocal_tuning_plugin_plan`, `apply_vocal_tuning_plugin_plan` | Apply approved scale-aware pitch correction through a verified, undoable provider |
| **Manage projects** | `save_project`, `apply_track_template`, `freeze_track`, `undo` | Save, template, freeze, and recover project changes |
| **Analyze** | `measure_audio_file`, `analyze_audio_program` | Measure loudness, peaks, DC offset, frequency-band balance, and silence |
| **Master** | `create_mastering_session`, `preview_mastering_plan`, `prepare_mastering_audition` | Guard master-FX plans, render measured candidates, and prepare level-matched A/B projects |
| **Deliver** | `deliver_mastering_candidate`, `create_mastering_codec_preview`, `create_mastering_version_set`, `prepare_mastering_album` | Verify PCM WAVs, measure decoded AAC/MP3/Opus previews, group approved versions, and prepare albums |
| **Render** | `render_project`, `render_project_start`, `render_project_result` | Produce approved WAV output with completion checks |

## Interfaces

All interfaces use the same services, profiles, safety rules, error model, and
Lua bridge. They are different ways to reach the same product.

| Interface | Best for | Start |
| --- | --- | --- |
| **MCP** | Claude, Codex, Cursor, and other AI clients | `reaper-mcp` |
| **CLI** | Producers, shell scripts, automation, and CI | `reaper-mcp-cli` |
| **REST** | Local apps and integrations | `REAPER_MCP_TRANSPORT=http reaper-mcp` |

## Quick start

You can connect REAPER MCP in a few minutes. You need REAPER and
[`uv`](https://docs.astral.sh/uv/getting-started/installation/). Linux with
REAPER 7.66 is the live-verified environment.

### 1. Install the server and bridge

Install the Python package as an isolated command-line tool, then copy its
packaged Lua bridge into your REAPER resource directory:

```bash
uv tool install danishaft-reaper-mcp
reaper-mcp-install
```

The installer prints the exact bridge path and the remaining REAPER steps. It
backs up an older bridge when the installed content differs.

### 2. Activate the bridge in REAPER

Open REAPER and complete these steps once:

1. Choose **Actions > Show action list**.
2. Choose **New action > Load ReaScript**.
3. Select the `reaper_mcp_bridge.lua` path printed by the installer.
4. Select `reaper_mcp_bridge.lua` in the action list, then choose **Run**.

Run the bridge again after restarting REAPER. You can add it to a REAPER
startup action after confirming the first connection.

### 3. Start and verify the server

Keep REAPER open with the bridge running. Verify the connection before changing
a project:

```bash
reaper-mcp-cli health
```

Then start the MCP server:

```bash
reaper-mcp
```

A successful result reports both the Python server and the REAPER bridge as
available. Continue to [MCP setup](#mcp-setup) to connect your AI client.

## Platform support

The Python package and installer contain platform path handling. GitHub CI runs
the unit, contract, lint, format, and package checks on all three platforms,
but live DAW acceptance is narrower than source compatibility. Do not treat an
unverified platform as production-ready until REAPER has been exercised there.

| Platform | REAPER integration | Status |
| --- | --- | --- |
| **Linux** | CI plus REAPER 7.66, native Lua bridge, isolated render path | Live verified |
| **macOS** | CI and installer path handling; live REAPER run pending | CI tested, DAW unverified |
| **Windows** | CI and installer path handling; live REAPER run pending | CI tested, DAW unverified |

## Available tool surface

The server registers 172 tools and exposes 26 focused tools in the default
`minimal` profile. Use discovery instead of memorizing the complete list.

```bash
reaper-mcp-cli tools --pretty
reaper-mcp-cli capabilities --pretty
```

The `production`, `midi`, and `mixing` profiles provide larger task-specific
surfaces. The `full` profile exposes all tools, including experimental vocal
tuning, mastering, and render lifecycle operations.

> **Note:** Experimental tools are preview features under active development.
> Review the limitations before using them on production work.

## MCP setup

Add the server to an MCP client that supports stdio transport:

```json
{
  "mcpServers": {
    "reaper-mcp": {
      "command": "uvx",
      "args": [
        "--from",
        "danishaft-reaper-mcp",
        "reaper-mcp"
      ],
      "env": {
        "REAPER_MCP_BRIDGE_DIR": "/tmp/reaper-mcp-bridge"
      }
    }
  }
}
```

To work on the implementation instead of the released package, clone the
repository and point the client at the checkout:

```bash
git clone https://github.com/danishaft/reaper-mcp.git
cd reaper-mcp
uv sync --locked
uv run reaper-mcp-install
uv run reaper-mcp
```

The server exposes the `minimal` profile by default. Use the profile tools or
set `REAPER_MCP_TOOL_PROFILE` to choose `production`, `midi`, `mixing`, or
`full`.

## CLI usage

The CLI covers every visible MCP tool through `call`. The aliases are shortcuts
for common producer operations; they do not create a second implementation.

```bash
# Discover the active tool surface.
reaper-mcp-cli tools --pretty

# Call any tool with a JSON object.
reaper-mcp-cli call set_tempo --json '{"bpm": 96}'

# Use readable producer-facing aliases.
reaper-mcp-cli project snapshot
reaper-mcp-cli tracks list
reaper-mcp-cli transport play
reaper-mcp-cli transport stop

# Use the complete profile when an experimental tool is required.
reaper-mcp-cli --profile full tools --pretty
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
reaper-mcp
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
- Reference tracks can bypass master FX through a verified direct hardware
  send created in one undoable routing operation.
- Mutations are validated and wrapped in named REAPER undo actions.
- Stale target fingerprints return structured conflicts instead of guessing.
- Audio, project, template, analysis, and render paths use explicit allowlists.
- Template deletion requires the SHA-256 returned by a fresh template listing.
- Render success requires a stable, non-empty output and verified restoration.
- Hidden profile tools cannot be called through stale client discovery.
- A timed-out mutation reports an uncertain outcome and must be refreshed
  before retrying.
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
| `REAPER_MCP_ALLOWED_AUDIO_ROOTS` | Audio files allowed for analysis |
| `REAPER_MCP_REAPER_EXECUTABLE` | REAPER binary used by isolated rendering |
| `REAPER_MCP_FFMPEG_EXECUTABLE` | FFmpeg binary used for EBU R128 measurement |
| `REAPER_MCP_AUDIO_MEASUREMENT_TIMEOUT_SECONDS` | Per-file meter timeout |
| `REAPER_MCP_AUDIO_MEASUREMENT_MAX_OUTPUT_BYTES` | Meter diagnostic output cap |

All allowlists default to empty. See the
[engineering standards](docs/reaper-mcp-engineering-standards.md) for the
complete configuration contract.

## Verification and limitations

Automated tests cover the Python service, bridge contracts, and package on
Linux, macOS, and Windows. Live REAPER acceptance currently covers the core
producer workflow and isolated rendering on Linux with REAPER 7.66. See
[CONTRIBUTING.md](CONTRIBUTING.md) for the local and live test commands.

Known limitations are deliberate and documented:

- macOS and Windows have no live REAPER acceptance evidence yet.
- The native render lifecycle remains experimental because action `42230` can
  block the Lua event loop. The isolated external render path is verified.
- `set_fx_preset` remains unverified when the installed test FX exposes no
  preset.
- Vocal tuning does not detect the song key. x42 Auto Tune has a verified
  parameter contract on Linux but no formant correction; ReaTune requires an
  engineer-authored named preset. The take-pitch bridge command still needs
  live REAPER acceptance.
- Fixed-lane tools inspect and select complete lanes. Swipe-comp area creation
  and automatic phrase comping remain out of scope because REAPER does not
  expose comp areas as stable, directly addressable API objects.
- Plugin UI automation, audio-rate control, and cloud collaboration are out
  of scope.

The opt-in suite under [`tests/integration/`](tests/integration/) is the
executable source for live REAPER acceptance.

## Releases and contribution

Tagged releases publish `danishaft-reaper-mcp` to PyPI through Trusted
Publishing, then attach the same source distribution and wheel to the
[GitHub release](https://github.com/danishaft/reaper-mcp/actions/workflows/release.yml).
The package still requires a local REAPER installation and a compatible Lua
bridge; it is not a bundled REAPER application.

Read [CONTRIBUTING.md](CONTRIBUTING.md) for development checks and live
acceptance requirements. User-visible changes are tracked in
[CHANGELOG.md](CHANGELOG.md).

## License

REAPER MCP is available under the MIT License. See [LICENSE](LICENSE) and
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for attribution details.
