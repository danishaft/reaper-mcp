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

- Socket transport after the file bridge is stable.
- Static type checking after the package skeleton exists.
- Coverage reporting after the first useful test suite exists.

## Architecture rules

The server uses layered architecture. Each layer has one job and only depends on
the layer below it.

Required flow:

```text
MCP tool layer
  -> service and workflow layer
  -> safety and validation layer
  -> bridge client interface
  -> Lua bridge
  -> ReaScript API
```

Rules:

- MCP tools stay thin.
- Services contain workflow and business logic.
- The safety layer validates every mutating operation.
- The bridge client owns request and response transport.
- The Lua bridge owns direct ReaScript calls.
- Tool code must not write bridge files directly.
- Workflow code must not import MCP decorators.
- Lua bridge commands must use the shared command envelope.

## Package layout

The package layout keeps transport, services, models, and bridge code separate.
Create new modules only when they represent a real responsibility.

Target structure:

```text
src/reaper_mcp/
  __init__.py
  server.py
  config.py
  errors.py
  logging.py
  models/
    __init__.py
    bridge.py
    project.py
    tools.py
  tools/
    __init__.py
    health.py
    tracks.py
    transport.py
    midi.py
    fx.py
    render.py
  services/
    __init__.py
    project_service.py
    track_service.py
    midi_service.py
    fx_service.py
    render_service.py
    workflow_service.py
  bridge/
    __init__.py
    base.py
    file_bridge.py
    socket_bridge.py
  safety/
    __init__.py
    validators.py
    paths.py
    undo.py
  profiles/
    __init__.py
    registry.py
    capabilities.py
lua/
  reaper_mcp_bridge.lua
tests/
  unit/
  integration/
```

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
- Use defaults only when they are safe and unsurprising.
- Return structured results instead of free-form strings.
- Keep raw ReaScript payloads behind dedicated raw proxy models.

## Core data structures

The server uses snapshots and command envelopes as its core data model. These
structures give the AI client stable context without forcing many small calls.

Required models:

- `ProjectSnapshot`.
- `TrackSnapshot`.
- `ItemSnapshot`.
- `TakeSnapshot`.
- `FxSnapshot`.
- `MarkerSnapshot`.
- `RegionSnapshot`.
- `CommandEnvelope`.
- `BridgeResponse`.
- `ToolResult`.
- `ErrorResponse`.

Internal lookup maps:

```python
tracks_by_guid: dict[str, TrackSnapshot]
items_by_guid: dict[str, ItemSnapshot]
fx_by_track_guid: dict[str, list[FxSnapshot]]
track_order: list[str]
```

The ordered lists preserve REAPER UI order. The maps provide stable lookup.

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
- Use snapshot invalidation after every successful mutation.
- Use snapshot diffing later to summarize workflow changes.
- Use allowlists for raw ReaScript function access.
- Use capability gates to load broad tool groups on demand.

## Bridge design rules

The file bridge is the first transport because it is portable and easy to
debug. It must still be written behind an interface so socket transport can
arrive later without changing tools.

Rules:

- Put bridge behavior behind a `BridgeClient` interface.
- Implement the file bridge as the first concrete client.
- Keep socket bridge code out of the MVP unless the file bridge blocks real
  workflows.
- Use JSON for request and response files.
- Include request IDs in every file.
- Use one response file per request.
- Clean up completed request and response files.
- Ignore stale files from prior sessions.
- Time out bridge calls with a structured error.
- Keep bridge directory configurable through settings.

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
- Keep raw ReaScript tools disabled by default.
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

Deferred profiles:

- `mixing`.
- `rendering`.
- `advanced`.
- `raw-reascript`.

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
- Cache project snapshots and invalidate them after mutations.
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

Required log fields:

- Request ID.
- Tool name.
- Bridge command name.
- Active profile.
- Capability state.
- Target object IDs.
- Undo label for mutating commands.
- Duration.
- Result status.
- Error code.

Debug mode can include larger payloads. Default logs must avoid full MIDI note
lists, waveform peaks, and complete project dumps.

## Configuration rules

Configuration must be explicit, local, and easy to diagnose at startup.

Required settings:

- `REAPER_MCP_BRIDGE_DIR`.
- `REAPER_MCP_PROFILE`.
- `REAPER_MCP_LOG_LEVEL`.
- `REAPER_MCP_ALLOWED_RENDER_ROOTS`.
- `REAPER_MCP_TRANSPORT`.
- `REAPER_MCP_BRIDGE_TIMEOUT_SECONDS`.

Startup diagnostics must report:

- The active profile.
- The bridge directory.
- The selected transport.
- Whether the bridge health check passes.
- The configured allowed render roots.

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
- Never claim a render finished unless REAPER returns a completed result.
- Never expose raw ReaScript access without capability enablement.

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

Use this document as the review checklist for remaining render work. Keep render
paths root-guarded, result shapes stable, and REAPER bridge behavior verified
before expanding render modes. Full-project rendering requires REAPER background
rendering to be enabled and explicitly confirmed through
`REAPER_MCP_RENDER_BACKGROUND_CONFIRMED=true`; a completed result must include
stable output metadata plus render-setting and dirty-state restoration evidence.
Keep the `production` profile free of experimental render tools until that
evidence exists. Profile changes must filter both discovery and calls so a
client cannot invoke a hidden tool from stale discovery state.
