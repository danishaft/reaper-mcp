# REAPER MCP engineering standards

This document defines the engineering decisions for the REAPER MCP server. Use
it before implementation work so the codebase stays consistent as the bridge,
tool count, and workflow layer grow.

> **Note:** This is a planning document for a new implementation. Update it
> when the codebase proves that a decision needs to change.

## Purpose

The project needs a small set of explicit rules before coding starts. These
rules prevent tool sprawl, bridge coupling, unsafe mutations, and inconsistent
Python code as the MCP server grows.

This document covers:

- The standard technology kit.
- The architecture boundaries.
- The core data structures.
- The bridge and command algorithms.
- The clean Python rules.
- The performance and testing rules.
- The anti-hallucination rules for AI-facing tools.

## Diagnosis

The main engineering challenge is not calling REAPER once. The challenge is
building a system that stays understandable when it has many tools, many object
types, and both high-level workflows and low-level ReaScript access.

The system fails if:

- MCP tools call bridge internals directly.
- Raw ReaScript functions become the default tool surface.
- Track and item indices become the primary identity model.
- Mutating tools bypass validation or undo blocks.
- Error handling becomes scattered strings.
- Tool descriptions overpromise what the implementation can do.

## Standard kit

The project uses a boring, constrained stack. New dependencies need a clear
reason tied to reliability, safety, or developer speed.

Approved core tools:

- Python `>=3.11`.
- `uv` for local environment and package workflows.
- `mcp` Python SDK for server transport and tool registration.
- `pydantic v2` for schemas, validation, and typed command envelopes.
- `pydantic-settings` for environment configuration.
- `pytest` for tests.
- `pytest-asyncio` for async bridge and MCP tests.
- `ruff` for linting and formatting.
- Lua inside REAPER for native ReaScript execution.
- Biome for JavaScript and TypeScript linting and formatting when JavaScript or
  TypeScript is added.
- JSDoc for public JavaScript and TypeScript APIs, user-editable scripts, and
  integration examples.

Deferred tools:

- Socket transport only after measured file-bridge latency blocks a real
  workflow.
- Static type checking when it removes defects not covered by the current typed
  schemas and Ruff checks.
- Coverage reporting when the metric will drive a specific test-quality
  decision.

## Architecture rules

The server uses layered architecture. Each layer has one job and only depends on
the layer below it.

Required flow:

```text
MCP, CLI, or REST adapter
  -> profiled tool registry
  -> thin tool layer
  -> service and workflow layer
  -> models and operation-specific policies
  -> bridge client interface
  -> Lua bridge
  -> ReaScript API
```

Rules:

- MCP tools stay thin.
- Services contain workflow and business logic.
- Models and services validate inputs and filesystem policies before bridge
  execution.
- The bridge client owns request and response transport.
- The Lua bridge owns direct ReaScript calls, identity resolution, mutation
  preflight, and undo blocks.
- Tool code must not write bridge files directly.
- Workflow code must not import MCP decorators.
- Lua bridge commands must use the shared command envelope.
- CLI and REST must call the shared tool registry instead of creating separate
  business paths.

## Package layout

The package layout keeps transport, services, models, and bridge code separate.
Create new modules only when they represent a real responsibility.

Current structure:

```text
src/reaper_mcp/
|-- server.py
|-- cli.py
|-- rest.py
|-- install.py
|-- config.py
|-- errors.py
|-- logging.py
|-- profiles.py
|-- models/
|-- tools/
|-- services/
`-- bridge/
    |-- base.py
    `-- file_bridge.py
lua/
`-- reaper_mcp_bridge.lua
tests/
|-- unit/
`-- integration/
```

Safety is a cross-cutting responsibility implemented in models, services,
`CommandOptions`, the file bridge, and Lua command definitions. Do not create a
standalone safety package unless it would own cohesive reusable behavior that
those boundaries cannot express.

## Python coding rules

Python code must be typed, explicit, and easy to test without REAPER.

Rules:

- Type-hint all public functions and methods.
- Use `dataclass` only for internal simple values.
- Use `pydantic.BaseModel` for external inputs, outputs, config, and bridge
  payloads.
- Use `pathlib.Path` for filesystem paths.
- Use `time.monotonic()` for timeouts.
- Use enums or literals for profiles, capabilities, transports, and error
  codes.
- Keep MCP tool functions as adapters that call services.
- Keep constructors free of network, filesystem, or REAPER side effects.
- Avoid module-level mutable state except controlled config constants.
- Avoid broad `except Exception` unless converting to a structured error.
- Avoid hidden bridge calls from model methods or validators.
- Prefer clear functions over clever abstractions.

Naming rules:

- Use verbs for mutating tool names, such as `create_track`.
- Use `get_` for a single object or state query.
- Use `list_` for collections.
- Use `set_` for property updates.
- Use explicit destructive names, such as `delete_track` or `remove_fx`.
- Avoid vague names such as `do_action`, `handle_request`, or `process_data`.

## JavaScript and TypeScript rules

JavaScript and TypeScript are secondary in this project. Use them only for
tooling, examples, UI work, or integration scripts that genuinely need them.

Rules:

- Use Biome as the formatter and linter.
- Keep JavaScript and TypeScript modules narrow and explicit.
- Use JSDoc for exported functions, public examples, and user-editable scripts.
- Document parameters, return values, side effects, and expected environment for
  public scripts.
- Avoid adding a separate JavaScript toolchain when Python can solve the problem
  cleanly.
- Avoid mixing unrelated UI, build, and server concerns in the same module.

## Comment rules

Comments must explain intent, invariants, and non-obvious constraints. They must
not narrate code that is already clear.

Rules:

- Add comments before complex bridge, validation, or undo behavior.
- Add comments for REAPER-specific constraints that are not obvious from the
  code.
- Add docstrings for public Python modules, services, and bridge interfaces.
- Add JSDoc for public JavaScript and TypeScript entrypoints.
- Do not add noisy comments such as "set variable" or "loop through items."
- Update comments when behavior changes.

## Implementation discipline

The project values clean first-principles engineering over quick patchwork. A
small correct design is better than a large clever design.

Rules:

- Fix root causes instead of layering local patches over broken boundaries.
- Keep changes small enough to review.
- Add abstractions only when they remove real duplication or clarify ownership.
- Keep modules cohesive and avoid circular dependencies.
- Prefer explicit data flow over hidden mutation.
- Avoid speculative extension points.
- Avoid copying patterns from reference repos without re-evaluating them.
- Keep the implementation aligned with the documented architecture.

## Type and schema rules

Schemas are the contract between the MCP client, the Python server, and the Lua
bridge. They must remain stable and easy to inspect.

Rules:

- Define all MCP tool inputs with Pydantic models where practical.
- Define all bridge requests and responses with Pydantic models.
- Keep external schema fields explicit and descriptive.
- Validate path, time position, GUID, and enum fields before bridge calls.
- Reject media source files outside configured allowed roots before bridge
  calls.
- Reject render output paths outside configured allowed roots before bridge
  calls.
- Reject template and audio-analysis paths outside their configured allowed
  roots before filesystem or bridge calls.
- Use defaults only when they are safe and unsurprising.
- Return structured results instead of free-form strings.
- Do not expose unrestricted raw ReaScript payloads.

## Core data structures

The server uses snapshots and command envelopes as its core data model. These
structures give the AI client stable context without forcing many small calls.

Representative models:

- `ProjectSnapshot`.
- `TrackSnapshot`.
- `MediaItemSnapshot`.
- `TakeSnapshot`.
- `FxSnapshot`.
- `MarkerSnapshot`.
- `RegionSnapshot`.
- `CommandEnvelope`.
- `BridgeResponse`.
- `ErrorResponse`.

List models preserve REAPER UI order. The Python process does not keep a
project-state cache; read tools request current state from REAPER. Lua resolves
GUIDs and guarded compound identities against the active project at execution
time.

## Identity rules

Stable identity is mandatory because REAPER track, item, take, and FX indices
can change during normal editing.

Rules:

- Use track GUIDs as primary track identifiers.
- Use media item GUIDs as primary item identifiers.
- Use take GUIDs as primary take identifiers.
- Identify FX by track GUID plus FX index plus REAPER FX GUID when available.
- When REAPER does not provide an FX GUID, guard FX mutations with the expected
  FX name at that index.
- Address FX parameters by guarded FX identity plus parameter index, and accept
  normalized parameter values from `0.0` to `1.0` for writes.
- Use REAPER marker and region IDs for marker and region identity, and guard
  deletes with expected names or timeline positions when callers provide them.
- Accept time signature denominators only from `1`, `2`, `4`, `8`, `16`, `32`,
  and `64`.
- Return GUIDs after every mutation that creates or changes an object.
- Accept index references only as convenience inputs.
- Resolve index inputs to GUIDs before a mutating operation.
- Reject ambiguous natural-language references unless a resolver can prove a
  single match.

## Algorithm decisions

The implementation uses simple, predictable algorithms before complex
optimization. Batch operations matter more than clever local caching.

Decisions:

- Use GUID lookup as the primary object resolution algorithm.
- Use index lookup only as an input normalization step.
- Use request IDs to correlate every bridge request and response.
- Use one command envelope per logical tool call.
- Batch related project mutations into one bridge command where practical.
- Batch MIDI note insertion instead of sending one bridge request per note.
- Validate a complete batch before applying its first mutation.
- Use fingerprints to reject stale MIDI and index-based identities.
- Resolve filesystem paths before checking containment in approved roots.
- Publish bridge JSON through a temporary file and atomic rename.
- Poll native render output until its size is stable before completion.
- Use set membership for profile and capability call gating.

## Bridge design rules

The file bridge is the implemented transport because it is portable and easy
to debug. It remains behind an interface so a measured transport problem can
be solved without changing tools or services.

Rules:

- Put bridge behavior behind a `BridgeClient` interface.
- Keep `FileBridgeClient` as the concrete client until measurements justify a
  replacement.
- Use JSON for request and response files.
- Include request IDs in every file.
- Use one response file per request.
- Publish request and response files with temporary writes and atomic renames.
- Clean up completed request and response files.
- Ignore stale files from prior sessions.
- Time out bridge calls with a structured error.
- Keep bridge directory configurable through settings.
- Treat a timed-out mutation as outcome-uncertain if Lua may have started it.

## Command envelope rules

The command envelope is the shared protocol between Python and Lua. Every bridge
command uses this shape, even when the command is read-only.

Required fields:

- `id`: request ID.
- `command`: bridge command name.
- `args`: structured command arguments.
- `options.mutates_project`: whether the command changes the project.
- `options.undo_label`: REAPER undo label for mutating commands.
- `options.dry_run`: whether the command previews behavior.

Example:

```json
{
  "id": "request-001",
  "command": "create_midi_item",
  "args": {
    "track_guid": "{TRACK-GUID}",
    "start": { "measure": 1, "beat": 1 },
    "length_beats": 16
  },
  "options": {
    "mutates_project": true,
    "undo_label": "Create MIDI item",
    "dry_run": false
  }
}
```

## Safety rules

Safety rules protect the user's REAPER project and make AI actions reversible.
They are release requirements, not polish work.

Rules:

- Validate inputs before bridge execution.
- Wrap every mutating command in one named REAPER undo block.
- Return changed object IDs after every successful mutation.
- Reject ambiguous destructive operations.
- Keep destructive tools explicit and narrow.
- Support dry-run for workflow tools where practical.
- Enforce render and file path policies.
- Require explicit allowed roots for media source reads.
- Require explicit allowed roots for render output writes.
- Never write outside configured roots.
- Never assume a plugin, track, item, take, or FX exists.
- Query or resolve project state before mutating it.

## Error model

Errors must be structured, stable, and useful to both humans and MCP clients.
Do not return random exception strings as tool results.

Every error includes:

- `code`: stable machine-readable error code.
- `message`: concise human-readable message.
- `details`: optional structured context.
- `recoverable`: recovery hint.
- `suggested_action`: optional next action.

Example:

```json
{
  "ok": false,
  "error": {
    "code": "bridge_not_running",
    "message": "The REAPER Lua bridge is not running.",
    "details": {},
    "recoverable": true,
    "suggested_action": "Start the Lua bridge in REAPER."
  }
}
```

Error codes must live in one enum or constants module.

## Tool design rules

AI-facing tools must be boring, exact, and honest. A tool description is part of
the product contract.

Rules:

- Give every tool a precise name.
- Describe what the tool changes and what it never changes.
- Keep one tool focused on one logical task.
- Prefer workflow tools for common music tasks.
- Do not expose unrestricted raw ReaScript tools.
- Return stable IDs, summaries, and warnings.
- Return enough context for the client to continue without guessing.
- Reject vague object references unless the resolver finds one clear match.
- Keep default profile tool count manageable.

## Profile and capability rules

Profiles define the default MCP surface. Capabilities let advanced users load
more power only when needed.

Required profiles:

- `minimal`.
- `production`.
- `midi`.

Additional profiles:

- `mixing`.
- `full`.

Experimental rendering remains a capability rather than a default profile.

Required capability tools:

- `list_capabilities`.
- `enable_capability`.
- `disable_capability`.
- `get_active_profile`.
- `set_active_profile`.

## Performance rules

The project avoids premature optimization, but it must not make known expensive
mistakes.

Rules:

- Batch MIDI note creation and updates.
- Batch workflow mutations into one bridge command where practical.
- Avoid one bridge call per property when a snapshot can return the data.
- Query current REAPER state instead of introducing a cache without a proven
  invalidation design.
- Avoid sending full MIDI notes, peaks, or project state unless requested.
- Keep large payloads behind dedicated tools.
- Use bridge duration logs to identify slow operations.
- Add socket transport only after file bridge bottlenecks are measured.

## Testing rules

Tests must prove behavior without requiring REAPER for every check. REAPER
integration tests are still required for bridge and undo behavior.

Fast tests:

- Schema validation.
- Config parsing.
- Command envelope creation.
- Bridge request and response parsing.
- Error normalization.
- Path policy validation.
- Tool profile registration.
- GUID and index resolution.
- Musical position conversion.

REAPER integration tests:

- Lua bridge health.
- Project snapshot.
- Track creation and undo.
- MIDI item creation and note insertion.
- FX insertion and parameter read.
- Marker and region creation.
- Render path validation.
- Render execution to an allowed path.

Manual tests:

- Start REAPER.
- Run the Lua bridge.
- Start the MCP server.
- Connect MCP Inspector.
- Run a create, edit, arrange, and render workflow.
- Undo each mutating action in REAPER.

## Observability rules

Logs must explain what happened without dumping large musical payloads by
default.

Bridge completion logs require these fields:

- Request ID.
- Bridge command name.
- Target object IDs.
- Duration.
- Result status.
- Error code.

Render transactions also retain stage, elapsed time, and detail trace points.
Debug mode can include larger payloads. Default logs must avoid full MIDI note
lists, waveform peaks, and complete project dumps.

## Configuration rules

Configuration must be explicit, local, and easy to diagnose at startup.

Required settings:

- `REAPER_MCP_BRIDGE_DIR`.
- `REAPER_MCP_TOOL_PROFILE`.
- `REAPER_MCP_LOG_LEVEL`.
- `REAPER_MCP_ALLOWED_MEDIA_SOURCE_ROOTS`.
- `REAPER_MCP_ALLOWED_PROJECT_ROOTS`.
- `REAPER_MCP_ALLOWED_RENDER_ROOTS`.
- `REAPER_MCP_ALLOWED_TEMPLATE_ROOTS`.
- `REAPER_MCP_ALLOWED_AUDIO_ROOTS`.
- `REAPER_MCP_TRANSPORT`.
- `REAPER_MCP_HTTP_HOST` and `REAPER_MCP_HTTP_PORT` when HTTP transport is used.
- `REAPER_MCP_BRIDGE_TIMEOUT_SECONDS`.
- `REAPER_MCP_RENDER_EXTERNAL_ENABLED`.
- `REAPER_MCP_REAPER_EXECUTABLE` when isolated rendering cannot discover
  REAPER.

Configuration defaults must remain local and conservative. Approved-root lists
default to empty, REST defaults to `127.0.0.1`, the stable tool profile defaults
to `production`, and isolated rendering defaults to enabled.

## Anti-hallucination rules

The MCP server must make it hard for an AI client to invent project state. Tools
must return enough facts for the next tool call to be grounded.

Rules:

- Query before mutation when target state is uncertain.
- Treat `ProjectSnapshot` as the source of truth for project context.
- Reject vague references like "the bass track" when multiple matches exist.
- Return actual GUIDs after mutations.
- Return warnings when a request partially succeeds.
- Never claim a plugin was added unless REAPER confirms it.
- Never claim a render finished unless the typed output and restoration
  invariants pass.
- Never expose unrestricted raw ReaScript access.

## Review checklist

Use this checklist before merging any implementation change.

- The change keeps MCP tools thin.
- The change uses Pydantic models for external payloads.
- The change validates inputs before bridge execution.
- The change uses stable IDs in outputs.
- The change wraps mutations in undo blocks.
- The change returns structured errors.
- The change has unit tests for non-REAPER logic.
- The change has manual or automated REAPER verification when bridge behavior
  changes.
- The change does not add a broad dependency without justification.
- The change does not increase the default tool surface without profile review.

## Next steps

Keep the `production` profile free of experimental native render tools until
live evidence proves bridge liveness, output integrity, and state restoration.
Measure file-bridge latency before adding another transport, and require live
REAPER evidence when a change affects identity, undo, or native API behavior.
