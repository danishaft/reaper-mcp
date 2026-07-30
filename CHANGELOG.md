# Changelog

This file records user-visible changes to REAPER MCP.

## Unreleased

- Add an undoable, source-guarded media-item track move that preserves and
  verifies timeline position and take offsets for vocal comping workflows.
- Add undoable, GUID-based reference-track routing that bypasses master-bus FX
  through a verified direct stereo hardware send.
- Add a project-local Codex workflow for evidence-led vocal mixing, reference
  checks, human approval, isolated mastering, and delivery.
- Add GitHub CI coverage for Python 3.11 through 3.13 on Linux, macOS, and
  Windows.
- Add tagged source and wheel release artifacts.

## 0.1.0 - 2026-07-27

- Add MCP, CLI, and loopback REST interfaces over one shared service layer.
- Add producer workflows for tracks, media, MIDI, FX, routing, automation,
  arrangement, tempo, templates, analysis, and rendering.
- Add stable REAPER identity handling, guarded mutations, named undo steps,
  path allowlists, profiles, and structured errors.
- Verify the core workflow and isolated project render path on Linux with
  REAPER 7.66.
