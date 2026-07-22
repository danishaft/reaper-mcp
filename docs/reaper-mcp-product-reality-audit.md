# REAPER MCP product reality audit

This document records what the repository implements, what automated tests
cover, and what has actually passed inside REAPER. It is the acceptance source
of truth for the repeatable integration suite and retained manual evidence.

> **Note:** This is a preview feature currently under active development.

Audit date: July 19, 2026.

## How to read this audit

The three evidence levels are intentionally separate.

- **Implemented** means the MCP tool and its complete runtime path exist.
- **Unit covered** means a focused service test or a group test exercises the
  tool without REAPER.
- **Live status** means retained evidence exists from a REAPER smoke test.

In the matrix, `Yes` means a focused unit test exists. `Group` means one test
loops over several related commands.

`Unverified` does not mean broken. It means the project has no retained live
evidence strong enough to call the behavior complete. A phase is not complete
until its required live checks pass and the evidence is recorded here.

## Current conclusion

The repository is a Linux-verified `0.1.0` release candidate. It registers 108
MCP tools and exposes 104 in the default `production` profile. It has 129
passing unit tests and nine opt-in integration buckets. The current bridge live
score is 99 passed, 2 partial, 2 blocked, and 0 unverified. Five local profile
tools also pass discovery and call-gating tests. Every production-profile tool
has therefore passed at its required evidence level; rendering remains the only
unaccepted group and is hidden by default.

Full-project rendering is not live-accepted. The tested REAPER profile has
background rendering disabled, and the earlier smoke showed that action `42230`
can create a WAV while blocking the Lua bridge before it returns. The server now
requires explicit background-render confirmation before invoking that path, so a
normal MCP call fails closed instead of blocking. No confirmed completed MCP
render result has been recorded yet.

## Phase status

This table replaces phase completion inferred from code or unit tests.

| Phase | Implementation | Live evidence | Current status |
| --- | --- | --- | --- |
| 0. Foundation | Present | Not applicable | Locally verified |
| 1. Bridge and server | Present | All exposed diagnostics passed | Accepted on REAPER 7.66 Linux |
| 2. Safety and envelope | Present | Envelope, timeout, recovery, errors, and undo passed | Accepted on REAPER 7.66 Linux |
| 3. Project, tracks, transport | Present | All tools and track undo passed | Accepted on REAPER 7.66 Linux |
| 4. MIDI and media | Present | All tools, guards, paths, and undo-redo passed | Accepted on REAPER 7.66 Linux |
| 5. FX and arrangement | Present | All FX, arrangement, and tempo checks passed | Accepted on REAPER 7.66 Linux |
| 6. Rendering | Partial | Blocked path passed; allowed render hung | Blocked |
| 7. Installation and release surface | Package and installer present | Linux artifacts and install passed | Accepted on Linux |
| 8. Essential competitor parity | Present | Item editing, routing, freeze, and workflow passed | Accepted on REAPER 7.66 Linux |
| 9. Producer expansion | Automation, takes, navigation, and profiles present | 26 bridge tools passed; five profile tools passed locally | Accepted on REAPER 7.66 Linux |
| 10. v0.1 release | Artifacts present | Source, wheel, and installed bridge verified | Release candidate verified |

## Tool acceptance matrix

Every currently exposed MCP tool appears below. Live statuses come only from
the retained smoke-test reports in the project work session.

### Health and diagnostics

These tools establish whether the Python server and Lua bridge can communicate.

| Tool | Unit covered | Live status | Evidence or required check |
| --- | --- | --- | --- |
| `health_check` | Yes | Passed | Returned healthy bridge details during multiple smokes |
| `get_reaper_version` | Group | Passed | Returned `7.66/linux-x86_64` |
| `get_project_info` | Group | Passed | Matched the empty scratch project |
| `get_bridge_status` | Group | Passed | Confirmed render command cleanup and bridge status |

### Project and track tools

Track mutations require stable GUIDs, one undo action, and a refreshed read.

| Tool | Unit covered | Live status | Evidence or required check |
| --- | --- | --- | --- |
| `get_project_snapshot` | Yes | Passed | Matched the isolated scratch project |
| `list_tracks` | Yes | Passed | Verified count, state, UI order, and stable GUID |
| `create_track` | Yes | Passed | Created a track during the render smoke setup |
| `rename_track` | Yes | Passed | Renamed, read back, undid, and redid |
| `set_track_color` | Yes | Passed | Set, read back, undid, and redid |
| `set_track_mute` | Yes | Passed | Set, read back, undid, and redid |
| `set_track_solo` | Yes | Passed | Set, read back, undid, and redid |
| `set_track_arm` | Yes | Passed | Set, read back, undid, and redid |
| `set_track_volume` | Yes | Passed | Adapted from `reaper-reapy-mcp`; set linear gain and undid-redid |
| `set_track_pan` | Yes | Passed | Adapted from `reaper-reapy-mcp`; set pan and undid-redid |
| `delete_track` | Yes | Passed | Deleted by GUID, undid, and redid with GUID preserved |

### Master track tools

Master mutations use explicit values rather than ambiguous toggle operations.

| Tool | Unit covered | Live status | Evidence or required check |
| --- | --- | --- | --- |
| `get_master_track` | Yes | Passed | Returned GUID, linear gain, pan, and mute state |
| `set_master_volume` | Yes | Passed | Adapted property mapping, read back, undid, and redid |
| `set_master_pan` | Yes | Passed | Adapted property mapping and read back |
| `set_master_mute` | Yes | Passed | Set explicit state, read back, undid, and redid |

### Transport tools

Transport tests must include active recording because stopping recording can
create media items.

| Tool | Unit covered | Live status | Evidence or required check |
| --- | --- | --- | --- |
| `play` | Group | Passed | Started playback and returned playing state |
| `stop` | Group | Passed | Rejected active recording with the expected error |
| `stop_recording` | Group | Passed | Stopped recording through the mutating path |
| `pause` | Group | Passed | Paused active playback and returned paused state |
| `record` | Group | Passed | Armed a track, started recording, and returned recording state |

### Media and MIDI tools

Media tests must prove stable item and take GUIDs, guarded note identity, source
path safety, and one undo action per mutation.

| Tool | Unit covered | Live status | Evidence or required check |
| --- | --- | --- | --- |
| `list_media_items` | Yes | Passed | Preserved item and take GUIDs through undo-redo |
| `create_midi_item` | Yes | Passed | Created by track GUID and restored stable item and take GUIDs |
| `insert_audio_item` | Yes | Passed | Rejected a blocked path, inserted an allowed WAV, and undid-redid |
| `move_media_item` | Yes | Passed | Moved by item GUID to measure 3 and undid-redid |
| `resize_media_item` | Yes | Passed | Resized by item GUID to two beats with readback |
| `duplicate_media_item` | Yes | Passed | Returned a new GUID, restored selection, and undid-redid |
| `split_media_item` | Yes | Passed | Rejected an outside split, returned both GUIDs, and undid-redid |
| `set_media_item_mute` | Yes | Passed | Set explicit mute state, read back, and undid-redid |
| `set_media_item_gain` | Yes | Passed | Set linear gain by item GUID and read back the value |
| `set_media_item_fade_in` | Yes | Passed | Set and read back a manual fade-in length |
| `set_media_item_fade_out` | Yes | Passed | Set and read back a manual fade-out length |
| `delete_media_item` | Yes | Passed | Deleted by item GUID and restored the same GUID through undo |
| `get_midi_notes` | Yes | Passed | Returned ordered notes with current fingerprints |
| `add_midi_note` | Yes | Passed | Inserted one note and undid-redid the take state |
| `add_midi_notes` | Yes | Passed | Inserted a batch and undid-redid the take state |
| `update_midi_note` | Yes | Passed | Updated by fingerprint, rejected a stale guard, and undid-redid |
| `delete_midi_notes` | Yes | Passed | Deleted by fingerprint and undid-redid the take state |

### MIDI transformation tools

MIDI transformations require explicit note fingerprints, preflight every
target, apply one sorted batch, and create one named undo action.

| Tool | Unit covered | Live status | Evidence or required check |
| --- | --- | --- | --- |
| `transpose_midi_notes` | Yes | Passed | Transposed by two semitones, rejected stale identity and pitch overflow, and undid-redid |
| `nudge_midi_notes` | Yes | Passed | Shifted one note by 0.1 beats while preserving duration |
| `quantize_midi_notes` | Yes | Passed | Quantized the shifted onset to a quarter-beat grid |
| `humanize_midi_notes` | Yes | Passed | Repeated seed 42 after undo and reproduced the same timing and velocity state |
| `snap_midi_notes_to_scale` | Yes | Passed | Snapped D-sharp down to D in C major with deterministic nearest-note policy |
| `shape_midi_note_velocities` | Yes | Passed | Scaled guarded velocities and returned the full refreshed take state |
| `remove_midi_note_overlaps` | Yes | Passed | Trimmed overlap, undid-redid, and rejected same-onset ambiguity without deleting notes |

### FX tools

FX mutations must use guarded identity and account for plugin availability on
the test machine.

| Tool | Unit covered | Live status | Evidence or required check |
| --- | --- | --- | --- |
| `list_available_fx` | Yes | Passed | Returned 248 installed FX in the recorded smoke |
| `list_track_fx` | Yes | Passed | Returned an empty FX list on a fresh track |
| `add_fx` | Yes | Passed | Added stock ReaEQ and preserved identity through undo-redo |
| `remove_fx` | Yes | Passed | Removed by guarded identity and undid-redid |
| `set_fx_enabled` | Yes | Passed | Disabled, read back, and undid-redid |
| `get_fx_parameters` | Yes | Passed | Returned parameters from stock ReaEQ |
| `set_fx_parameter` | Yes | Passed | Set a normalized value and undid-redid |

### Arrangement and tempo tools

Arrangement tests must verify IDs, stale guards, timeline values, and undo
behavior.

| Tool | Unit covered | Live status | Evidence or required check |
| --- | --- | --- | --- |
| `list_markers` | Yes | Passed | Matched marker ID, name, position, and order |
| `create_marker` | Yes | Passed | Created, read back, and restored through undo-redo |
| `delete_marker` | Yes | Passed | Rejected a stale guard, deleted, and undid-redid |
| `list_regions` | Yes | Passed | Matched region ID, name, bounds, and order |
| `create_region` | Yes | Passed | Created, read back, and restored through undo-redo |
| `delete_region` | Yes | Passed | Rejected a stale guard, deleted, and undid-redid |
| `get_tempo` | Yes | Passed | Matched effective project-start BPM |
| `set_tempo` | Yes | Passed | Set 128 BPM, read back, and undid-redid |
| `get_time_signature` | Yes | Passed | Matched the project-start signature |
| `set_time_signature` | Yes | Passed | Set 7/8, rejected denominator 7, and undid-redid |

### Automation envelope tools

Automation tools create supported built-in envelopes, use stable envelope
GUIDs, and guard point updates with index-and-fingerprint identities. Point
values use REAPER's scaled value domain.

| Tool | Unit covered | Live status | Evidence or required check |
| --- | --- | --- | --- |
| `list_track_envelopes` | Yes | Passed | Returned zero envelopes on a fresh track and the created volume envelope afterward |
| `ensure_track_envelope` | Yes | Passed | Created a volume envelope while restoring track selection |
| `get_envelope_points` | Yes | Passed | Returned the default point as scaled value `1.0` at 0 dB |
| `add_envelope_points` | Yes | Passed | Added a two-point batch in one sorted mutation |
| `update_envelope_point` | Yes | Passed | Updated a guarded point to scaled value `0.75` |
| `delete_envelope_points` | Yes | Passed | Deleted one guarded point and returned refreshed indexes |
| `delete_envelope_points_in_range` | Yes | Passed | Deleted two points from a guarded timeline range |
| `get_track_automation_mode` | Yes | Passed | Returned the current track mode by GUID |
| `set_track_automation_mode` | Yes | Passed | Set touch mode and returned the observed mode |

### Take and comping tools

Take tools use stable take GUIDs. Crop-to-active-take also checks the expected
active GUID and take count before invoking REAPER's native action.

| Tool | Unit covered | Live status | Evidence or required check |
| --- | --- | --- | --- |
| `list_item_takes` | Yes | Passed | Returned the initial MIDI take and active GUID |
| `add_empty_take` | Yes | Passed | Added and activated a second named take |
| `set_active_take` | Yes | Passed | Uses the same GUID resolver exercised by take mutations |
| `rename_take` | Yes | Passed | Renamed the active take to `Comp Winner` |
| `set_take_volume` | Yes | Passed | Set and read back linear take gain `0.8` |
| `set_take_pan` | Yes | Passed | Set and read back pan `-0.25` |
| `set_take_pitch` | Yes | Passed | Set and read back a two-semitone pitch shift |
| `set_take_playback_rate` | Yes | Passed | Set rate `1.25` with explicit pitch preservation disabled |
| `crop_to_active_take` | Yes | Passed | Reduced two takes to the guarded active take only |

### Project navigation and save tools

Navigation controls return the complete observed cursor, selection, loop, path,
and dirty state. Save-as uses a default-deny project-root policy.

| Tool | Unit covered | Live status | Evidence or required check |
| --- | --- | --- | --- |
| `get_project_navigation` | Yes | Passed | Returned complete scratch-project navigation state |
| `set_edit_cursor` | Yes | Passed | Moved and read back the cursor at 2.5 seconds |
| `set_time_selection` | Yes | Passed | Set and read back a non-empty range |
| `clear_time_selection` | Yes | Passed | Cleared the range and returned `is_set: false` |
| `set_loop_points` | Yes | Passed | Set and read back independent loop points |
| `set_loop_enabled` | Yes | Passed | Enabled repeat and returned the observed state |
| `save_project` | Yes | Passed | Saved the newly named project and cleared dirty state |
| `save_project_as` | Yes | Passed | Wrote an `.rpp` inside the allowed root and confirmed the active path |

### Tool profiles and capabilities

Profile tools run inside the MCP server and do not call REAPER. Tests verify
both filtered discovery and rejection of calls from stale tool discovery.

| Tool | Unit covered | Live status | Evidence or required check |
| --- | --- | --- | --- |
| `list_capabilities` | Yes | Local passed | Returned all 15 capability groups and profile mappings |
| `enable_capability` | Yes | Local passed | Added MIDI tools to the minimal profile |
| `disable_capability` | Yes | Local passed | Registry override behavior is covered with profile invariants |
| `get_active_profile` | Yes | Local passed | Returned active capabilities and override state |
| `set_active_profile` | Yes | Local passed | Switched discovery to mixing and cleared prior overrides |

### Routing tools

Track sends use source GUID, send slot, and expected destination GUID as guarded
identity. This improves on the index-only reference implementation.

| Tool | Unit covered | Live status | Evidence or required check |
| --- | --- | --- | --- |
| `list_track_sends` | Yes | Passed | Returned destination GUID, gain, pan, mute, and slot identity |
| `create_track_send` | Yes | Passed | Created between two GUID tracks and undid-redid |
| `set_track_send` | Yes | Passed | Rejected a stale destination, updated properties, and undid-redid |
| `remove_track_send` | Yes | Passed | Removed by guarded identity and restored through undo |

### Render tools

Render path validation and the deferred job contract are implemented, but render
execution is not live-accepted. These tools remain preview-only until REAPER
background rendering is enabled and a confirmed MCP result proves completion,
restoration, overwrite behavior, and bridge responsiveness.

| Tool | Unit covered | Live status | Evidence or required check |
| --- | --- | --- | --- |
| `render_project` | Yes | Blocked | Earlier confirmed path created a WAV but action `42230` blocked the bridge |
| `render_project_start` | Yes | Partial | Returned a job before the earlier bridge block; guarded path needs a rerun |
| `render_project_status` | Yes | Partial | Reported the blocked job as running without claiming success |
| `render_project_result` | Yes | Blocked | No completed result with restoration evidence exists |

### Workflow tools

The song starter adapts the chord templates, General MIDI drum map, and beat
layouts from `total-reaper-mcp`. This project adds typed input, one bridge
transaction, rollback, stable GUID results, signature checks, and undo-redo.

| Tool | Unit covered | Live status | Evidence or required check |
| --- | --- | --- | --- |
| `create_song_starter` | Yes | Passed | Created four tracks, four MIDI items, 184 notes, and one region; rejected 3/4 before mutation; undid and redid with stable GUIDs |

### Freeze tools

Freeze state uses REAPER's read-only `I_FREEZECOUNT` field. Freeze mutations
target one track by GUID, restore the prior track selection, and verify the
freeze count changed before reporting success.

| Tool | Unit covered | Live status | Evidence or required check |
| --- | --- | --- | --- |
| `get_track_freeze_state` | Yes | Passed | Returned the current freeze count and stable track GUID |
| `freeze_track` | Yes | Passed | Froze a WAV track, restored selection, stayed responsive, and undid-redid |
| `unfreeze_track` | Yes | Passed | Unfroze by GUID, restored selection, stayed responsive, and undid-redid |

## Known limitations and remaining work

These issues remain outside the accepted Linux non-render core.

- The tested REAPER profile has background rendering disabled, so action `42230`
  must not be invoked until the operator enables and confirms that preference.
- A live completed render result, restoration check, and overwrite smoke are
  still required before render execution can be accepted.
- The nine opt-in integration tests require a local isolated REAPER instance
  and are not part of the default unit-test run.
- The packaged bridge installer has unit coverage on Linux, macOS, and Windows
  path conventions. Installation and idempotent reinstallation passed against
  the local Linux REAPER resource directory.
- CI and macOS and Windows live verification are not implemented.

## Acceptance sequence

Run acceptance in this order so later tests rely only on proven foundations.

1. Verify health, diagnostics, invalid envelopes, timeout behavior, and bridge
   recovery.
2. Verify every project and track tool, including GUID stability and one-step
   undo.
3. Verify playback and recording safety, including media creation on recording
   stop.
4. Verify MIDI and audio workflows, item editing, transformations, insertion
   identity, selection restoration, path policies, note fingerprints, and undo.
5. Verify guarded send creation, stale identity rejection, updates, removal,
   and undo.
6. Verify FX discovery, guarded mutations, parameter writes, and undo with stock
   REAPER FX.
7. Verify markers, regions, tempo, time signatures, stale guards, and undo.
8. Verify the song starter's signature guard, returned identities, note counts,
   single transaction, and one-step undo-redo.
9. Verify automation, takes, comping, navigation, project paths, and profile
   discovery.
10. Enable REAPER background rendering, set the explicit confirmation flag, then
   verify render success, failure, timeout, overwrite preservation, state
   restoration, and bridge responsiveness.
11. Add render integration coverage, CI execution, and platform testing.

## Definition of accepted

A tool is accepted only when all of these statements are true.

- Its external schema and errors are stable.
- Focused unit tests cover success and important failure paths.
- A recorded REAPER test proves the real behavior.
- Mutations produce one named undo action.
- Created or changed objects return stable identifiers where available.
- Safety policies reject disallowed operations before bridge execution.
- Documentation describes the observed behavior and known limitations.

## Acceptance run log

This log keeps the live evidence attached to a date and outcome. Add a row after
each consolidated REAPER run.

| Date | Scope | Result | Evidence retained |
| --- | --- | --- | --- |
| July 18, 2026 | Bridge, recording stop, and FX reads | Passed selected checks | Health, bridge status, guarded stop, recording stop, 248 available FX, and empty fresh-track FX list |
| July 18, 2026 | MIDI render setup | Passed selected checks | Track, MIDI item, and batch notes were created; blocked output path was rejected |
| July 18, 2026 | Allowed full-project render | Blocked | The tested REAPER profile had background rendering disabled; an earlier run created a WAV but action `42230` did not return |
| July 18, 2026 | Automated core acceptance on REAPER 7.66 Linux | Passed | Diagnostics, project snapshot, every track tool, named undo-redo, playback, pause, record, guarded stop, and recording stop |
| July 18, 2026 | Consolidated non-render acceptance on REAPER 7.66 Linux | Passed | Five tests covered all 43 non-render tools, safety recovery, guards, stable identities, path policy, and undo-redo |
| July 18, 2026 | Reuse bucket 1 on REAPER 7.66 Linux | Passed | Five tests covered all 52 non-render tools, including track gain and pan, master controls, media-item move, resize, delete, and undo-redo |
| July 18, 2026 | Packaged bridge installer on Linux | Passed | Installed into the real REAPER resource directory, repeated as a no-op, and matched the source SHA-256 |
| July 18, 2026 | Guarded track routing on REAPER 7.66 Linux | Passed | Six tests covered all 56 non-render tools, including send create, stale guard, update, removal, and undo-redo |
| July 18, 2026 | Track freeze on REAPER 7.66 Linux | Passed | Seven tests covered all 59 non-render tools, including freeze count, selection restoration, liveness, misuse errors, and undo-redo |
| July 18, 2026 | Song starter on REAPER 7.66 Linux | Passed | The eighth test covered 4/4 preflight, four MIDI parts, 184 notes, one region, stable GUIDs, and one-step undo-redo |
| July 18, 2026 | `0.1.0` release artifacts | Passed | Wheel and source distribution built; wheel contents, license notices, installer idempotence, and matching bridge hashes were verified |
| July 18, 2026 | GUID-based media-item editing on REAPER 7.66 Linux | Passed | Duplicate, split, mute, gain, fades, selection restoration, preflight rejection, stable identities, and undo-redo passed |
| July 19, 2026 | Full installed-bridge acceptance on REAPER 7.66 Linux | Passed | All eight groups and 73 non-render tools passed in 106.02 seconds, including seven MIDI transforms, insertion identity, and undo-redo |
| July 19, 2026 | Producer expansion on REAPER 7.66 Linux | Passed | Automation creation and scaled point edits, take comping, cursor and loop state, allowed-root save-as, and 108-tool profile discovery passed |

## Next steps

Keep rendering experimental until a confirmed result leaves the bridge
responsive. Add macOS and Windows live acceptance after the Linux release
candidate remains stable under producer use.
