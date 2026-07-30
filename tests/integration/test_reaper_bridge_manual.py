"""Opt-in acceptance tests against a running isolated REAPER instance."""

from __future__ import annotations

import asyncio
import json
import math
import os
import struct
import time
import wave
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from reaper_mcp.bridge.file_bridge import FileBridgeClient
from reaper_mcp.services.arrangement_service import ArrangementService
from reaper_mcp.services.audio_analysis_service import AudioAnalysisService
from reaper_mcp.services.audio_measurement_backend import FfmpegEbur128Backend
from reaper_mcp.services.audio_measurement_service import AudioMeasurementService
from reaper_mcp.services.automation_service import AutomationService
from reaper_mcp.services.batch_service import BatchService
from reaper_mcp.services.diagnostics_service import DiagnosticsService
from reaper_mcp.services.freeze_service import FreezeService
from reaper_mcp.services.fx_service import FxService
from reaper_mcp.services.health_service import HealthService
from reaper_mcp.services.mastering_plan_service import MasteringPlanService
from reaper_mcp.services.mastering_session_service import MasteringSessionService
from reaper_mcp.services.media_service import MediaService
from reaper_mcp.services.midi_controller_service import MidiControllerService
from reaper_mcp.services.midi_transform_service import MidiTransformService
from reaper_mcp.services.navigation_service import NavigationService
from reaper_mcp.services.project_controls_service import ProjectControlsService
from reaper_mcp.services.project_service import ProjectService
from reaper_mcp.services.routing_service import RoutingService
from reaper_mcp.services.take_service import TakeService
from reaper_mcp.services.template_service import TemplateService
from reaper_mcp.services.tempo_map_service import TempoMapService
from reaper_mcp.services.tempo_service import TempoService
from reaper_mcp.services.transport_service import TransportService
from reaper_mcp.services.vocal_tuning_service import VocalTuningService
from reaper_mcp.services.workflow_service import WorkflowService

LIVE_TEST_ENABLED = os.getenv("REAPER_MCP_LIVE_TEST") == "1"

pytestmark = pytest.mark.skipif(
    not LIVE_TEST_ENABLED,
    reason="Set REAPER_MCP_LIVE_TEST=1 for isolated live REAPER acceptance.",
)


def _bridge_client(
    bridge_dir: Path,
    timeout_seconds: float = 5.0,
) -> FileBridgeClient:
    return FileBridgeClient(
        bridge_dir=bridge_dir,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=0.05,
        stale_after_seconds=300.0,
    )


def _run_probe(bridge_dir: Path, command: str = "status") -> dict[str, Any]:
    command_path = bridge_dir / "acceptance-probe-command.txt"
    output_path = bridge_dir / "acceptance-probe.json"
    request_id = str(uuid4())

    output_path.unlink(missing_ok=True)
    command_path.write_text(f"{request_id}|{command}", encoding="utf-8")

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if output_path.exists():
            result = json.loads(output_path.read_text(encoding="utf-8"))
            if result.get("request_id") != request_id:
                time.sleep(0.05)
                continue
            if result.get("error"):
                raise AssertionError(result["error"])
            return result
        time.sleep(0.05)
    raise AssertionError(
        "Timed out waiting for the deferred REAPER acceptance probe. "
        "Start REAPER with both bridge and probe scripts."
    )


def _track_by_guid(tracks: dict[str, Any], track_guid: str) -> dict[str, Any]:
    return next(track for track in tracks["tracks"] if track["guid"] == track_guid)


def _fx_identity(fx: dict[str, Any]) -> dict[str, Any]:
    return {
        "track_guid": fx["track_guid"],
        "index": fx["index"],
        "expected_identity": fx["identity"],
        "expected_name": fx["name"],
        "expected_guid": fx["guid"],
    }


def _take_fx_identity(fx: dict[str, Any]) -> dict[str, Any]:
    return {
        "take_guid": fx["take_guid"],
        "index": fx["index"],
        "expected_name": fx["name"],
        "expected_guid": fx["guid"],
    }


def _midi_note(
    beat: float,
    pitch: int,
    velocity: int = 96,
    length_beats: float = 1.0,
) -> dict[str, Any]:
    return {
        "start": {"measure": 1, "beat": beat},
        "length": {"beats": length_beats},
        "pitch": pitch,
        "velocity": velocity,
        "channel": 0,
        "selected": False,
        "muted": False,
    }


def _midi_identity(note: dict[str, Any]) -> dict[str, Any]:
    return {
        "index": note["index"],
        "expected_fingerprint": note["fingerprint"],
    }


def _write_test_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(44_100)
        output.writeframes(b"\0\0" * 4_410)


@pytest.mark.asyncio
async def test_reaper_vocal_tuning_split_pitch_and_undo(tmp_path: Path) -> None:
    """Verify approved segment tuning, observed pitch, and one-step undo."""

    bridge_dir = Path(os.environ["REAPER_MCP_BRIDGE_DIR"])
    bridge = _bridge_client(bridge_dir)
    project = ProjectService(bridge)
    media = MediaService(bridge, allowed_media_source_roots=[tmp_path])
    takes = TakeService(bridge)
    tuning = VocalTuningService(
        bridge,
        project,
        media,
        takes,
        FxService(bridge),
    )

    source_path = tmp_path / "vocal.wav"
    _write_test_wav(source_path)
    created_track = await project.create_track(name="Tuning Acceptance")
    assert created_track["ok"] is True
    track_guid = created_track["track"]["guid"]
    inserted = await media.insert_audio_item(track_guid, str(source_path))
    assert inserted["ok"] is True
    item = inserted["item"]
    item_guid = item["guid"]
    take_guid = item["active_take"]["guid"]
    start_seconds = item["position_seconds"] + 0.02
    end_seconds = item["position_seconds"] + 0.06

    preview = await tuning.preview_plan(
        "reaper_take_pitch",
        "transparent_repair",
        track_guid,
        item_guid,
        take_guid,
        [
            {
                "segment_id": "acceptance-note",
                "start_seconds": start_seconds,
                "end_seconds": end_seconds,
                "correction_cents": -25.0,
                "preserve_vibrato": True,
                "rationale": "Verify the stable take-pitch provider",
            }
        ],
    )
    assert preview["ok"] is True
    applied = await tuning.apply_plan(
        preview["plan"],
        preview["plan"]["approval_hash"],
    )
    assert applied["ok"] is True
    assert applied["application"]["applied_correction_count"] == 1
    assert applied["application"]["segments"][0]["result_pitch_semitones"] == (
        pytest.approx(-0.25)
    )
    assert _run_probe(bridge_dir)["undo_label"] == ("Apply approved vocal tuning plan")
    assert (await media.list_media_items())["item_count"] == 3

    _run_probe(bridge_dir, "undo")
    restored = await media.list_media_items()
    assert restored["item_count"] == 1
    restored_takes = await takes.list_item_takes(restored["items"][0]["guid"])
    assert restored_takes["takes"][0]["pitch_semitones"] == pytest.approx(0.0)


def _write_mastering_test_wav(path: Path) -> None:
    sample_rate = 48_000
    with wave.open(str(path), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(
            b"".join(
                struct.pack(
                    "<hh",
                    round(math.sin(2 * math.pi * 997 * frame / sample_rate) * 8192),
                    round(math.sin(2 * math.pi * 997 * frame / sample_rate) * 8192),
                )
                for frame in range(sample_rate * 4)
            )
        )


async def _send_raw_envelope(
    bridge_dir: Path,
    payload: dict[str, Any],
) -> dict[str, Any]:
    request_id = str(payload.get("id") or uuid4())
    payload["id"] = request_id
    request_path = bridge_dir / "requests" / f"{request_id}.json"
    response_path = bridge_dir / "responses" / f"{request_id}.json"
    request_path.write_text(json.dumps(payload), encoding="utf-8")

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if response_path.exists():
            response = json.loads(response_path.read_text(encoding="utf-8"))
            response_path.unlink()
            return response
        await asyncio.sleep(0.05)
    raise AssertionError("Timed out waiting for a raw bridge response.")


@pytest.mark.asyncio
async def test_reaper_core_acceptance_diagnostics_tracks_transport() -> None:
    """Verify diagnostics, track lifecycle, undo, and transport safety."""

    bridge_dir = Path(os.environ["REAPER_MCP_BRIDGE_DIR"])
    bridge = _bridge_client(bridge_dir)
    health = HealthService(bridge)
    diagnostics = DiagnosticsService(bridge)
    project = ProjectService(bridge)
    transport = TransportService(bridge)
    media = MediaService(bridge)

    assert (await health.check())["ok"] is True
    assert (await diagnostics.get_reaper_version())["ok"] is True
    assert (await diagnostics.get_project_info())["ok"] is True
    assert (await diagnostics.get_bridge_status())["ok"] is True

    initial_tracks = await project.list_tracks()
    assert initial_tracks["ok"] is True
    assert initial_tracks["track_count"] == 0
    assert (await project.get_project_snapshot())["ok"] is True

    created = await project.create_track(name="Acceptance Track", color=0x336699)
    assert created["ok"] is True
    track_guid = created["track"]["guid"]
    assert _run_probe(bridge_dir)["undo_label"] == "Create track: Acceptance Track"

    _run_probe(bridge_dir, "undo")
    assert (await project.list_tracks())["track_count"] == 0
    _run_probe(bridge_dir, "redo")
    tracks = await project.list_tracks()
    assert _track_by_guid(tracks, track_guid)["name"] == "Acceptance Track"

    renamed = await project.rename_track(track_guid, "Verified Track")
    assert renamed["ok"] is True
    assert _run_probe(bridge_dir)["undo_label"] == "Rename track: Verified Track"
    _run_probe(bridge_dir, "undo")
    assert _track_by_guid(await project.list_tracks(), track_guid)["name"] == (
        "Acceptance Track"
    )
    _run_probe(bridge_dir, "redo")

    colored = await project.set_track_color(track_guid, 0x224466)
    assert colored["ok"] is True
    assert _run_probe(bridge_dir)["undo_label"] == "Set track color"
    updated_color = _track_by_guid(await project.list_tracks(), track_guid)["color"]
    assert updated_color != 0
    _run_probe(bridge_dir, "undo")
    assert _track_by_guid(await project.list_tracks(), track_guid)["color"] != (
        updated_color
    )
    _run_probe(bridge_dir, "redo")
    assert _track_by_guid(await project.list_tracks(), track_guid)["color"] == (
        updated_color
    )

    muted = await project.set_track_mute(track_guid, True)
    assert muted["ok"] is True
    assert _run_probe(bridge_dir)["undo_label"] == "Set track mute"
    assert _track_by_guid(await project.list_tracks(), track_guid)["mute"] is True
    _run_probe(bridge_dir, "undo")
    assert _track_by_guid(await project.list_tracks(), track_guid)["mute"] is False
    _run_probe(bridge_dir, "redo")

    soloed = await project.set_track_solo(track_guid, True)
    assert soloed["ok"] is True
    assert _run_probe(bridge_dir)["undo_label"] == "Set track solo"
    assert _track_by_guid(await project.list_tracks(), track_guid)["solo"] is True
    _run_probe(bridge_dir, "undo")
    assert _track_by_guid(await project.list_tracks(), track_guid)["solo"] is False
    _run_probe(bridge_dir, "redo")

    armed = await project.set_track_arm(track_guid, True)
    assert armed["ok"] is True
    assert _run_probe(bridge_dir)["undo_label"] == "Set track record arm"
    assert _track_by_guid(await project.list_tracks(), track_guid)["armed"] is True
    _run_probe(bridge_dir, "undo")
    assert _track_by_guid(await project.list_tracks(), track_guid)["armed"] is False
    _run_probe(bridge_dir, "redo")

    volume = await project.set_track_volume(track_guid, 0.5)
    assert volume["ok"] is True
    assert volume["track"]["volume"] == pytest.approx(0.5)
    assert _run_probe(bridge_dir)["undo_label"] == "Set track volume"
    _run_probe(bridge_dir, "undo")
    assert _track_by_guid(await project.list_tracks(), track_guid)[
        "volume"
    ] != pytest.approx(0.5)
    _run_probe(bridge_dir, "redo")

    panned = await project.set_track_pan(track_guid, -0.25)
    assert panned["ok"] is True
    assert panned["track"]["pan"] == pytest.approx(-0.25)
    assert _run_probe(bridge_dir)["undo_label"] == "Set track pan"

    original_master = (await project.get_master_track())["master_track"]
    master_volume = await project.set_master_volume(0.75)
    assert master_volume["master_track"]["volume"] == pytest.approx(0.75)
    assert _run_probe(bridge_dir)["undo_label"] == "Set master volume"
    _run_probe(bridge_dir, "undo")
    assert (await project.get_master_track())["master_track"][
        "volume"
    ] == pytest.approx(original_master["volume"])
    _run_probe(bridge_dir, "redo")

    master_pan = await project.set_master_pan(0.2)
    assert master_pan["master_track"]["pan"] == pytest.approx(0.2)
    assert _run_probe(bridge_dir)["undo_label"] == "Set master pan"
    master_mute = await project.set_master_mute(True)
    assert master_mute["master_track"]["mute"] is True
    assert _run_probe(bridge_dir)["undo_label"] == "Set master mute"
    _run_probe(bridge_dir, "undo")
    assert (await project.get_master_track())["master_track"]["mute"] is False
    _run_probe(bridge_dir, "redo")

    await project.set_master_volume(original_master["volume"])
    await project.set_master_pan(original_master["pan"])
    await project.set_master_mute(original_master["mute"])
    undo_label_before_recording = _run_probe(bridge_dir)["undo_label"]

    played = await transport.play()
    assert played["ok"] is True
    assert played["transport"]["playing"] is True

    paused = await transport.pause()
    assert paused["ok"] is True
    assert paused["transport"]["paused"] is True
    assert (await transport.stop())["ok"] is True

    recording = await transport.record()
    assert recording["ok"] is True
    assert recording["transport"]["recording"] is True
    await asyncio.sleep(0.25)

    guarded_stop = await transport.stop()
    assert guarded_stop["ok"] is False
    assert guarded_stop["error"]["code"] == ("recording_stop_requires_stop_recording")

    stopped_recording = await transport.stop_recording()
    assert stopped_recording["ok"] is True
    assert stopped_recording["transport"]["recording"] is False
    assert stopped_recording["may_create_media_items"] is True
    recorded_media = await media.list_media_items()
    assert recorded_media["ok"] is True
    stop_probe = _run_probe(bridge_dir)
    if recorded_media["item_count"] > 0:
        assert stop_probe["undo_label"] == "Stop recording"
    else:
        # REAPER omits empty undo points when recording creates no project media.
        assert stop_probe["undo_label"] == undo_label_before_recording

    deleted = await project.delete_track(track_guid)
    assert deleted["ok"] is True
    assert _run_probe(bridge_dir)["undo_label"] == "Delete track"
    assert (await project.list_tracks())["track_count"] == 0

    _run_probe(bridge_dir, "undo")
    restored_tracks = await project.list_tracks()
    assert _track_by_guid(restored_tracks, track_guid)["name"] == "Verified Track"
    _run_probe(bridge_dir, "redo")
    assert (await project.list_tracks())["track_count"] == 0


@pytest.mark.asyncio
async def test_reaper_bridge_rejects_invalid_envelope_and_recovers() -> None:
    """Verify invalid envelopes, deterministic timeout, and bridge recovery."""

    bridge_dir = Path(os.environ["REAPER_MCP_BRIDGE_DIR"])
    invalid = await _send_raw_envelope(
        bridge_dir,
        {"args": {}, "options": {"mutates_project": False}},
    )
    assert invalid["ok"] is False
    assert invalid["error"]["code"] == "invalid_command_envelope"

    timeout_bridge = _bridge_client(bridge_dir, timeout_seconds=0.000001)
    timed_out = await timeout_bridge.execute("health_check")
    assert timed_out.ok is False
    assert timed_out.error is not None
    assert timed_out.error.code == "command_timeout"

    await asyncio.sleep(0.1)
    late_response = bridge_dir / "responses" / f"{timed_out.id}.json"
    late_response.unlink(missing_ok=True)
    assert (await HealthService(_bridge_client(bridge_dir)).check())["ok"] is True


@pytest.mark.asyncio
async def test_reaper_media_and_midi_acceptance() -> None:
    """Verify media identity, MIDI guards, source policy, and undo-redo."""

    bridge_dir = Path(os.environ["REAPER_MCP_BRIDGE_DIR"])
    bridge = _bridge_client(bridge_dir)
    project = ProjectService(bridge)
    media = MediaService(bridge, allowed_media_source_roots=[bridge_dir])
    midi_transform = MidiTransformService(bridge)
    blocked_media = MediaService(bridge)

    created_track = await project.create_track(name="Media Acceptance")
    assert created_track["ok"] is True
    track_guid = created_track["track"]["guid"]
    destination_track = await project.create_track(name="Media Destination")
    assert destination_track["ok"] is True
    destination_track_guid = destination_track["track"]["guid"]
    assert (await media.list_media_items())["item_count"] == 0

    created_item = await media.create_midi_item(
        track_guid,
        length_beats=8.0,
        name="Acceptance MIDI",
    )
    assert created_item["ok"] is True
    item_guid = created_item["item"]["guid"]
    take_guid = created_item["item"]["active_take"]["guid"]
    assert created_item["item"]["active_take"]["is_midi"] is True
    assert _run_probe(bridge_dir)["undo_label"] == ("Create MIDI item: Acceptance MIDI")

    _run_probe(bridge_dir, "undo")
    assert (await media.list_media_items())["item_count"] == 0
    _run_probe(bridge_dir, "redo")
    restored_items = await media.list_media_items()
    assert restored_items["items"][0]["guid"] == item_guid
    assert restored_items["items"][0]["active_take"]["guid"] == take_guid

    empty_notes = await media.get_midi_notes(take_guid)
    assert empty_notes["ok"] is True
    assert empty_notes["note_count"] == 0

    added_note = await media.add_midi_note(take_guid, _midi_note(1.0, 60))
    assert added_note["ok"] is True
    assert added_note["note_count"] == 1
    assert _run_probe(bridge_dir)["undo_label"] == "Add MIDI note"
    _run_probe(bridge_dir, "undo")
    assert (await media.get_midi_notes(take_guid))["note_count"] == 0
    _run_probe(bridge_dir, "redo")
    assert (await media.get_midi_notes(take_guid))["note_count"] == 1

    batch = await media.add_midi_notes(
        take_guid,
        [_midi_note(2.0, 64), _midi_note(3.0, 67)],
    )
    assert batch["ok"] is True
    assert batch["inserted_count"] == 2
    assert batch["note_count"] == 3
    assert _run_probe(bridge_dir)["undo_label"] == "Add 2 MIDI notes"
    _run_probe(bridge_dir, "undo")
    assert (await media.get_midi_notes(take_guid))["note_count"] == 1
    _run_probe(bridge_dir, "redo")

    notes_before_update = await media.get_midi_notes(take_guid)
    original_note = notes_before_update["notes"][0]
    updated = await media.update_midi_note(
        take_guid,
        original_note["index"],
        original_note["fingerprint"],
        _midi_note(1.0, 61, velocity=110),
    )
    assert updated["ok"] is True
    assert updated["updated_note"]["pitch"] == 61
    assert _run_probe(bridge_dir)["undo_label"] == "Update MIDI note"

    stale_update = await media.update_midi_note(
        take_guid,
        original_note["index"],
        original_note["fingerprint"],
        _midi_note(1.0, 62),
    )
    assert stale_update["ok"] is False
    assert stale_update["error"]["code"] == "midi_note_conflict"
    assert _run_probe(bridge_dir)["undo_label"] == "Update MIDI note"
    _run_probe(bridge_dir, "undo")
    assert (await media.get_midi_notes(take_guid))["notes"][0]["pitch"] == 60
    _run_probe(bridge_dir, "redo")

    notes_before_delete = await media.get_midi_notes(take_guid)
    note_to_delete = notes_before_delete["notes"][1]
    deleted = await media.delete_midi_notes(
        take_guid,
        [
            {
                "index": note_to_delete["index"],
                "expected_fingerprint": note_to_delete["fingerprint"],
            }
        ],
    )
    assert deleted["ok"] is True
    assert deleted["deleted_count"] == 1
    assert deleted["note_count"] == 2
    assert _run_probe(bridge_dir)["undo_label"] == "Delete 1 MIDI notes"
    _run_probe(bridge_dir, "undo")
    assert (await media.get_midi_notes(take_guid))["note_count"] == 3
    _run_probe(bridge_dir, "redo")

    transform_notes = (await media.get_midi_notes(take_guid))["notes"]
    first_note_identity = _midi_identity(transform_notes[0])
    transposed = await midi_transform.transpose_midi_notes(
        take_guid,
        [first_note_identity],
        semitones=2,
    )
    assert transposed["ok"] is True
    assert transposed["transformed_count"] == 1
    assert transposed["notes"][0]["pitch"] == 63
    assert _run_probe(bridge_dir)["undo_label"] == "Transpose MIDI notes"

    stale_nudge = await midi_transform.nudge_midi_notes(
        take_guid,
        [first_note_identity],
        offset_beats=0.25,
    )
    assert stale_nudge["ok"] is False
    assert stale_nudge["error"]["code"] == "midi_note_conflict"
    assert _run_probe(bridge_dir)["undo_label"] == "Transpose MIDI notes"

    current_first_note = transposed["notes"][0]
    out_of_range = await midi_transform.transpose_midi_notes(
        take_guid,
        [_midi_identity(current_first_note)],
        semitones=100,
    )
    assert out_of_range["ok"] is False
    assert out_of_range["error"]["code"] == "invalid_midi_note_request"
    assert _run_probe(bridge_dir)["undo_label"] == "Transpose MIDI notes"

    _run_probe(bridge_dir, "undo")
    assert (await media.get_midi_notes(take_guid))["notes"][0]["pitch"] == 61
    _run_probe(bridge_dir, "redo")
    assert (await media.get_midi_notes(take_guid))["notes"][0]["pitch"] == 63

    current_notes = (await media.get_midi_notes(take_guid))["notes"]
    second_note = current_notes[1]
    nudged = await midi_transform.nudge_midi_notes(
        take_guid,
        [_midi_identity(second_note)],
        offset_beats=0.1,
    )
    assert nudged["ok"] is True
    nudged_note = next(note for note in nudged["notes"] if note["pitch"] == 67)
    assert nudged_note["start_qn"] == pytest.approx(2.1)
    assert _run_probe(bridge_dir)["undo_label"] == "Nudge MIDI notes"

    quantized = await midi_transform.quantize_midi_notes(
        take_guid,
        [_midi_identity(nudged_note)],
        grid_beats=0.25,
        strength=1.0,
        swing=0.0,
    )
    assert quantized["ok"] is True
    quantized_note = next(note for note in quantized["notes"] if note["pitch"] == 67)
    assert quantized_note["start_qn"] == pytest.approx(2.0)
    assert _run_probe(bridge_dir)["undo_label"] == "Quantize MIDI notes"

    current_notes = quantized["notes"]
    off_scale_note = next(note for note in current_notes if note["pitch"] == 63)
    snapped = await midi_transform.snap_midi_notes_to_scale(
        take_guid,
        [_midi_identity(off_scale_note)],
        root_pitch_class=0,
        scale="major",
        direction="nearest",
    )
    assert snapped["ok"] is True
    assert any(note["pitch"] == 62 for note in snapped["notes"])
    assert _run_probe(bridge_dir)["undo_label"] == "Snap MIDI notes to scale"

    shaped = await midi_transform.shape_midi_note_velocities(
        take_guid,
        [_midi_identity(note) for note in snapped["notes"]],
        factor=0.5,
        offset=0,
    )
    assert shaped["ok"] is True
    assert shaped["transformed_count"] == 2
    assert max(note["velocity"] for note in shaped["notes"]) <= 55
    assert _run_probe(bridge_dir)["undo_label"] == "Shape MIDI note velocities"

    humanize_identities = [_midi_identity(note) for note in shaped["notes"]]
    humanized = await midi_transform.humanize_midi_notes(
        take_guid,
        humanize_identities,
        max_timing_offset_beats=0,
        max_velocity_offset=8,
        seed=42,
    )
    assert humanized["ok"] is True
    first_humanize_state = [
        (note["pitch"], note["velocity"], note["start_qn"], note["end_qn"])
        for note in humanized["notes"]
    ]
    assert _run_probe(bridge_dir)["undo_label"] == "Humanize MIDI notes"

    _run_probe(bridge_dir, "undo")
    restored_for_humanize = (await media.get_midi_notes(take_guid))["notes"]
    repeated_humanize = await midi_transform.humanize_midi_notes(
        take_guid,
        [_midi_identity(note) for note in restored_for_humanize],
        max_timing_offset_beats=0,
        max_velocity_offset=8,
        seed=42,
    )
    assert repeated_humanize["ok"] is True
    repeated_humanize_state = [
        (note["pitch"], note["velocity"], note["start_qn"], note["end_qn"])
        for note in repeated_humanize["notes"]
    ]
    assert repeated_humanize_state == first_humanize_state

    overlapping = await media.add_midi_note(
        take_guid,
        _midi_note(1.5, 62, velocity=80, length_beats=1.0),
    )
    pitch_62_notes = [note for note in overlapping["notes"] if note["pitch"] == 62]
    assert len(pitch_62_notes) == 2
    trimmed = await midi_transform.remove_midi_note_overlaps(
        take_guid,
        [_midi_identity(note) for note in pitch_62_notes],
    )
    assert trimmed["ok"] is True
    trimmed_pitch_62 = [note for note in trimmed["notes"] if note["pitch"] == 62]
    assert trimmed_pitch_62[0]["end_qn"] == pytest.approx(0.5)
    assert _run_probe(bridge_dir)["undo_label"] == "Remove MIDI note overlaps"
    _run_probe(bridge_dir, "undo")
    restored_pitch_62 = [
        note
        for note in (await media.get_midi_notes(take_guid))["notes"]
        if note["pitch"] == 62
    ]
    assert restored_pitch_62[0]["end_qn"] == pytest.approx(1.0)
    _run_probe(bridge_dir, "redo")

    duplicate_onset = await media.add_midi_notes(
        take_guid,
        [_midi_note(1.5, 62, velocity=70, length_beats=0.5)],
    )
    assert duplicate_onset["ok"] is True, duplicate_onset
    assert duplicate_onset["inserted_count"] == 1
    assert len(duplicate_onset["inserted_notes"]) == 1
    exact_duplicate = await media.add_midi_note(
        take_guid,
        _midi_note(1.5, 62, velocity=70, length_beats=0.5),
    )
    assert exact_duplicate["ok"] is False
    assert exact_duplicate["error"]["code"] == "invalid_midi_note_request"
    same_onset_notes = [
        note
        for note in duplicate_onset["notes"]
        if note["pitch"] == 62 and note["start_qn"] == pytest.approx(0.5)
    ]
    ambiguous_overlap = await midi_transform.remove_midi_note_overlaps(
        take_guid,
        [_midi_identity(note) for note in same_onset_notes],
    )
    assert ambiguous_overlap["ok"] is False
    assert ambiguous_overlap["error"]["code"] == "invalid_midi_note_request"

    audio_path = bridge_dir / "acceptance-source.wav"
    _write_test_wav(audio_path)
    blocked = await blocked_media.insert_audio_item(track_guid, str(audio_path))
    assert blocked["ok"] is False
    assert blocked["error"]["code"] == "media_source_not_allowed"

    inserted_audio = await media.insert_audio_item(
        track_guid,
        str(audio_path),
        measure=2,
        name="Acceptance Audio",
    )
    assert inserted_audio["ok"] is True
    audio_item_guid = inserted_audio["item"]["guid"]
    assert inserted_audio["item"]["active_take"]["is_midi"] is False
    assert _run_probe(bridge_dir)["undo_label"] == "Insert audio item"
    _run_probe(bridge_dir, "undo")
    item_guids = {item["guid"] for item in (await media.list_media_items())["items"]}
    assert audio_item_guid not in item_guids
    _run_probe(bridge_dir, "redo")
    item_guids = {item["guid"] for item in (await media.list_media_items())["items"]}
    assert audio_item_guid in item_guids

    moved = await media.move_media_item(audio_item_guid, measure=3, beat=1.0)
    assert moved["ok"] is True
    assert moved["item"]["start_qn"] == pytest.approx(8.0)
    assert _run_probe(bridge_dir)["undo_label"] == "Move media item"
    _run_probe(bridge_dir, "undo")
    original_audio = next(
        item
        for item in (await media.list_media_items())["items"]
        if item["guid"] == audio_item_guid
    )
    assert original_audio["start_qn"] == pytest.approx(4.0)
    _run_probe(bridge_dir, "redo")

    moved_to_track = await media.move_media_item_to_track(
        audio_item_guid,
        destination_track_guid,
        track_guid,
    )
    assert moved_to_track["ok"] is True
    assert moved_to_track["item"]["track_guid"] == destination_track_guid
    assert moved_to_track["item"]["start_qn"] == pytest.approx(8.0)
    assert moved_to_track["position_preserved"] is True
    assert moved_to_track["take_offsets_preserved"] is True
    assert _run_probe(bridge_dir)["undo_label"] == "Move media item to track"
    _run_probe(bridge_dir, "undo")
    restored_audio = next(
        item
        for item in (await media.list_media_items())["items"]
        if item["guid"] == audio_item_guid
    )
    assert restored_audio["track_guid"] == track_guid
    _run_probe(bridge_dir, "redo")

    stale_source = await media.move_media_item_to_track(
        audio_item_guid,
        destination_track_guid,
        track_guid,
    )
    assert stale_source["ok"] is False
    assert stale_source["error"]["code"] == "invalid_media_item_request"

    moved_back = await media.move_media_item_to_track(
        audio_item_guid,
        track_guid,
        destination_track_guid,
    )
    assert moved_back["ok"] is True
    assert moved_back["item"]["track_guid"] == track_guid

    resized = await media.resize_media_item(audio_item_guid, length_beats=2.0)
    assert resized["ok"] is True
    assert resized["item"]["end_qn"] - resized["item"]["start_qn"] == pytest.approx(2.0)
    assert _run_probe(bridge_dir)["undo_label"] == "Resize media item"

    muted = await media.set_media_item_mute(audio_item_guid, True)
    assert muted["ok"] is True
    assert muted["item"]["muted"] is True
    assert _run_probe(bridge_dir)["undo_label"] == "Set media item mute"
    _run_probe(bridge_dir, "undo")
    restored_audio = next(
        item
        for item in (await media.list_media_items())["items"]
        if item["guid"] == audio_item_guid
    )
    assert restored_audio["muted"] is False
    _run_probe(bridge_dir, "redo")

    gained = await media.set_media_item_gain(audio_item_guid, 0.5)
    assert gained["ok"] is True
    assert gained["item"]["gain"] == pytest.approx(0.5)
    assert _run_probe(bridge_dir)["undo_label"] == "Set media item gain"

    faded_in = await media.set_media_item_fade_in(audio_item_guid, 0.1)
    assert faded_in["ok"] is True
    assert faded_in["item"]["fade_in_seconds"] == pytest.approx(0.1)
    assert _run_probe(bridge_dir)["undo_label"] == "Set media item fade in"

    faded_out = await media.set_media_item_fade_out(audio_item_guid, 0.2)
    assert faded_out["ok"] is True
    assert faded_out["item"]["fade_out_seconds"] == pytest.approx(0.2)
    assert _run_probe(bridge_dir)["undo_label"] == "Set media item fade out"

    items_before_duplicate = await media.list_media_items()
    prior_selection = {
        item["guid"]: item["selected"] for item in items_before_duplicate["items"]
    }
    duplicated = await media.duplicate_media_item(audio_item_guid)
    assert duplicated["ok"] is True
    duplicate_guid = duplicated["item"]["guid"]
    assert duplicate_guid != audio_item_guid
    assert duplicated["selection_restored"] is True
    assert _run_probe(bridge_dir)["undo_label"] == "Duplicate media item"
    items_after_duplicate = await media.list_media_items()
    assert (
        items_after_duplicate["item_count"] == items_before_duplicate["item_count"] + 1
    )
    assert {
        item["guid"]: item["selected"]
        for item in items_after_duplicate["items"]
        if item["guid"] in prior_selection
    } == prior_selection
    _run_probe(bridge_dir, "undo")
    item_guids = {item["guid"] for item in (await media.list_media_items())["items"]}
    assert duplicate_guid not in item_guids
    _run_probe(bridge_dir, "redo")
    item_guids = {item["guid"] for item in (await media.list_media_items())["items"]}
    assert duplicate_guid in item_guids

    invalid_split = await media.split_media_item(audio_item_guid, measure=1, beat=1.0)
    assert invalid_split["ok"] is False
    assert invalid_split["error"]["code"] == "invalid_media_item_request"

    split = await media.split_media_item(audio_item_guid, measure=3, beat=2.0)
    assert split["ok"] is True
    right_item_guid = split["right_item"]["guid"]
    assert split["left_item"]["guid"] == audio_item_guid
    assert split["left_item"]["end_qn"] == pytest.approx(9.0)
    assert split["right_item"]["start_qn"] == pytest.approx(9.0)
    assert _run_probe(bridge_dir)["undo_label"] == "Split media item"
    _run_probe(bridge_dir, "undo")
    item_guids = {item["guid"] for item in (await media.list_media_items())["items"]}
    assert right_item_guid not in item_guids
    _run_probe(bridge_dir, "redo")
    item_guids = {item["guid"] for item in (await media.list_media_items())["items"]}
    assert right_item_guid in item_guids

    deleted_audio = await media.delete_media_item(audio_item_guid)
    assert deleted_audio["ok"] is True
    assert _run_probe(bridge_dir)["undo_label"] == "Delete media item"
    item_guids = {item["guid"] for item in (await media.list_media_items())["items"]}
    assert audio_item_guid not in item_guids
    _run_probe(bridge_dir, "undo")
    item_guids = {item["guid"] for item in (await media.list_media_items())["items"]}
    assert audio_item_guid in item_guids
    _run_probe(bridge_dir, "redo")

    assert (await project.delete_track(track_guid))["ok"] is True
    assert (await project.delete_track(destination_track_guid))["ok"] is True
    audio_path.unlink()


@pytest.mark.asyncio
async def test_reaper_track_routing_acceptance() -> None:
    """Verify guarded track sends, stale identity, and undo-redo."""

    bridge_dir = Path(os.environ["REAPER_MCP_BRIDGE_DIR"])
    bridge = _bridge_client(bridge_dir)
    project = ProjectService(bridge)
    routing = RoutingService(bridge)

    source = await project.create_track(name="Routing Source")
    destination = await project.create_track(name="Routing Bus")
    source_guid = source["track"]["guid"]
    destination_guid = destination["track"]["guid"]
    assert (await routing.list_track_sends(source_guid))["send_count"] == 0

    created = await routing.create_track_send(
        source_guid,
        destination_guid,
        volume=0.5,
        pan=-0.2,
    )
    assert created["ok"] is True
    assert created["send"]["destination_track_guid"] == destination_guid
    assert created["send"]["volume"] == pytest.approx(0.5)
    assert _run_probe(bridge_dir)["undo_label"] == "Create track send"
    _run_probe(bridge_dir, "undo")
    assert (await routing.list_track_sends(source_guid))["send_count"] == 0
    _run_probe(bridge_dir, "redo")

    current_send = (await routing.list_track_sends(source_guid))["sends"][0]
    stale = await routing.set_track_send(
        source_guid,
        current_send["index"],
        source_guid,
        volume=0.25,
    )
    assert stale["ok"] is False
    assert stale["error"]["code"] == "invalid_send_reference"

    updated = await routing.set_track_send(
        source_guid,
        current_send["index"],
        destination_guid,
        volume=0.25,
        pan=0.3,
        muted=True,
    )
    assert updated["ok"] is True
    assert updated["send"]["volume"] == pytest.approx(0.25)
    assert updated["send"]["pan"] == pytest.approx(0.3)
    assert updated["send"]["muted"] is True
    assert _run_probe(bridge_dir)["undo_label"] == "Set track send"
    _run_probe(bridge_dir, "undo")
    restored_send = (await routing.list_track_sends(source_guid))["sends"][0]
    assert restored_send["volume"] == pytest.approx(0.5)
    assert restored_send["muted"] is False
    _run_probe(bridge_dir, "redo")

    removed = await routing.remove_track_send(
        source_guid,
        current_send["index"],
        destination_guid,
    )
    assert removed["ok"] is True
    assert removed["send_count"] == 0
    assert _run_probe(bridge_dir)["undo_label"] == "Remove track send"
    _run_probe(bridge_dir, "undo")
    assert (await routing.list_track_sends(source_guid))["send_count"] == 1
    _run_probe(bridge_dir, "redo")

    reference = await project.create_track(name="Reference Routing")
    reference_guid = reference["track"]["guid"]
    configured = await routing.configure_reference_track(reference_guid)
    assert configured["ok"] is True
    assert configured["master_send_enabled"] is False
    assert configured["hardware_output"]["destination_channels"] == "1/2"
    assert configured["hardware_send_created"] is True
    assert _run_probe(bridge_dir)["undo_label"] == ("Configure reference track routing")
    _run_probe(bridge_dir, "undo")
    _run_probe(bridge_dir, "redo")

    assert (await project.delete_track(source_guid))["ok"] is True
    assert (await project.delete_track(destination_guid))["ok"] is True
    assert (await project.delete_track(reference_guid))["ok"] is True


@pytest.mark.asyncio
async def test_reaper_track_freeze_acceptance() -> None:
    """Verify freeze state, selection restoration, liveness, and undo-redo."""

    bridge_dir = Path(os.environ["REAPER_MCP_BRIDGE_DIR"])
    bridge = _bridge_client(bridge_dir, timeout_seconds=30.0)
    health = HealthService(bridge)
    project = ProjectService(bridge)
    media = MediaService(bridge, allowed_media_source_roots=[bridge_dir])
    freeze = FreezeService(bridge)

    source = await project.create_track(name="Freeze Source")
    sentinel = await project.create_track(name="Selection Sentinel")
    source_guid = source["track"]["guid"]
    sentinel_guid = sentinel["track"]["guid"]

    audio_path = bridge_dir / "freeze-source.wav"
    _write_test_wav(audio_path)
    inserted = await media.insert_audio_item(source_guid, str(audio_path))
    assert inserted["ok"] is True
    _run_probe(bridge_dir, "save_project")
    _run_probe(bridge_dir, f"select_track:{sentinel_guid}")

    tracks = await project.list_tracks()
    selected_guids = {track["guid"] for track in tracks["tracks"] if track["selected"]}
    assert selected_guids == {sentinel_guid}

    initial = await freeze.get_track_freeze_state(source_guid)
    assert initial["state"]["frozen"] is False
    not_frozen = await freeze.unfreeze_track(source_guid)
    assert not_frozen["ok"] is False
    assert not_frozen["error"]["code"] == "track_not_frozen"

    frozen = await freeze.freeze_track(source_guid)
    assert frozen["ok"] is True
    assert frozen["state"]["track_guid"] == source_guid
    assert frozen["state"]["frozen"] is True
    assert frozen["state"]["freeze_count"] >= 1
    assert frozen["selection_restored"] is True
    assert frozen["may_create_media_files"] is True
    assert _run_probe(bridge_dir)["undo_label"] == "Freeze track to stereo"
    assert (await health.check())["ok"] is True

    tracks = await project.list_tracks()
    selected_guids = {track["guid"] for track in tracks["tracks"] if track["selected"]}
    assert selected_guids == {sentinel_guid}

    already_frozen = await freeze.freeze_track(source_guid)
    assert already_frozen["ok"] is False
    assert already_frozen["error"]["code"] == "track_already_frozen"

    _run_probe(bridge_dir, "undo")
    assert (await freeze.get_track_freeze_state(source_guid))["state"][
        "frozen"
    ] is False
    _run_probe(bridge_dir, "redo")
    assert (await freeze.get_track_freeze_state(source_guid))["state"]["frozen"] is True

    unfrozen = await freeze.unfreeze_track(source_guid)
    assert unfrozen["ok"] is True
    assert unfrozen["state"]["frozen"] is False
    assert unfrozen["selection_restored"] is True
    assert unfrozen["may_create_media_files"] is False
    assert _run_probe(bridge_dir)["undo_label"] == "Unfreeze track"
    assert (await health.check())["ok"] is True

    _run_probe(bridge_dir, "undo")
    assert (await freeze.get_track_freeze_state(source_guid))["state"]["frozen"] is True
    _run_probe(bridge_dir, "redo")
    assert (await freeze.get_track_freeze_state(source_guid))["state"][
        "frozen"
    ] is False

    assert (await project.delete_track(source_guid))["ok"] is True
    assert (await project.delete_track(sentinel_guid))["ok"] is True
    audio_path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_reaper_fx_acceptance() -> None:
    """Verify stock FX discovery, guarded mutations, parameters, and undo."""

    bridge_dir = Path(os.environ["REAPER_MCP_BRIDGE_DIR"])
    bridge = _bridge_client(bridge_dir)
    project = ProjectService(bridge)
    fx_service = FxService(bridge)

    created_track = await project.create_track(name="FX Acceptance")
    track_guid = created_track["track"]["guid"]
    available = await fx_service.list_available_fx()
    assert available["ok"] is True
    stock_fx = next(fx for fx in available["fx"] if "reaeq" in fx["name"].casefold())

    assert (await fx_service.list_track_fx(track_guid))["fx_count"] == 0
    added = await fx_service.add_fx(track_guid, stock_fx["identifier"])
    assert added["ok"] is True
    assert added["fx_count"] == 1
    assert _run_probe(bridge_dir)["undo_label"] == (f"Add FX: {stock_fx['identifier']}")
    added_identity = added["added_fx"]["identity"]
    _run_probe(bridge_dir, "undo")
    assert (await fx_service.list_track_fx(track_guid))["fx_count"] == 0
    _run_probe(bridge_dir, "redo")
    restored_fx = (await fx_service.list_track_fx(track_guid))["fx"][0]
    assert restored_fx["identity"] == added_identity
    identity = _fx_identity(restored_fx)

    disabled = await fx_service.set_fx_enabled(identity, False)
    assert disabled["ok"] is True
    assert disabled["updated_fx"]["enabled"] is False
    assert _run_probe(bridge_dir)["undo_label"] == (
        f"Set FX enabled: {identity['expected_name']}"
    )
    _run_probe(bridge_dir, "undo")
    assert (await fx_service.list_track_fx(track_guid))["fx"][0]["enabled"] is True
    _run_probe(bridge_dir, "redo")

    parameters = await fx_service.get_fx_parameters(identity)
    assert parameters["ok"] is True
    assert parameters["parameter_count"] > 0
    parameter = parameters["parameters"][0]
    original_value = parameter["normalized_value"]
    new_value = 0.25 if original_value > 0.5 else 0.75
    changed = await fx_service.set_fx_parameter(identity, parameter["index"], new_value)
    assert changed["ok"] is True
    assert changed["updated_parameter"]["normalized_value"] == pytest.approx(new_value)
    assert _run_probe(bridge_dir)["undo_label"] == (
        f"Set FX parameter: {identity['expected_name']}"
    )
    _run_probe(bridge_dir, "undo")
    restored_parameter = await fx_service.get_fx_parameters(identity)
    assert restored_parameter["parameters"][0]["normalized_value"] == pytest.approx(
        original_value
    )
    _run_probe(bridge_dir, "redo")

    stale_identity = {**identity, "expected_name": f"{identity['expected_name']} stale"}
    stale = await fx_service.set_fx_enabled(stale_identity, True)
    assert stale["ok"] is False
    assert stale["error"]["code"] == "invalid_fx_reference"

    removed = await fx_service.remove_fx(identity)
    assert removed["ok"] is True
    assert removed["fx_count"] == 0
    assert _run_probe(bridge_dir)["undo_label"] == (
        f"Remove FX: {identity['expected_name']}"
    )
    _run_probe(bridge_dir, "undo")
    assert (await fx_service.list_track_fx(track_guid))["fx_count"] == 1
    _run_probe(bridge_dir, "redo")
    assert (await fx_service.list_track_fx(track_guid))["fx_count"] == 0
    assert (await project.delete_track(track_guid))["ok"] is True


@pytest.mark.asyncio
async def test_reaper_mastering_stock_fx_plan_acceptance() -> None:
    """Verify stock master FX and an approved plan against live REAPER."""

    bridge_dir = Path(os.environ["REAPER_MCP_BRIDGE_DIR"])
    bridge = _bridge_client(bridge_dir)
    project = ProjectService(bridge)
    fx_service = FxService(bridge)
    measurement_service = AudioMeasurementService(
        FfmpegEbur128Backend(),
        allowed_audio_roots=[bridge_dir],
    )
    session_service = MasteringSessionService(measurement_service, project)
    plan_service = MasteringPlanService(bridge, fx_service, project)

    master = (await project.get_master_track())["master_track"]
    master_guid = master["guid"]
    assert (await fx_service.list_track_fx(master_guid))["fx_count"] == 0

    available = (await fx_service.list_available_fx())["fx"]
    required_names = ("reaeq", "reacomp", "realimit")
    stock_fx = [
        next(item for item in available if name in item["name"].casefold())
        for name in required_names
    ]
    for expected_count, item in enumerate(stock_fx, start=1):
        added = await fx_service.add_fx(master_guid, item["identifier"])
        assert added["ok"] is True
        assert added["fx_count"] == expected_count
        assert _run_probe(bridge_dir)["undo_label"] == (f"Add FX: {item['identifier']}")

    chain = await fx_service.list_track_fx(master_guid)
    assert chain["fx_count"] == 3
    for required_name, fx in zip(required_names, chain["fx"], strict=True):
        assert required_name in fx["name"].casefold()
    for fx in chain["fx"]:
        parameters = await fx_service.get_fx_parameters(_fx_identity(fx))
        assert parameters["ok"] is True
        assert parameters["parameter_count"] > 0

    source_path = bridge_dir / "mastering-acceptance-source.wav"
    _write_mastering_test_wav(source_path)
    session_result = await session_service.create_session(
        str(source_path),
        "current_project",
        "Verify a guarded stock-FX mastering plan.",
        priorities=["Do not change the source file."],
    )
    assert session_result["ok"] is True

    target_fx = chain["fx"][0]
    target_identity = _fx_identity(target_fx)
    target_parameter = (await fx_service.get_fx_parameters(target_identity))[
        "parameters"
    ][0]
    original_value = target_parameter["normalized_value"]
    target_value = 0.25 if original_value > 0.5 else 0.75
    preview = await plan_service.preview_plan(
        session_result["session"],
        master_guid,
        [
            {
                "action": "set_parameter",
                "fx_identity": target_identity,
                "parameter_index": target_parameter["index"],
                "expected_parameter_name": target_parameter["name"],
                "normalized_value": target_value,
                "rationale": "Exercise the guarded mastering transaction.",
                "expected_effect": "Only the selected normalized parameter changes.",
            }
        ],
    )
    assert preview["ok"] is True
    applied = await plan_service.apply_plan(
        preview["plan"],
        preview["plan"]["approval_hash"],
    )
    assert applied["ok"] is True
    assert applied["application"]["applied_operation_count"] == 1
    assert _run_probe(bridge_dir)["undo_label"] == ("Apply approved mastering FX plan")

    _run_probe(bridge_dir, "undo")
    restored = await fx_service.get_fx_parameters(target_identity)
    restored_parameter = next(
        item
        for item in restored["parameters"]
        if item["index"] == target_parameter["index"]
    )
    assert restored_parameter["normalized_value"] == pytest.approx(original_value)

    for fx in reversed((await fx_service.list_track_fx(master_guid))["fx"]):
        assert (await fx_service.remove_fx(_fx_identity(fx)))["ok"] is True
    assert (await fx_service.list_track_fx(master_guid))["fx_count"] == 0
    source_path.unlink()


@pytest.mark.asyncio
async def test_reaper_arrangement_and_tempo_acceptance() -> None:
    """Verify arrangement guards, tempo policy, state reads, and undo-redo."""

    bridge_dir = Path(os.environ["REAPER_MCP_BRIDGE_DIR"])
    bridge = _bridge_client(bridge_dir)
    arrangement = ArrangementService(bridge)
    tempo = TempoService(bridge)

    assert (await arrangement.list_markers())["marker_count"] == 0
    marker_result = await arrangement.create_marker(2.0, name="Acceptance Marker")
    marker = marker_result["marker"]
    assert _run_probe(bridge_dir)["undo_label"] == ("Create marker: Acceptance Marker")
    assert (await arrangement.list_markers())["markers"] == [marker]
    stale_marker = await arrangement.delete_marker(
        marker["id"],
        expected_name="Stale Marker",
        expected_start_seconds=marker["start_seconds"],
    )
    assert stale_marker["ok"] is False
    assert stale_marker["error"]["code"] == "invalid_marker_reference"
    deleted_marker = await arrangement.delete_marker(
        marker["id"],
        expected_name=marker["name"],
        expected_start_seconds=marker["start_seconds"],
    )
    assert deleted_marker["ok"] is True
    assert _run_probe(bridge_dir)["undo_label"] == f"Delete marker: {marker['id']}"
    _run_probe(bridge_dir, "undo")
    assert (await arrangement.list_markers())["markers"] == [marker]
    _run_probe(bridge_dir, "redo")
    assert (await arrangement.list_markers())["marker_count"] == 0

    assert (await arrangement.list_regions())["region_count"] == 0
    region_result = await arrangement.create_region(
        4.0,
        8.0,
        name="Acceptance Region",
    )
    region = region_result["region"]
    assert _run_probe(bridge_dir)["undo_label"] == ("Create region: Acceptance Region")
    assert (await arrangement.list_regions())["regions"] == [region]
    stale_region = await arrangement.delete_region(
        region["id"],
        expected_name=region["name"],
        expected_start_seconds=region["start_seconds"],
        expected_end_seconds=region["end_seconds"] + 1.0,
    )
    assert stale_region["ok"] is False
    assert stale_region["error"]["code"] == "invalid_region_reference"
    deleted_region = await arrangement.delete_region(
        region["id"],
        expected_name=region["name"],
        expected_start_seconds=region["start_seconds"],
        expected_end_seconds=region["end_seconds"],
    )
    assert deleted_region["ok"] is True
    assert _run_probe(bridge_dir)["undo_label"] == f"Delete region: {region['id']}"
    _run_probe(bridge_dir, "undo")
    assert (await arrangement.list_regions())["regions"] == [region]
    _run_probe(bridge_dir, "redo")
    assert (await arrangement.list_regions())["region_count"] == 0

    original_tempo = (await tempo.get_tempo())["tempo"]["bpm"]
    original_signature = (await tempo.get_time_signature())["time_signature"]
    changed_tempo = await tempo.set_tempo(128.0)
    assert changed_tempo["tempo"]["bpm"] == pytest.approx(128.0)
    assert _run_probe(bridge_dir)["undo_label"] == "Set tempo: 128 BPM"
    _run_probe(bridge_dir, "undo")
    assert (await tempo.get_tempo())["tempo"]["bpm"] == pytest.approx(original_tempo)
    _run_probe(bridge_dir, "redo")

    invalid_signature = await tempo.set_time_signature(5, 7)
    assert invalid_signature["ok"] is False
    assert invalid_signature["error"]["code"] == "invalid_tempo_request"
    changed_signature = await tempo.set_time_signature(7, 8)
    assert changed_signature["time_signature"] == {"numerator": 7, "denominator": 8}
    assert _run_probe(bridge_dir)["undo_label"] == "Set time signature: 7/8"
    _run_probe(bridge_dir, "undo")
    assert (await tempo.get_time_signature())["time_signature"] == original_signature
    _run_probe(bridge_dir, "redo")
    assert (await tempo.get_time_signature())["time_signature"] == {
        "numerator": 7,
        "denominator": 8,
    }

    _run_probe(bridge_dir, "undo")
    _run_probe(bridge_dir, "undo")
    assert (await tempo.get_tempo())["tempo"]["bpm"] == pytest.approx(original_tempo)
    assert (await tempo.get_time_signature())["time_signature"] == original_signature


@pytest.mark.asyncio
async def test_reaper_song_starter_acceptance() -> None:
    """Verify one complete musical workflow, stable identities, and undo-redo."""

    bridge_dir = Path(os.environ["REAPER_MCP_BRIDGE_DIR"])
    bridge = _bridge_client(bridge_dir)
    arrangement = ArrangementService(bridge)
    media = MediaService(bridge)
    project = ProjectService(bridge)
    tempo = TempoService(bridge)
    workflow = WorkflowService(bridge)

    initial_signature = (await tempo.get_time_signature())["time_signature"]
    assert initial_signature == {"numerator": 4, "denominator": 4}
    assert (await project.list_tracks())["track_count"] == 0

    changed_signature = await tempo.set_time_signature(3, 4)
    assert changed_signature["ok"] is True
    blocked = await workflow.create_song_starter(name="Blocked Starter")
    assert blocked["ok"] is False
    assert blocked["error"]["code"] == "unsupported_workflow_time_signature"
    assert (await project.list_tracks())["track_count"] == 0
    _run_probe(bridge_dir, "undo")
    assert (await tempo.get_time_signature())["time_signature"] == initial_signature

    created = await workflow.create_song_starter(
        name="Acceptance Starter",
        start_measure=1,
        bars=8,
        root_note=60,
        mode="major",
    )
    assert created["ok"] is True
    assert created["selection_restored"] is True
    assert created["total_note_count"] == 184
    assert _run_probe(bridge_dir)["undo_label"] == (
        "Create song starter: Acceptance Starter"
    )

    expected_counts = {"drums": 96, "bass": 32, "chords": 24, "lead": 32}
    assert {part["role"]: part["note_count"] for part in created["parts"]} == (
        expected_counts
    )
    track_guids = {part["track"]["guid"] for part in created["parts"]}
    item_guids = {part["item"]["guid"] for part in created["parts"]}
    assert {track["guid"] for track in (await project.list_tracks())["tracks"]} == (
        track_guids
    )
    assert {item["guid"] for item in (await media.list_media_items())["items"]} == (
        item_guids
    )
    assert (await arrangement.list_regions())["regions"] == [created["region"]]
    for part in created["parts"]:
        take_guid = part["item"]["active_take"]["guid"]
        notes = await media.get_midi_notes(take_guid)
        assert notes["note_count"] == expected_counts[part["role"]]

    _run_probe(bridge_dir, "undo")
    assert (await project.list_tracks())["track_count"] == 0
    assert (await media.list_media_items())["item_count"] == 0
    assert (await arrangement.list_regions())["region_count"] == 0

    _run_probe(bridge_dir, "redo")
    assert {track["guid"] for track in (await project.list_tracks())["tracks"]} == (
        track_guids
    )
    assert {item["guid"] for item in (await media.list_media_items())["items"]} == (
        item_guids
    )
    assert (await arrangement.list_regions())["regions"] == [created["region"]]
    for part in created["parts"]:
        take_guid = part["item"]["active_take"]["guid"]
        notes = await media.get_midi_notes(take_guid)
        assert notes["note_count"] == expected_counts[part["role"]]

    _run_probe(bridge_dir, "undo")
    assert (await project.list_tracks())["track_count"] == 0


@pytest.mark.asyncio
async def test_reaper_automation_takes_and_navigation_acceptance() -> None:
    """Verify producer expansion tools against real REAPER project state."""

    bridge_dir = Path(os.environ["REAPER_MCP_BRIDGE_DIR"])
    bridge = _bridge_client(bridge_dir)
    automation = AutomationService(bridge)
    media = MediaService(bridge)
    navigation = NavigationService(bridge, allowed_project_roots=[bridge_dir])
    project = ProjectService(bridge)
    takes = TakeService(bridge)

    created = await project.create_track("Expansion Acceptance")
    track_guid = created["track"]["guid"]

    ensured = await automation.ensure_track_envelope(track_guid, "volume")
    assert ensured["created"] is True
    envelope_guid = ensured["envelope"]["guid"]
    initial_points = await automation.get_envelope_points(track_guid, envelope_guid)
    assert initial_points["points"][0]["value"] == 1.0

    added_points = await automation.add_envelope_points(
        track_guid,
        envelope_guid,
        [
            {"time_seconds": 1.0, "value": 0.5},
            {"time_seconds": 2.0, "value": 1.0},
        ],
    )
    assert added_points["point_count"] == 3
    point = added_points["points"][1]
    updated_points = await automation.update_envelope_point(
        track_guid,
        envelope_guid,
        point["index"],
        point["fingerprint"],
        value=0.75,
    )
    assert updated_points["points"][1]["value"] == pytest.approx(0.75)
    assert (await automation.set_track_automation_mode(track_guid, "touch"))[
        "mode"
    ] == "touch"

    item = await media.create_midi_item(track_guid, name="Take Acceptance")
    item_guid = item["item"]["guid"]
    added_take = await takes.add_empty_take(item_guid, "Comp B")
    active_take_guid = added_take["active_take_guid"]
    assert added_take["take_count"] == 2
    renamed = await takes.rename_take(active_take_guid, "Comp Winner")
    assert renamed["changed_take"]["name"] == "Comp Winner"
    assert (await takes.set_take_pan(active_take_guid, -0.25))["changed_take"][
        "pan"
    ] == pytest.approx(-0.25)
    cropped = await takes.crop_to_active_take(item_guid, active_take_guid, 2)
    assert cropped["take_count"] == 1

    assert (await navigation.set_edit_cursor(2.5))["edit_cursor_seconds"] == 2.5
    assert (await navigation.set_time_selection(1.0, 3.0))["time_selection"][
        "is_set"
    ] is True
    assert (await navigation.set_loop_points(0.5, 4.0))["loop_points"]["is_set"] is True
    assert (await navigation.set_loop_enabled(True))["loop_enabled"] is True
    project_path = bridge_dir / "expansion-acceptance.rpp"
    assert (await navigation.save_project_as(str(project_path)))["saved"] is True
    assert project_path.is_file()

    assert (await project.delete_track(track_guid))["changes_applied"] is True
    assert (await navigation.save_project())["saved"] is True


@pytest.mark.asyncio
async def test_reaper_producer_expansion_acceptance(tmp_path: Path) -> None:
    """Verify the producer-focused bridge additions in an isolated project."""

    bridge_dir = Path(os.environ["REAPER_MCP_BRIDGE_DIR"])
    bridge = _bridge_client(bridge_dir)
    project = ProjectService(bridge)
    media = MediaService(bridge, [tmp_path])
    audio_analysis = AudioAnalysisService(
        [
            tmp_path,
            bridge_dir / "Media",
            Path.home() / "Music" / "Reaper MCP Demos" / "Media",
        ],
        bridge_client=bridge,
    )
    controllers = MidiControllerService(bridge)
    tempo_map = TempoMapService(bridge)
    controls = ProjectControlsService(bridge)
    fx = FxService(bridge)
    routing = RoutingService(bridge)
    templates = TemplateService(bridge, [tmp_path])
    batch = BatchService(bridge)
    workflows = WorkflowService(bridge)

    source = await project.create_track("Expansion Source")
    destination = await project.create_track("Expansion Destination")
    assert source["ok"] is True
    assert destination["ok"] is True
    source_guid = source["track"]["guid"]
    destination_guid = destination["track"]["guid"]

    midi_item = await media.create_midi_item(source_guid)
    assert midi_item["ok"] is True
    take_guid = midi_item["item"]["active_take"]["guid"]
    audio_path = tmp_path / "loudness-source.wav"
    _write_test_wav(audio_path)
    audio_item = await media.insert_audio_item(source_guid, str(audio_path), 2.0)
    assert audio_item["ok"] is True
    audio_take = (
        await TakeService(bridge).list_item_takes(audio_item["item"]["guid"])
    )["takes"][0]
    loudness = await audio_analysis.calculate_take_loudness(audio_take["guid"])
    assert loudness["ok"] is True
    assert loudness["calculation_status"] in {-1, 1}
    assert Path(loudness["analysis"]["path"]).name == audio_path.name
    controller = {
        "position": {"measure": 1, "beat": 1.0},
        "event_type": "cc",
        "controller": 1,
        "value": 64,
        "channel": 0,
    }
    added_controller = await controllers.add_events(take_guid, [controller])
    assert added_controller["ok"] is True
    listed_controllers = await controllers.list_events(take_guid)
    assert listed_controllers["event_count"] == 1
    event = listed_controllers["events"][0]
    updated_controller = await controllers.update_event(
        take_guid,
        event["index"],
        event["fingerprint"],
        {**controller, "value": 96},
    )
    assert updated_controller["ok"] is True
    event = updated_controller["updated_event"]
    deleted_controller = await controllers.delete_events(
        take_guid,
        [{"index": event["index"], "expected_fingerprint": event["fingerprint"]}],
    )
    assert deleted_controller["deleted_count"] == 1

    pattern = await workflows.create_midi_pattern(
        destination_guid,
        "arpeggio",
        start_measure=1,
        bars=2,
        root_note=60,
        mode="minor",
        subdivision_beats=0.5,
    )
    assert pattern["ok"] is True
    assert pattern["note_count"] > 0
    assert pattern["pattern"] == "arpeggio"

    created_marker = await tempo_map.create_marker(2.0, 128.0, 3, 4)
    assert created_marker["ok"] is True
    marker = next(
        marker for marker in created_marker["markers"] if marker["bpm"] == 128.0
    )
    updated_marker = await tempo_map.update_marker(
        marker["index"], marker["fingerprint"], 2.0, 132.0, 3, 4
    )
    assert updated_marker["ok"] is True
    marker = next(
        marker for marker in updated_marker["markers"] if marker["bpm"] == 132.0
    )
    assert (await tempo_map.delete_marker(marker["index"], marker["fingerprint"]))[
        "ok"
    ] is True

    assert (await controls.get_grid())["ok"] is True
    assert (await controls.set_grid(0.25, 0.1, 0, True))["ok"] is True
    assert (await controls.get_metronome())["ok"] is True
    assert (await controls.set_metronome(True))["ok"] is True
    assert (await controls.get_playback_rate())["ok"] is True
    assert (await controls.set_playback_rate(1.0))["ok"] is True

    assert (await project.set_track_recording(source_guid, 0, True))["ok"] is True
    assert (await project.set_track_folder_depth(source_guid, 1))["ok"] is True
    assert (
        await batch.update_tracks(
            [
                {
                    "track_guid": source_guid,
                    "name": "Expansion Source Updated",
                    "volume": 0.8,
                },
                {"track_guid": destination_guid, "muted": True},
            ]
        )
    )["ok"] is True

    available_fx = await fx.list_available_fx()
    assert available_fx["ok"] is True
    eq = next(entry for entry in available_fx["fx"] if "ReaEQ" in entry["name"])
    added_take_fx = await fx.add_take_fx(take_guid, eq["identifier"])
    assert added_take_fx["ok"] is True
    take_fx_identity = _take_fx_identity(added_take_fx["added_fx"])
    listed_take_fx = await fx.list_take_fx(take_guid)
    assert listed_take_fx["fx_count"] == 1
    assert (await fx.set_take_fx_enabled(take_fx_identity, False))["ok"] is True
    assert (await fx.remove_take_fx(take_fx_identity))["ok"] is True
    added_fx = await fx.add_fx(source_guid, eq["identifier"])
    assert added_fx["ok"] is True
    fx_identity = _fx_identity(added_fx["added_fx"])
    assert (await fx.get_fx_preset(fx_identity))["ok"] is True
    preset_bank = await fx.get_fx_preset_index(fx_identity)
    assert preset_bank["ok"] is True
    if preset_bank["preset_count"] > 0:
        assert (await fx.navigate_fx_presets(fx_identity, 1))["ok"] is True
    compressor = next(
        entry for entry in available_fx["fx"] if "ReaComp" in entry["name"]
    )
    assert (await fx.add_fx(source_guid, compressor["identifier"]))["ok"] is True
    assert (await fx.move_fx(fx_identity, 1))["ok"] is True
    assert (await fx.copy_fx_chain(source_guid, destination_guid))["ok"] is True

    sidechain = await routing.setup_sidechain(source_guid, destination_guid)
    assert sidechain["ok"] is True
    assert sidechain["source_channels"] == "1/2"
    assert sidechain["destination_channels"] == "3/4"

    template_path = tmp_path / "Expansion.RTrackTemplate"
    saved_template = await templates.save_template(source_guid, str(template_path))
    assert saved_template["ok"] is True
    assert template_path.is_file()
    applied_template = await templates.apply_template(str(template_path))
    assert applied_template["ok"] is True
    assert applied_template["track"]["guid"] not in {
        source_guid,
        destination_guid,
    }
    listed_templates = await templates.list_templates()
    template_sha256 = next(
        template["sha256"]
        for template in listed_templates["templates"]
        if Path(template["path"]) == template_path
    )
    assert (await templates.delete_template(str(template_path), template_sha256))[
        "ok"
    ] is True

    assert (await project.delete_track(source_guid))["ok"] is True
    assert (await project.delete_track(destination_guid))["ok"] is True
