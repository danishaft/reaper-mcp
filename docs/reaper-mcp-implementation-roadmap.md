# REAPER MCP implementation roadmap

This roadmap turns the product and architecture spec into a practical build
sequence. It favors a small reliable core before broad ReaScript coverage.

> **Note:** This roadmap uses a reuse-first strategy. The project adapts proven
> MIT-licensed behavior from `reaper-reapy-mcp` and `total-reaper-mcp`, then
> custom-builds only the safety, identity, architecture, and reliability that
> make this implementation better.

## Diagnosis

The project needs to avoid two failure modes.

First, a small MCP server can ship quickly but become limited if it relies too
heavily on Python-side REAPER control. Second, a broad MCP server can expose too
many tools and become hard for LLM clients to use safely.

The roadmap uses a hybrid strategy:

- Build the Python MCP server as the stable product surface.
- Build a Lua bridge as the native REAPER control layer.
- Ship curated workflow and core tools first.
- Add raw ReaScript coverage later through capability gates.

## Guiding policies

The project uses these policies to keep implementation focused.

- Prefer the standard Python MCP SDK and REAPER Lua scripting.
- Keep the default tool surface small and useful.
- Add broad API coverage only after the bridge and safety layer are reliable.
- Test bridge behavior separately from MCP transport behavior.
- Treat undo behavior as a release blocker.
- Keep every phase demonstrable in a real REAPER project.

## Reuse map

The project does not rebuild solved behavior without a specific reason. Every
adapted implementation must still fit this repository's typed service
boundaries, GUID identity model, structured errors, path policy, and undo
contract.

| Component | Primary source | Decision |
| --- | --- | --- |
| Python MCP packaging and compact tool registration | `reaper-reapy-mcp` | Adapt the simple install and launch experience. Keep this project's typed services. |
| Native REAPER bridge and broad action recipes | `total-reaper-mcp` | Adapt useful ReaScript operations. Keep this project's command envelope and file transport. |
| Track, media, MIDI, FX, arrangement, and tempo core | This project | Keep the live-accepted GUID, guard, error, and undo implementations. |
| Master controls and media-item editing | `reaper-reapy-mcp` | Adapt behavior into GUID-based services and Lua commands. |
| Routing, sends, bounce, freeze, and workflow recipes | `total-reaper-mcp` | Adapt only the production workflows selected for the release. |
| Rendering | Both references plus this project | Reuse render-setting and action knowledge, but require truthful output verification. Neither reference currently provides that contract. |
| Installation | `total-reaper-mcp` | Adapt bridge discovery and copying into a non-interactive cross-platform installer. |

## Phase 0: Project foundation

This phase creates the repo structure and baseline engineering workflow.

Goals:

- Establish a clean Python package.
- Add the Lua bridge location.
- Add documentation and development commands.
- Add a mockable bridge interface.

Tasks:

- Create `pyproject.toml`.
- Create `src/reaper_mcp/` for the Python server.
- Create `lua/reaper_mcp_bridge.lua`.
- Create `tests/` with unit test scaffolding.
- Add lint, format, and test commands.
- Add a short `README.md` with setup status.
- Add example MCP client configuration.

Exit criteria:

- The package installs locally.
- Unit tests can run without REAPER.
- The MCP server starts and exposes a health tool.

## Phase 1: Lua bridge and server skeleton

This phase proves end-to-end communication between MCP, Python, Lua, and REAPER.

Goals:

- Run the Lua bridge as a deferred ReaScript.
- Send a JSON command from Python to Lua.
- Return a structured JSON response.
- Report bridge health.

Tasks:

- Implement file-based bridge directories.
- Implement request and response IDs.
- Implement bridge timeouts.
- Implement stale file cleanup.
- Implement `health_check`.
- Implement `get_reaper_version`.
- Implement `get_project_info`.
- Add mocked bridge tests.
- Add manual REAPER bridge smoke test instructions.

Exit criteria:

- `health_check` passes when the Lua bridge is running.
- `health_check` returns `bridge_not_running` when it is stopped.
- A request can execute a simple ReaScript read call.
- Timeout behavior is deterministic.

## Phase 2: Safety and command envelope

This phase creates the guardrails required before adding mutating tools.

Goals:

- Standardize command envelopes.
- Wrap mutating calls in named REAPER undo blocks.
- Normalize errors.
- Add dry-run support for selected commands.

Tasks:

- Define command request and response schemas.
- Add `mutates_project`, `undo_label`, and `dry_run` options.
- Implement Lua-side undo wrappers.
- Implement Python-side input validation.
- Add standard error codes.
- Add structured command logging.
- Add bridge duration measurement.
- Add tests for validation and error mapping.

Exit criteria:

- Mutating test commands create one REAPER undo action.
- Invalid input fails before the bridge call where possible.
- Bridge and validation errors return stable error codes.
- Logs contain request ID, command name, duration, and result.

## Phase 3: Core project and track tools

This phase adds the first useful DAW control surface.

Goals:

- Inspect project state.
- Manage tracks safely.
- Control transport.

Tasks:

- Implement `get_project_snapshot`.
- Implement `list_tracks`.
- Implement `create_track`.
- Implement `rename_track`.
- Implement `set_track_color`.
- Implement `set_track_mute`.
- Implement `set_track_solo`.
- Implement `set_track_arm`.
- Implement `delete_track`.
- Implement `play`, `stop`, `stop_recording`, `pause`, and `record`.
- Add stable track GUID handling.
- Add tests for track identity and undo behavior.

Exit criteria:

- A client can inspect an empty project.
- A client can create and rename tracks.
- A user can undo each track mutation in one REAPER undo action.
- Tool responses include stable track GUIDs.

## Phase 4: MIDI and media item tools

This phase enables the first serious music creation workflows.

Goals:

- Create MIDI items.
- Add, update, list, and delete MIDI notes.
- Insert audio items from allowed paths.
- Use musical position formats.

Tasks:

- Implement measure, beat, and PPQ conversion helpers.
- Implement `create_midi_item`.
- Implement `list_media_items`.
- Implement `get_midi_notes`.
- Implement `add_midi_note`.
- Implement `add_midi_notes`.
- Implement `update_midi_note`.
- Implement `delete_midi_notes`.
- Implement `insert_audio_item`.
- Add stable item and take GUID handling.
- Add tests for position conversion.
- Add tests for MIDI payload validation.

Exit criteria:

- A client can create an 8-bar MIDI item.
- A client can add a simple drum pattern.
- A client can read the notes it created.
- A client can insert an audio item from an explicitly allowed source root.
- Item responses include stable item GUIDs.

## Phase 5: FX, markers, regions, and tempo

This phase gives the MCP server enough control for practical arrangement and
mix setup.

Goals:

- Add and inspect FX.
- Create arrangement markers and regions.
- Control tempo and time signature.

Tasks:

- Implement `list_track_fx`.
- Implement `list_available_fx`.
- Implement `add_fx`.
- Implement `remove_fx`.
- Implement `set_fx_enabled`.
- Implement `get_fx_parameters`.
- Implement `set_fx_parameter`.
- Implement guarded FX preset name, index, and navigation tools.
- Implement `create_marker`.
- Implement `list_markers`.
- Implement `delete_marker`.
- Implement `create_region`.
- Implement `list_regions`.
- Implement `delete_region`.
- Implement `get_tempo`.
- Implement `set_tempo`.
- Implement `get_time_signature`.
- Implement `set_time_signature`.

Exit criteria:

- A client can add an FX to a track.
- A client can read and set an FX parameter.
- A client can create verse and chorus regions.
- A client can set tempo and time signature.

## Phase 6: Render tools

This phase completes the basic production loop from creation to output.

Goals:

- Render projects and selected regions.
- Enforce file output safety.
- Return render results clearly.
- Treat render execution as a transaction with explicit liveness and recovery
  evidence.

Tasks:

- Define allowed render root configuration.
- Use an isolated REAPER process for confirmed project renders; require an
  explicit operator confirmation only for the native fallback path.
- Implement the `render_project` job lifecycle with status and result polling.
- Snapshot, apply, restore, and verify render settings and project dirty state.
- Require a stable, non-empty output file before success.
- Use a temporary output and atomic promotion for overwrite requests.
- Implement `render_selected_region`.
- Implement `render_regions`.
- Implement `render_stems`.
- Validate output paths.
- Return output files and render status.
- Add manual render smoke tests.

Exit criteria:

- A client can render to an allowed path.
- A client cannot render outside configured roots.
- Render errors return actionable messages.
- A completed result contains output metadata and restoration/dirty-state trace
  evidence.
- An active render cannot be mistaken for success when the bridge heartbeat is
  stale.

## Phase 7: Installation and release surface

This phase makes the accepted core easy to install and run.

Goals:

- Install the Lua bridge into the REAPER resource directory.
- Package and launch the Python server through one command.
- Keep setup deterministic and non-interactive.

Tasks:

- Adapt the useful bridge-copy behavior from `total-reaper-mcp`.
- Detect Linux, macOS, and Windows REAPER resource paths.
- Support an explicit resource-path override.
- Back up a different existing bridge before replacement.
- Add a packaged `reaper-mcp-install` command.
- Add focused installer tests.
- Add concise MCP client configuration examples.
- Add an optional loopback-only REST adapter over the existing MCP server.
- Add REST discovery and tool-call contract tests.
- Add a complete CLI adapter with generic tool dispatch and producer aliases.
- Add CLI output and exit-code tests.

Exit criteria:

- A source checkout and built package can install the bridge.
- Re-running the installer is deterministic.
- A user can start the server with `reaper-mcp`.
- A local script can discover and call visible tools over HTTP without a second
  business-logic path.
- A shell user can discover and call every visible tool without a second
  business-logic path.

## Phase 8: Essential competitor parity

This phase adapts the highest-value missing operations from the two reference
projects. It is deliberately smaller than either repository's full tool list.

Goals:

- Complete common track, item, routing, and mix operations.
- Reuse proven ReaScript action and property mappings.
- Preserve GUID addressing, structured errors, and one-step undo.

Tasks:

- Adapt track volume and pan controls.
- Adapt master volume, pan, mute, and FX inspection.
- Adapt media-item position, length, duplication, splitting, mute, gain, fades,
  and deletion.
- Adapt track sends and bus routing.
- Adapt track freeze and unfreeze after selection restoration is defined.
- Add one practical song-starter workflow from accepted primitives.
- Add focused unit tests and one consolidated live acceptance bucket.

Exit criteria:

- A client can perform the common editing and routing operations missing from
  the accepted core.
- Every adapted mutation remains undoable and returns stable identities.
- The default tool surface contains only tools selected for the release.

Accepted scope:

- Track and master mix controls passed live acceptance.
- Media-item move, resize, duplicate, split, mute, gain, fades, and delete
  passed with GUID addressing and named undo actions.
- Routing, freeze, and the song-starter workflow passed live acceptance.

## Phase 9: Producer expansion and capability profiles

This phase adds the remaining producer controls selected from the competitor
review without exposing a raw ReaScript proxy.

Goals:

- Add advanced capability groups.
- Keep raw ReaScript calls behind allowlists.
- Build coverage based on real workflows.

Accepted capabilities:

- Tool profiles and capability discovery.
- Built-in track automation envelopes and guarded points.
- Take management and guarded crop-to-active-take comping.
- Project save, cursor, time selection, and loop controls.
- MIDI controller event editing with guarded identities.
- Tempo-map marker editing with guarded identities.
- Grid, metronome, playback-rate, undo, and redo controls.
- Track recording and folder-depth controls.
- FX preset reads/writes, FX movement, and FX-chain copying.
- Sidechain send setup with explicit source and destination channels.
- Track-template file operations with approved-root policies.
- Preflighted batch track updates.
- Read-only PCM WAV analysis with approved-root policies.
- Deterministic chord and arpeggio MIDI pattern generation.
- Guarded take-FX listing and mutation.

Deferred candidates:

- Project open and project tabs.
- Advanced bus topology beyond the guarded sidechain helper.
- LUFS, true-peak, and REAPER-native live metering.
- Action management.
- Project tabs.
- Layouts and screensets.
- Raw ReaScript proxy.

Accepted scope:

- Guarded transpose, nudge, quantize, deterministic humanize, scale snap,
  velocity shaping, and overlap removal passed live Linux acceptance.
- Every transform requires current note fingerprints, preflights the complete
  plan, applies one sorted batch, and creates one named undo action.
- MIDI insertion rejects identity-ambiguous duplicate note keys and restores the
  raw take event buffer if a post-insert invariant fails.
- Twenty-six new REAPER commands passed a consolidated Linux smoke for
  automation, takes, comping, navigation, and saving.
- Five profile management tools filter discovery and reject calls to hidden
  tools. The default profile excludes experimental rendering.
- The production profile exposes 142 stable tools; the full profile exposes 146
  including the four experimental render tools.

Exit criteria:

- Advanced groups are loaded only when enabled.
- Raw ReaScript calls require the `raw_reascript` capability.
- Advanced tools use the same safety and error model as core tools.

## Phase 10: v0.1 release

This phase prepares the project for broader use.

Goals:

- Stabilize installation.
- Improve diagnostics.
- Package a first release.

Tasks:

- Add bridge installation instructions for REAPER.
- Add MCP client configuration examples.
- Add manual REAPER integration checklist.
- Add package metadata.
- Tag the first release.

Exit criteria:

- A new user can install the server and bridge from docs.
- Unit tests and the Linux REAPER acceptance suite pass.
- Isolated project rendering is live-accepted, and native lifecycle tools are
  clearly excluded from the stable profile without blocking the release.
- The package has a versioned release.

## Test strategy

Testing needs two tracks: fast tests without REAPER and integration tests with
REAPER running.

Fast tests:

- Command schema validation.
- Tool profile registration.
- Position conversion.
- Bridge request and response parsing.
- Error normalization.
- Path policy validation.

REAPER integration tests:

- Bridge health.
- Project snapshot.
- Track mutation and undo.
- MIDI item creation.
- FX add and parameter read.
- Marker and region creation.
- Render to allowed path.

Manual tests:

- Start REAPER.
- Run the Lua bridge.
- Start the MCP server.
- Connect MCP Inspector.
- Run a full create, edit, arrange, and render workflow.
- Undo each mutating action in REAPER.

## Release plan

The first public release must be small and dependable.

The next release is `0.1.0`. It registers 146 tools, exposes 142 through the
default production profile, and keeps the four render tools experimental. The
original 99 non-render bridge tools are live-accepted on Linux; the producer
expansion commands and isolated project rendering are live-accepted on Linux.
Audio analysis is unit-tested and approved-WAV live-verified; native render
lifecycle tools remain outside the stable release claim.

## Definition of done

A phase is done only when implementation, tests, and docs move together.

Each phase requires:

- Implemented tools or components.
- Unit tests for non-REAPER logic.
- Manual or automated REAPER verification.
- Updated docs when setup, behavior, or tool schemas change.
- Clear known limitations.

## Next steps

The packaged bridge installer, competitor-parity operations, guarded MIDI
transformations, automation, takes, navigation, saving, profiles, producer
expansion implementation, local audio analysis, and isolated project rendering
are complete in code and Linux-verified. Finish the native render lifecycle and
add macOS and Windows acceptance without blocking the stable Linux core.
