# REAPER MCP

REAPER MCP is an MCP server that talks to a Lua bridge running inside REAPER.
The current implementation includes the project foundation, bridge diagnostics,
project and track tools, transport controls, media item tools, MIDI note list,
insert, update, and delete tools, GUID-based item editing, FX chain and
parameter tools, marker and region tools, tempo and time signature tools,
routing and freeze operations, guarded MIDI transformations, and a complete
song-starter workflow. It also includes MIDI controller events, tempo-map
markers, automation envelopes, take and comping controls, project controls,
FX presets and chain copying, track templates, batch track updates, audio
analysis, project navigation and saving, and runtime tool profiles. MCP tools
send JSON commands through the file bridge and read structured responses from
REAPER.

> **Note:** This project is under active development. The server currently
> registers 146 tools. The default `production` profile exposes 142 stable
> tools and hides the four experimental render tools. The `full` profile
> exposes all 146. The
> [product reality audit](docs/reaper-mcp-product-reality-audit.md) records
> which tools have passed live REAPER acceptance.

> **Note:** Isolated full-project WAV rendering is live-verified when
> `REAPER_MCP_REAPER_EXECUTABLE` points to a REAPER binary. The native render
> lifecycle and fallback action remain experimental and are hidden from the
> default profile. See the
> [product reality audit](docs/reaper-mcp-product-reality-audit.md).

## What is included

The repository contains the package layout and end-to-end protocol between the
MCP server and REAPER.

- Python package under `src/reaper_mcp/`.
- Lua bridge script at `lua/reaper_mcp_bridge.lua`.
- Typed bridge models for `CommandEnvelope`, `BridgeResponse`, and
  `ErrorResponse`.
- File bridge client with request IDs, response polling, cleanup, and timeouts.
- MCP server entrypoint registering the 146 tools tracked in the
  [product reality audit](docs/reaper-mcp-product-reality-audit.md).
- Unit tests that run without REAPER.
- Opt-in integration tests for isolated live REAPER acceptance.

## Requirements

Install these tools before running the project locally.

- Python 3.11 or newer.
- `uv`.
- REAPER for manual bridge testing.

## Setup

Run these commands from the repository root.

1. Install the package and development dependencies:

   ```bash
   uv sync
   ```

2. Install the Lua bridge into REAPER's resource directory:

   ```bash
   uv run reaper-mcp-install
   ```

   The installer detects the standard Linux, macOS, or Windows resource path.
   If REAPER uses a portable or custom resource directory, pass it explicitly:

   ```bash
   uv run reaper-mcp-install --resource-path /path/to/REAPER
   ```

   The command preserves a changed existing bridge as
   `reaper_mcp_bridge.lua.backup`. Re-running it with the current bridge makes
   no changes.

3. Run the unit tests:

   ```bash
   uv run pytest
   ```

4. Run linting and formatting checks:

   ```bash
   uv run ruff check .
   uv run ruff format --check .
   ```

## Bridge root directory

The Python server and Lua bridge communicate through a shared directory. By
default, both sides use `reaper-mcp-bridge/` inside the system temporary
directory.

Set `REAPER_MCP_BRIDGE_DIR` when you need an explicit location:

```bash
export REAPER_MCP_BRIDGE_DIR=/tmp/reaper-mcp-bridge
```

The bridge creates three subdirectories:

- `requests/` for command envelopes written by Python.
- `responses/` for bridge responses written by Lua.
- `jobs/` for experimental asynchronous render job state.

Bridge settings use the `REAPER_MCP_` environment variable prefix:

- `REAPER_MCP_TRANSPORT` maps to `transport` and defaults to `stdio`. Set it to
  `http` to enable the optional local REST interface.
- `REAPER_MCP_HTTP_HOST` maps to `http_host` and defaults to `127.0.0.1`.
- `REAPER_MCP_HTTP_PORT` maps to `http_port` and defaults to `8765`.
- `REAPER_MCP_BRIDGE_DIR` maps to `bridge_dir`.
- `REAPER_MCP_BRIDGE_TIMEOUT_SECONDS` maps to `bridge_timeout_seconds`
  and defaults to `5.0`.
- `REAPER_MCP_BRIDGE_POLL_INTERVAL_SECONDS` maps to
  `bridge_poll_interval_seconds` and defaults to `0.05`.
- `REAPER_MCP_BRIDGE_STALE_AFTER_SECONDS` maps to
  `bridge_stale_after_seconds` and defaults to `300.0`.
- `REAPER_MCP_LOG_LEVEL` maps to `log_level` and defaults to `INFO`.
- `REAPER_MCP_TOOL_PROFILE` maps to `tool_profile` and defaults to
  `production`. Valid profiles are `minimal`, `production`, `midi`, `mixing`,
  and `full`.
- `REAPER_MCP_ALLOWED_MEDIA_SOURCE_ROOTS` maps to
  `allowed_media_source_roots` and defaults to an empty list.
- `REAPER_MCP_ALLOWED_PROJECT_ROOTS` maps to `allowed_project_roots` and
  defaults to an empty list.
- `REAPER_MCP_ALLOWED_RENDER_ROOTS` maps to `allowed_render_roots` and
  defaults to an empty list.
- `REAPER_MCP_ALLOWED_TEMPLATE_ROOTS` maps to `allowed_template_roots` and
  defaults to an empty list.
- `REAPER_MCP_ALLOWED_AUDIO_ROOTS` maps to `allowed_audio_roots` and defaults
  to an empty list.
- `REAPER_MCP_RENDER_TIMEOUT_SECONDS` maps to `render_timeout_seconds` and
  defaults to `60.0`.
- `REAPER_MCP_RENDER_POLL_INTERVAL_SECONDS` maps to
  `render_poll_interval_seconds` and defaults to `0.1`.
- `REAPER_MCP_RENDER_BACKGROUND_CONFIRMED` maps to
  `render_background_confirmed` and defaults to `false`.
- `REAPER_MCP_RENDER_EXTERNAL_ENABLED` maps to `render_external_enabled` and
  defaults to `true`.
- `REAPER_MCP_REAPER_EXECUTABLE` maps to `reaper_executable`. Set it to the
  absolute path of the REAPER executable when it is not available on `PATH`.

`insert_audio_item` only accepts source files inside
`allowed_media_source_roots`. With the default empty list, audio insertion is
disabled and returns `error.code: "media_source_not_allowed"` before the bridge
receives a command. Set the environment variable as a JSON array:

```bash
export REAPER_MCP_ALLOWED_MEDIA_SOURCE_ROOTS='["/home/ayodele/Music/Samples"]'
```

`save_project_as` uses the same default-deny policy. Configure one or more
project roots before saving a new `.rpp` path:

```bash
export REAPER_MCP_ALLOWED_PROJECT_ROOTS='["/home/ayodele/Music/Projects"]'
```

Render output uses the same default-deny policy. `render_project` only writes
WAV files inside `allowed_render_roots`. Set allowed render roots as a JSON
array before calling render tools:

```bash
export REAPER_MCP_ALLOWED_RENDER_ROOTS='["/home/ayodele/Music/Renders"]'
```

Track-template files and audio-analysis inputs are also default-deny. Configure
their roots before using `save_track_template`, `apply_track_template`, or
`analyze_audio_file`:

```bash
export REAPER_MCP_ALLOWED_TEMPLATE_ROOTS='["/home/ayodele/Music/Templates"]'
export REAPER_MCP_ALLOWED_AUDIO_ROOTS='["/home/ayodele/Music/Renders"]'
```

The external renderer does not require REAPER's background-render preference. If
you disable the external renderer and use the native fallback, open
**Preferences > Audio > Rendering**, enable **Render in background (does not
apply to queued renders)**, and explicitly confirm that setting for this MCP
process:

```bash
export REAPER_MCP_RENDER_BACKGROUND_CONFIRMED=true
```

The confirmation flag applies only to the native fallback. It protects the
file bridge from a synchronous REAPER render action that can block the Lua event
loop. The flag is a user confirmation, not an automatic capability probe.

## Run the server

Start the MCP server over stdio with this command. Stdio is the default and is
the recommended transport for MCP clients.

```bash
uv run reaper-mcp
```

### Optional local REST interface

The server also provides an optional loopback-only REST interface. It reuses
the same MCP tool registry, profiles, services, validation, and structured
results. It does not add a separate CLI or duplicate REAPER logic.

Start HTTP mode by setting the transport environment variable:

```bash
export REAPER_MCP_TRANSPORT=http
export REAPER_MCP_HTTP_HOST=127.0.0.1
export REAPER_MCP_HTTP_PORT=8765
uv run reaper-mcp
```

The API is available at `http://127.0.0.1:8765`:

- `GET /api/health` checks the Python server and Lua bridge.
- `GET /api/tools` lists tools visible in the active profile.
- `POST /api/tools/{tool_name}` calls a visible tool with a JSON object body.

For example:

```bash
curl http://127.0.0.1:8765/api/tools/get_active_profile
curl -X POST http://127.0.0.1:8765/api/tools/get_project_snapshot \
  -H 'content-type: application/json' \
  -d '{}'
```

The REST server rejects non-loopback bindings because it has no authentication
layer. Keep the API local unless an authenticated gateway is added later.

### Command-line interface

The CLI calls the same profiled MCP server and provides a complete command for
every visible tool. It does not contain separate REAPER logic.

List the tools in the active profile:

```bash
uv run reaper-mcp-cli tools --pretty
```

Call any tool with a JSON object:

```bash
uv run reaper-mcp-cli call set_tempo --json '{"bpm": 96}'
```

Simple producer-facing aliases are also available:

```bash
uv run reaper-mcp-cli project snapshot
uv run reaper-mcp-cli tracks list
uv run reaper-mcp-cli transport play
uv run reaper-mcp-cli transport stop
```

Use `--arg key=value` for simple scalar arguments, `--json` for nested
arguments, and `--profile full` when a command needs an advanced capability.
The CLI returns compact JSON by default and uses non-zero exit codes for
invalid requests, hidden tools, bridge failures, and failed tool results.

Example MCP client configuration:

```json
{
  "mcpServers": {
    "reaper-mcp": {
      "command": "uv",
      "args": ["--directory", "/home/ayodele/Desktop/reaper-mcp", "run", "reaper-mcp"],
      "env": {
        "REAPER_MCP_BRIDGE_DIR": "/tmp/reaper-mcp-bridge",
        "REAPER_MCP_ALLOWED_MEDIA_SOURCE_ROOTS": "[\"/home/ayodele/Music/Samples\"]"
      }
    }
  }
}
```

## Manual REAPER smoke test

Use this flow after installing dependencies.

1. Open REAPER.
2. Open **Actions**, select **New action > Load**, and choose the installed
   `Scripts/reaper_mcp_bridge.lua` file. Run it as a ReaScript.
3. Start the MCP server with `uv run reaper-mcp`.
4. Connect an MCP client or MCP Inspector.
5. Call `health_check`, `get_reaper_version`, `get_project_info`,
   `get_bridge_status`, `get_project_snapshot`, `list_tracks`,
   `create_track`, `rename_track`, `set_track_color`, `set_track_mute`,
   `set_track_solo`, `set_track_arm`, `set_track_volume`, `set_track_pan`,
   `delete_track`, `get_master_track`, `set_master_volume`, `set_master_pan`,
   `set_master_mute`, `play`, `stop`,
   `stop_recording`, `pause`, `record`, `list_available_fx`,
   `list_track_fx`, `list_media_items`, `create_midi_item`,
   `insert_audio_item`, `move_media_item`, `resize_media_item`,
   `duplicate_media_item`, `split_media_item`, `set_media_item_mute`,
   `set_media_item_gain`, `set_media_item_fade_in`,
   `set_media_item_fade_out`, `delete_media_item`, `get_midi_notes`,
   `add_midi_note`, `add_midi_notes`, `update_midi_note`, and
   `delete_midi_notes`. Exercise `transpose_midi_notes`, `nudge_midi_notes`,
   `quantize_midi_notes`, `humanize_midi_notes`,
   `snap_midi_notes_to_scale`, `shape_midi_note_velocities`, and
   `remove_midi_note_overlaps` with the guarded identities returned by
   `get_midi_notes`. Use `analyze_audio_file` for approved local WAV files and
   `calculate_take_loudness` for non-modal level metrics from a take's approved
   WAV source.
   Then call `add_fx`, `set_fx_enabled`, `get_fx_parameters`,
   `set_fx_parameter`, `get_fx_preset`, `set_fx_preset`,
   `get_fx_preset_index`, `set_fx_preset_index`, `navigate_fx_presets`, and
   `remove_fx` using the FX identifiers and guarded identities returned by the
   read-only FX tools. Call `list_markers`,
   `create_marker`, `delete_marker`, `list_regions`, `create_region`,
   `delete_region`, `get_tempo`, `set_tempo`, `get_time_signature`, and
   `set_time_signature` to validate arrangement and timeline behavior. Treat
   `list_track_sends`, `create_track_send`, `set_track_send`, and
   `remove_track_send` as the guarded routing workflow. Treat
   `get_track_freeze_state`, `freeze_track`, and `unfreeze_track` as the
   selection-restoring freeze workflow. Call `create_song_starter` in a 4/4
   project to create eight bars of Drums, Bass, Chords, and Lead MIDI in one
   undo step. Exercise `ensure_track_envelope`, the guarded envelope point
   tools, take management, cursor and loop controls, and project saving. Use
   `list_capabilities` and `set_active_profile` to verify runtime discovery.
   Treat
   the render tools as preview-only until the product reality audit marks their
   live acceptance checks as passed.

When the bridge is running, `health_check` returns `ok: true` and includes the
REAPER version, bridge version, and bridge directory. When the bridge is not
running, it returns a structured `bridge_not_running` error.

To validate invalid envelope handling manually, write a request file without a
`command` field into the bridge `requests/` directory. The Lua bridge must write
a response with `ok: false` and `error.code: "invalid_command_envelope"`.

The opt-in integration suite automates bridge safety, tracks, transport, media,
MIDI transformations, routing, freeze, FX, arrangement, tempo, automation,
takes, project navigation, the song-starter workflow, and undo-redo against an
isolated empty REAPER project.
Start the isolated instance in one terminal:

```bash
export REAPER_MCP_BRIDGE_DIR=/tmp/reaper-mcp-acceptance
reaper -newinst -new -nosplash \
  "$PWD/lua/reaper_mcp_bridge.lua" \
  "$PWD/tests/integration/reaper_acceptance_probe.lua"
```

Run the acceptance test from another terminal:

```bash
export REAPER_MCP_LIVE_TEST=1
export REAPER_MCP_BRIDGE_DIR=/tmp/reaper-mcp-acceptance
export REAPER_MCP_REAPER_EXECUTABLE="$(command -v reaper)"
uv run pytest tests/integration/test_reaper_bridge_manual.py -vv
```

This suite changes and deletes tracks, media, MIDI notes, sends, freeze media,
FX, markers, regions, tempo, time signatures, and a four-part song starter. Do
not point it at a project containing user work.

The MCP process writes one JSON command record to stderr after each bridge call.
Records include the request ID, command, duration in milliseconds, result,
error code when present, and bounded target identifiers.

MIDI note mutation uses guarded note identity. `get_midi_notes`,
`add_midi_note`, and `add_midi_notes` return each note with its current
`index` and `fingerprint`. `update_midi_note` and `delete_midi_notes` require
that pair as
`note_index`/`expected_fingerprint` or `notes[].index`/`expected_fingerprint`.
If the take changes before mutation, the bridge returns
`error.code: "midi_note_conflict"` so callers can refresh and retry.

MIDI transformations target explicit note identities and execute as one named
undo action. Quantization preserves note duration, humanization is deterministic
for the same seed and inputs, scale snapping supports named scales and explicit
pitch direction, and overlap removal trims notes without deleting them. Notes
with the same start, channel, pitch, velocity, selected state, and muted state
are rejected during insertion because REAPER cannot expose an unambiguous
identity for them.

FX identity uses the current `track_guid`, FX slot `index`, and REAPER FX
`guid` when available. If REAPER does not provide an FX GUID, FX mutations
guard against the expected FX `name` at that slot.

FX parameters are addressed by guarded FX identity plus parameter index.
`set_fx_parameter` accepts normalized values from `0.0` to `1.0` and returns
the updated parameter with its index, name, normalized value, and formatted
value.

FX preset index tools use REAPER's native preset bank. Index `-2` selects the
factory preset, index `-1` selects the default user preset, and non-negative
indexes select entries reported by REAPER. Preset mutations verify the guarded
FX identity and execute in one named undo block.

Markers and regions use REAPER marker and region IDs. Delete tools accept
optional expected names and timeline positions to guard against stale IDs before
the bridge mutates the project.

Media-item editing uses stable item GUIDs. Duplication isolates the target item,
restores the prior item selection, and returns the new item GUID. Split returns
the original left item and the newly created right item. Item gain is linear
from `0.0` to `4.0`, and manual fade lengths use seconds and cannot exceed the
item length.

Time signature writes accept denominators `1`, `2`, `4`, `8`, `16`, `32`, and
`64`. Other denominator values return `error.code: "invalid_tempo_request"`.

Automation points use envelope GUIDs plus index-and-fingerprint guards. Public
point values use REAPER's scaled value domain, so a volume envelope reports
`1.0` at 0 dB instead of REAPER's raw fader-scaled value. Built-in volume, pan,
mute, pre-FX volume and pan, and trim-volume envelopes can be created safely.

Take tools use stable take GUIDs. `crop_to_active_take` requires the expected
active take GUID and take count before it removes inactive takes. Project
save-as paths must use `.rpp` and remain inside an allowed project root.

Profiles filter both tool discovery and calls. The five profile management
tools remain visible in every profile. `enable_capability` and
`disable_capability` apply process-local overrides until the active profile
changes.

`render_project` validates allowed roots, snapshots the current project, and
renders the snapshot in a short-lived REAPER process. It promotes only a
non-empty WAV after the process exits successfully, preserves the project dirty
state, and reports overwrite behavior. The native render job lifecycle remains
experimental because action `42230` can block the Lua bridge.

## Release status

The original 99 REAPER-backed core tools and the producer-expansion bridge
commands have passed the Linux live acceptance matrix. Take loudness uses the
non-modal approved-WAV analysis path because REAPER's native dry-run calculation
opens a modal render-results window.
`set_fx_preset` and the preset index tools are implemented and unit-covered but
remain unverified on this REAPER profile because the installed test FX exposed
no preset to set.
Isolated `render_project` passed Linux live checks for completion, dirty-state
preservation, bridge responsiveness, overwrite rejection, and overwrite
success. Native render lifecycle tools remain experimental.

## License and attribution

REAPER MCP is available under the MIT License. See `LICENSE` and
`THIRD_PARTY_NOTICES.md` for the reference-project attributions.
