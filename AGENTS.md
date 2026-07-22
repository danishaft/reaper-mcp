# Project agent instructions

These instructions apply to this repository. Use them together with the product
and engineering documents in `docs/` before making implementation decisions.

## Source of truth

Read these documents before starting non-trivial work:

- `docs/reaper-mcp-product-architecture-spec.md`
- `docs/reaper-mcp-implementation-roadmap.md`
- `docs/reaper-mcp-engineering-standards.md`

Keep these documents aligned with implementation decisions. If the code proves
that a documented decision is wrong, update the document in the same change.

## Engineering standard

Build this project with first-principles clean code. Prefer small, coherent
modules with clear responsibilities over patchwork fixes or clever abstractions.

Rules:

- Keep MCP tools thin.
- Put workflow logic in services.
- Put validation and safety checks before bridge execution.
- Keep bridge transport behind an interface.
- Use stable REAPER GUIDs instead of indices for identity.
- Return structured errors and stable result shapes.
- Keep mutating REAPER commands undoable.
- Avoid spaghetti code, hidden side effects, and broad global state.
- Avoid overengineering and abstractions that don't remove real complexity.
- Fix root causes instead of layering local patches over broken design.

## Python rules

Use clean, typed Python for the MCP server and supporting logic.

Rules:

- Use Python `>=3.11`.
- Use `uv` for package and environment workflows.
- Use `pydantic v2` for external schemas, config, and bridge payloads.
- Use `pytest` for tests.
- Use `ruff` for linting and formatting.
- Type-hint public functions and methods.
- Keep constructors free of filesystem, network, or REAPER side effects.
- Use comments sparingly for intent, invariants, or non-obvious constraints.

## JavaScript and TypeScript rules

Use JavaScript or TypeScript only when the project needs it for tooling,
examples, UI, or integration scripts.

Rules:

- Use Biome for JavaScript and TypeScript linting and formatting.
- Use JSDoc for public exported functions, integration examples, and scripts
  that users are expected to edit.
- Keep comments useful and current.
- Prefer explicit data shapes and narrow modules.
- Do not introduce a separate JS toolchain when Python can solve the problem
  cleanly.

## Documentation rules

Documentation must stay practical and implementation-aligned.

Rules:

- Keep docs concise and decision-oriented.
- Update docs when architecture, setup, or tool behavior changes.
- Use diagrams as code for architecture where useful.
- Avoid creating new docs unless they reduce real ambiguity.

## Review checklist

Before finishing a change, verify that it satisfies this checklist.

- The change follows the documented architecture.
- The change keeps responsibilities separated.
- The change has the narrowest useful test or check.
- The change does not add avoidable dependencies.
- The change does not expand the default tool surface without profile review.
- The change does not trade long-term clarity for a quick patch.
