local function require_song_starter_integer(value, field_name)
  if type(value) ~= "number" or value % 1 ~= 0 then
    error("invalid_workflow_request: " .. field_name .. " must be an integer")
  end
end

local function validate_song_starter_request(project, args)
  if type(args.name) ~= "string" or args.name:match("^%s*$") or #args.name > 100 then
    error("invalid_workflow_request: name must contain 1 to 100 visible characters")
  end
  require_song_starter_integer(args.start_measure, "start_measure")
  if args.start_measure < 1 or args.start_measure > 9999 then
    error("invalid_workflow_request: start_measure must be between 1 and 9999")
  end
  require_song_starter_integer(args.bars, "bars")
  if args.bars < 4 or args.bars > 32 or args.bars % 4 ~= 0 then
    error("invalid_workflow_request: bars must be 4 to 32 in multiples of 4")
  end
  require_song_starter_integer(args.root_note, "root_note")
  if args.root_note < 48 or args.root_note > 72 then
    error("invalid_workflow_request: root_note must be between 48 and 72")
  end
  if args.mode ~= "major" and args.mode ~= "minor" then
    error("invalid_workflow_request: mode must be major or minor")
  end

  local numerator, denominator = reaper.TimeMap_GetTimeSigAtTime(project, 0)
  if numerator ~= 4 or denominator ~= 4 then
    error("unsupported_workflow_time_signature: song starters require 4/4")
  end
  local start_qn = (args.start_measure - 1) * 4
  local end_qn = start_qn + (args.bars * 4)
  local start_seconds = reaper.TimeMap2_QNToTime(project, start_qn)
  local end_seconds = reaper.TimeMap2_QNToTime(project, end_qn)
  local start_numerator, start_denominator = reaper.TimeMap_GetTimeSigAtTime(
    project,
    start_seconds
  )
  if start_numerator ~= 4 or start_denominator ~= 4 then
    error("unsupported_workflow_time_signature: starter position must use 4/4")
  end
  return {
    start_qn = start_qn,
    end_qn = end_qn,
    start_seconds = start_seconds,
    end_seconds = end_seconds,
  }
end

local function append_song_starter_note(notes, start_qn, length_qn, pitch, velocity, channel)
  notes[#notes + 1] = {
    start_qn = start_qn,
    end_qn = start_qn + length_qn,
    pitch = pitch,
    velocity = velocity,
    channel = channel or 0,
  }
end

local function song_starter_notes(args, start_qn)
  local notes = { drums = {}, bass = {}, chords = {}, lead = {} }
  local progression = SONG_STARTER_PROGRESSIONS[args.mode]
  for bar = 0, args.bars - 1 do
    local bar_start = start_qn + (bar * 4)
    local chord = progression[(bar % 4) + 1]
    local chord_root = args.root_note + chord.degree

    for _, beat in ipairs({ 0, 2 }) do
      append_song_starter_note(notes.drums, bar_start + beat, 0.25, 36, 108, 9)
    end
    for _, beat in ipairs({ 1, 3 }) do
      append_song_starter_note(notes.drums, bar_start + beat, 0.25, 38, 104, 9)
    end
    for step = 0, 7 do
      local velocity = step % 2 == 0 and 88 or 76
      append_song_starter_note(notes.drums, bar_start + (step * 0.5), 0.125, 42, velocity, 9)
    end

    for beat = 0, 3 do
      append_song_starter_note(notes.bass, bar_start + beat, 0.8, chord_root - 24, 92, 0)
    end
    for _, interval in ipairs(chord.intervals) do
      append_song_starter_note(notes.chords, bar_start, 3.8, chord_root + interval, 78, 0)
    end

    local lead_intervals = {
      0,
      chord.intervals[2],
      chord.intervals[3],
      chord.intervals[2],
    }
    for beat = 0, 3 do
      append_song_starter_note(
        notes.lead,
        bar_start + beat,
        0.75,
        chord_root + 12 + lead_intervals[beat + 1],
        84,
        0
      )
    end
  end
  return notes
end

local function create_song_starter_part(project, definition, resolved, notes, created_tracks)
  local track_index = safe_number_call(reaper.CountTracks, 0, project)
  reaper.InsertTrackAtIndex(track_index, true)
  local track = reaper.GetTrack(project, track_index)
  if not track then
    error("REAPER did not return the created " .. definition.role .. " track")
  end
  created_tracks[#created_tracks + 1] = track
  reaper.GetSetMediaTrackInfo_String(track, "P_NAME", definition.name, true)

  local item = reaper.CreateNewMIDIItemInProj(
    track,
    resolved.start_seconds,
    resolved.end_seconds,
    false
  )
  if not item then
    error("REAPER did not return the created " .. definition.role .. " MIDI item")
  end
  local take = reaper.GetActiveTake(item)
  if not take or not reaper.TakeIsMIDI(take) then
    error("REAPER did not return a MIDI take for " .. definition.role)
  end
  reaper.GetSetMediaItemTakeInfo_String(take, "P_NAME", definition.name, true)

  for note_index, note in ipairs(notes) do
    local inserted = reaper.MIDI_InsertNote(
      take,
      false,
      false,
      reaper.MIDI_GetPPQPosFromProjQN(take, note.start_qn),
      reaper.MIDI_GetPPQPosFromProjQN(take, note.end_qn),
      note.channel,
      note.pitch,
      note.velocity,
      true
    )
    if not inserted then
      error(
        "REAPER rejected "
          .. definition.role
          .. " MIDI note "
          .. tostring(note_index)
      )
    end
  end
  reaper.MIDI_Sort(take)
  local _, inserted_count = reaper.MIDI_CountEvts(take)
  if inserted_count ~= #notes then
    error("REAPER returned an unexpected " .. definition.role .. " note count")
  end
  reaper.UpdateItemInProject(item)
  return {
    role = definition.role,
    track = track,
    item = item,
    note_count = inserted_count,
  }
end

COMMANDS.create_song_starter = {
  mutates_project = true,
  preflight_handler = function(envelope)
    validate_song_starter_request(current_project(), envelope.args)
  end,
  handler = function(envelope)
    local project = current_project()
    local args = envelope.args
    local resolved = validate_song_starter_request(project, args)
    local prior_selection = snapshot_selected_tracks(project)
    local created_tracks = {}
    local created_parts = {}
    local region_id = nil

    local function rollback()
      if region_id then
        pcall(reaper.DeleteProjectMarker, project, region_id, true)
      end
      for index = #created_tracks, 1, -1 do
        pcall(reaper.DeleteTrack, created_tracks[index])
      end
      restore_selected_tracks(project, prior_selection)
      reaper.TrackList_AdjustWindows(false)
      reaper.UpdateTimeline()
      reaper.UpdateArrange()
    end

    local ok, result_or_error = pcall(function()
      local notes_by_role = song_starter_notes(args, resolved.start_qn)
      local total_note_count = 0
      for _, definition in ipairs(SONG_STARTER_PARTS) do
        local part = create_song_starter_part(
          project,
          definition,
          resolved,
          notes_by_role[definition.role],
          created_tracks
        )
        created_parts[#created_parts + 1] = part
        total_note_count = total_note_count + part.note_count
      end

      region_id = reaper.AddProjectMarker2(
        project,
        true,
        resolved.start_seconds,
        resolved.end_seconds,
        args.name,
        -1,
        0
      )
      if region_id == nil or region_id < 0 then
        error("REAPER rejected song starter region creation")
      end

      restore_selected_tracks(project, prior_selection)
      local selection_restored = track_selection_matches(project, prior_selection)
      if not selection_restored then
        error("prior track selection was not restored")
      end

      local region = require_region_identity(project, {
        id = region_id,
        expected_name = args.name,
        expected_start_seconds = resolved.start_seconds,
        expected_end_seconds = resolved.end_seconds,
      })
      local parts = {}
      for _, part in ipairs(created_parts) do
        parts[#parts + 1] = {
          role = part.role,
          track = track_snapshot(part.track),
          item = media_item_snapshot(project, part.item),
          note_count = part.note_count,
        }
      end
      return {
        name = args.name,
        start_measure = args.start_measure,
        bars = args.bars,
        root_note = args.root_note,
        mode = args.mode,
        start_qn = resolved.start_qn,
        end_qn = resolved.end_qn,
        start_seconds = resolved.start_seconds,
        end_seconds = resolved.end_seconds,
        parts = parts,
        region = region_payload(region),
        total_note_count = total_note_count,
        selection_restored = selection_restored,
        changes_applied = true,
      }
    end)

    if not ok then
      rollback()
      error("workflow_creation_failed: " .. tostring(result_or_error))
    end
    reaper.MarkProjectDirty(project)
    reaper.TrackList_AdjustWindows(false)
    reaper.UpdateTimeline()
    reaper.UpdateArrange()
    return result_or_error
  end,
}

local function validate_midi_pattern_request(project, args)
  require_track_by_guid(project, args.track_guid)
  if args.pattern ~= "chord_progression" and args.pattern ~= "arpeggio" then
    error("invalid_workflow_request: pattern must be chord_progression or arpeggio")
  end
  require_song_starter_integer(args.start_measure, "start_measure")
  require_song_starter_integer(args.bars, "bars")
  require_song_starter_integer(args.root_note, "root_note")
  if args.start_measure < 1 or args.start_measure > 9999 then
    error("invalid_workflow_request: start_measure must be between 1 and 9999")
  end
  if args.bars < 1 or args.bars > 64 then
    error("invalid_workflow_request: bars must be between 1 and 64")
  end
  if args.root_note < 36 or args.root_note > 84 then
    error("invalid_workflow_request: root_note must be between 36 and 84")
  end
  if args.mode ~= "major" and args.mode ~= "minor" then
    error("invalid_workflow_request: mode must be major or minor")
  end
  if args.subdivision_beats ~= 0.25 and args.subdivision_beats ~= 0.5
      and args.subdivision_beats ~= 1 and args.subdivision_beats ~= 2 then
    error("invalid_workflow_request: subdivision_beats must be 0.25, 0.5, 1, or 2")
  end
  local numerator, denominator = reaper.TimeMap_GetTimeSigAtTime(project, 0)
  if numerator ~= 4 or denominator ~= 4 then
    error("unsupported_workflow_time_signature: MIDI patterns require 4/4")
  end
  local start_qn = (args.start_measure - 1) * 4
  return {
    start_qn = start_qn,
    end_qn = start_qn + (args.bars * 4),
    start_seconds = reaper.TimeMap2_QNToTime(project, start_qn),
    end_seconds = reaper.TimeMap2_QNToTime(project, start_qn + (args.bars * 4)),
  }
end

local function midi_pattern_notes(args, start_qn)
  local progression = SONG_STARTER_PROGRESSIONS[args.mode]
  local notes = {}
  for bar = 0, args.bars - 1 do
    local bar_start = start_qn + (bar * 4)
    local chord = progression[(bar % 4) + 1]
    local chord_root = args.root_note + chord.degree
    if args.pattern == "chord_progression" then
      for _, interval in ipairs(chord.intervals) do
        append_song_starter_note(notes, bar_start, 3.8, chord_root + interval, 84, 0)
      end
    else
      local steps = math.floor(4 / args.subdivision_beats)
      for step = 0, steps - 1 do
        local interval = chord.intervals[(step % #chord.intervals) + 1]
        append_song_starter_note(
          notes,
          bar_start + (step * args.subdivision_beats),
          math.max(0.1, args.subdivision_beats * 0.8),
          chord_root + interval + 12,
          step % 2 == 0 and 96 or 82,
          0
        )
      end
    end
  end
  return notes
end

COMMANDS.create_midi_pattern = {
  mutates_project = true,
  preflight_handler = function(envelope)
    validate_midi_pattern_request(current_project(), envelope.args)
  end,
  handler = function(envelope)
    local project = current_project()
    local args = envelope.args
    local resolved = validate_midi_pattern_request(project, args)
    local track = require_track_by_guid(project, args.track_guid)
    local item = reaper.CreateNewMIDIItemInProj(
      track,
      resolved.start_seconds,
      resolved.end_seconds,
      false
    )
    if not item then
      error("workflow_creation_failed: REAPER did not create the MIDI pattern item")
    end
    local take = reaper.GetActiveTake(item)
    if not take or not reaper.TakeIsMIDI(take) then
      error("workflow_creation_failed: REAPER did not create a MIDI pattern take")
    end
    local notes = midi_pattern_notes(args, resolved.start_qn)
    for index, note in ipairs(notes) do
      local inserted = reaper.MIDI_InsertNote(
        take,
        false,
        false,
        reaper.MIDI_GetPPQPosFromProjQN(take, note.start_qn),
        reaper.MIDI_GetPPQPosFromProjQN(take, note.end_qn),
        note.channel,
        note.pitch,
        note.velocity,
        true
      )
      if not inserted then
        reaper.DeleteTrackMediaItem(track, item)
        error("workflow_creation_failed: REAPER rejected MIDI pattern note " .. tostring(index))
      end
    end
    reaper.MIDI_Sort(take)
    reaper.UpdateItemInProject(item)
    reaper.UpdateArrange()
    return {
      pattern = args.pattern,
      track_guid = args.track_guid,
      item = media_item_snapshot(project, item),
      note_count = #notes,
      start_measure = args.start_measure,
      bars = args.bars,
      changes_applied = true,
    }
  end,
}

COMMANDS.list_media_items = {
  mutates_project = false,
  handler = function()
    local project = current_project()
    local items = project_media_items(project)
    return {
      items = items,
      item_count = #items,
    }
  end,
}

COMMANDS.create_midi_item = {
  mutates_project = true,
  preflight_handler = function(envelope)
    local project = current_project()
    require_track_by_guid(project, envelope.args.track_guid)
    validate_musical_range(envelope.args)
  end,
  handler = function(envelope)
    local args = envelope.args
    local project = current_project()
    local track = require_track_by_guid(project, args.track_guid)
    validate_musical_range(args)

    local resolved = musical_range(project, args.start, args.length)
    local item = reaper.CreateNewMIDIItemInProj(
      track,
      resolved.start_seconds,
      resolved.end_seconds,
      false
    )
    if not item then
      error("REAPER did not return the created MIDI item")
    end

    local take = reaper.GetActiveTake(item)
    if take and args.name then
      reaper.GetSetMediaItemTakeInfo_String(take, "P_NAME", args.name, true)
    end
    if take then
      resolved.start_ppq = reaper.MIDI_GetPPQPosFromProjQN(take, resolved.start_qn)
      resolved.end_ppq = reaper.MIDI_GetPPQPosFromProjQN(take, resolved.end_qn)
    end
    reaper.UpdateItemInProject(item)
    reaper.UpdateArrange()

    return {
      item = media_item_snapshot(project, item),
      position = resolved,
      changes_applied = true,
    }
  end,
}

COMMANDS.insert_audio_item = {
  mutates_project = true,
  preflight_handler = function(envelope)
    local project = current_project()
    require_track_by_guid(project, envelope.args.track_guid)
    validate_audio_source_path(envelope.args.source_path)
    validate_musical_position(envelope.args.start)
  end,
  handler = function(envelope)
    local args = envelope.args
    local project = current_project()
    local track = require_track_by_guid(project, args.track_guid)
    validate_audio_source_path(args.source_path)
    validate_musical_position(args.start)

    local resolved_start = musical_position(project, args.start)
    local before_count = safe_number_call(reaper.CountMediaItems, 0, project)
    local previous_cursor = safe_number_call(reaper.GetCursorPosition, 0)
    local selected_tracks = snapshot_selected_tracks(project)

    reaper.SetOnlyTrackSelected(track)
    reaper.SetEditCurPos(resolved_start.start_seconds, false, false)
    local inserted = reaper.InsertMedia(args.source_path, 0)
    reaper.SetEditCurPos(previous_cursor, false, false)
    restore_selected_tracks(project, selected_tracks)

    if inserted == false then
      error("invalid_media_item_request: REAPER rejected the audio source")
    end

    local item = find_inserted_media_item(project, before_count, track, resolved_start.start_seconds)
    if not item then
      error("invalid_media_item_request: REAPER did not return an inserted audio item")
    end

    local take = reaper.GetActiveTake(item)
    if take and args.name then
      reaper.GetSetMediaItemTakeInfo_String(take, "P_NAME", args.name, true)
    end
    reaper.UpdateItemInProject(item)
    reaper.UpdateArrange()

    return {
      item = media_item_snapshot(project, item),
      position = media_item_position(project, item, args.start),
      changes_applied = true,
    }
  end,
}

COMMANDS.move_media_item = {
  mutates_project = true,
  preflight_handler = function(envelope)
    local project = current_project()
    require_media_item_by_guid(project, envelope.args.item_guid)
    validate_musical_position(envelope.args.start)
  end,
  handler = function(envelope)
    local args = envelope.args
    local project = current_project()
    local item = require_media_item_by_guid(project, args.item_guid)
    local resolved_start = musical_position(project, args.start)
    reaper.SetMediaItemInfo_Value(item, "D_POSITION", resolved_start.start_seconds)
    return media_item_mutation_result(project, item)
  end,
}

local function register_media_item_track_move_command()
local function media_item_move_invariants(item)
  local takes = {}
  local take_count = safe_number_call(reaper.CountTakes, 0, item)
  for take_index = 0, take_count - 1 do
    local take = reaper.GetTake(item, take_index)
    if not take then
      error("invalid_media_item_request: media item take was not found")
    end
    takes[#takes + 1] = {
      guid = take_guid(take),
      start_offset = safe_number_call(
        reaper.GetMediaItemTakeInfo_Value,
        0,
        take,
        "D_STARTOFFS"
      ),
    }
  end
  return {
    guid = item_guid(item),
    position = safe_number_call(
      reaper.GetMediaItemInfo_Value,
      0,
      item,
      "D_POSITION"
    ),
    length = safe_number_call(
      reaper.GetMediaItemInfo_Value,
      0,
      item,
      "D_LENGTH"
    ),
    takes = takes,
  }
end

local function media_item_move_invariants_match(item, expected)
  if item_guid(item) ~= expected.guid then
    return false, "item GUID"
  end
  local position = safe_number_call(
    reaper.GetMediaItemInfo_Value,
    0,
    item,
    "D_POSITION"
  )
  if not postcondition_values_match(position, expected.position) then
    return false, "timeline position"
  end
  local length = safe_number_call(
    reaper.GetMediaItemInfo_Value,
    0,
    item,
    "D_LENGTH"
  )
  if not postcondition_values_match(length, expected.length) then
    return false, "item length"
  end
  local take_count = safe_number_call(reaper.CountTakes, 0, item)
  if take_count ~= #expected.takes then
    return false, "take count"
  end
  for take_index = 0, take_count - 1 do
    local take = reaper.GetTake(item, take_index)
    local expected_take = expected.takes[take_index + 1]
    if not take or take_guid(take) ~= expected_take.guid then
      return false, "take identity"
    end
    local start_offset = safe_number_call(
      reaper.GetMediaItemTakeInfo_Value,
      0,
      take,
      "D_STARTOFFS"
    )
    if not postcondition_values_match(start_offset, expected_take.start_offset) then
      return false, "take start offset"
    end
  end
  return true, nil
end

local function media_item_track_guid(item)
  local track = reaper.GetMediaItemTrack(item)
  if not track then
    error("invalid_media_item_request: media item source track was not found")
  end
  return track, safe_string_call(reaper.GetTrackGUID, "", track)
end

local function require_media_item_source_track(item, expected_source_track_guid)
  local source_track, source_track_guid = media_item_track_guid(item)
  if source_track_guid ~= expected_source_track_guid then
    error(
      "invalid_media_item_request: item is not on expected_source_track_guid"
    )
  end
  return source_track
end

local function rollback_media_item_track_move(item, source_track)
  local rolled_back = reaper.MoveMediaItemToTrack(item, source_track)
  reaper.UpdateItemInProject(item)
  reaper.UpdateArrange()
  if not rolled_back then
    error("rollback_failed: media item could not be returned to its source track")
  end
end

COMMANDS.move_media_item_to_track = {
  mutates_project = true,
  preflight_handler = function(envelope)
    local args = envelope.args
    local project = current_project()
    local item = require_media_item_by_guid(project, args.item_guid)
    require_track_by_guid(project, args.expected_source_track_guid)
    require_media_item_source_track(item, args.expected_source_track_guid)
    require_track_by_guid(project, args.destination_track_guid)
    if args.destination_track_guid == args.expected_source_track_guid then
      error("invalid_media_item_request: destination track must differ from source")
    end
  end,
  handler = function(envelope)
    local args = envelope.args
    local project = current_project()
    local item = require_media_item_by_guid(project, args.item_guid)
    local source_track = require_track_by_guid(
      project,
      args.expected_source_track_guid
    )
    require_media_item_source_track(item, args.expected_source_track_guid)
    local destination_track = require_track_by_guid(
      project,
      args.destination_track_guid
    )
    if args.destination_track_guid == args.expected_source_track_guid then
      error("invalid_media_item_request: destination track must differ from source")
    end

    local invariants = media_item_move_invariants(item)
    local moved = reaper.MoveMediaItemToTrack(item, destination_track)
    if not moved then
      error("invalid_media_item_request: REAPER rejected the destination track")
    end

    reaper.UpdateItemInProject(item)
    reaper.UpdateArrange()
    local _, actual_track_guid = media_item_track_guid(item)
    if actual_track_guid ~= args.destination_track_guid then
      rollback_media_item_track_move(item, source_track)
      error("postcondition_failed: media item destination track did not match")
    end
    local preserved, changed_field = media_item_move_invariants_match(
      item,
      invariants
    )
    if not preserved then
      rollback_media_item_track_move(item, source_track)
      error(
        "postcondition_failed: media item "
          .. tostring(changed_field)
          .. " changed during track move"
      )
    end

    return {
      source_track_guid = args.expected_source_track_guid,
      destination_track_guid = args.destination_track_guid,
      item = media_item_snapshot(project, item),
      position_preserved = true,
      take_offsets_preserved = true,
      changes_applied = true,
    }
  end,
}
end

register_media_item_track_move_command()

COMMANDS.resize_media_item = {
  mutates_project = true,
  preflight_handler = function(envelope)
    local project = current_project()
    require_media_item_by_guid(project, envelope.args.item_guid)
    if type(envelope.args.length) ~= "table"
      or type(envelope.args.length.beats) ~= "number"
      or envelope.args.length.beats <= 0 then
      error("invalid_time_position: length.beats must be > 0")
    end
  end,
  handler = function(envelope)
    local args = envelope.args
    local project = current_project()
    local item = require_media_item_by_guid(project, args.item_guid)
    local position = safe_number_call(
      reaper.GetMediaItemInfo_Value,
      0,
      item,
      "D_POSITION"
    )
    local start_qn = reaper.TimeMap2_timeToQN(project, position)
    local end_seconds = reaper.TimeMap2_QNToTime(
      project,
      start_qn + args.length.beats
    )
    reaper.SetMediaItemInfo_Value(item, "D_LENGTH", end_seconds - position)
    return media_item_mutation_result(project, item)
  end,
}

local function project_media_item_guid_set(project)
  local guids = {}
  local item_count = safe_number_call(reaper.CountMediaItems, 0, project)
  for index = 0, item_count - 1 do
    local item = reaper.GetMediaItem(project, index)
    if item then
      guids[item_guid(item)] = true
    end
  end
  return guids
end

local function new_media_items(project, prior_guids)
  local items = {}
  local item_count = safe_number_call(reaper.CountMediaItems, 0, project)
  for index = 0, item_count - 1 do
    local item = reaper.GetMediaItem(project, index)
    if item and not prior_guids[item_guid(item)] then
      items[#items + 1] = item
    end
  end
  return items
end

local function rollback_created_media_items(items)
  for _, item in ipairs(items) do
    local track = reaper.GetMediaItemTrack(item)
    if track then
      reaper.DeleteTrackMediaItem(track, item)
    end
  end
end

COMMANDS.duplicate_media_item = {
  mutates_project = true,
  preflight_handler = function(envelope)
    require_media_item_by_guid(current_project(), envelope.args.item_guid)
  end,
  handler = function(envelope)
    local project = current_project()
    local source_item = require_media_item_by_guid(project, envelope.args.item_guid)
    local prior_selection = snapshot_selected_media_items(project)
    local prior_guids = project_media_item_guid_set(project)

    reaper.SelectAllMediaItems(project, false)
    reaper.SetMediaItemSelected(source_item, true)
    reaper.Main_OnCommand(41295, 0)

    local created_items = new_media_items(project, prior_guids)
    if #created_items ~= 1 then
      rollback_created_media_items(created_items)
      restore_selected_media_items(project, prior_selection)
      error("invalid_media_item_request: REAPER did not create exactly one duplicate")
    end

    restore_selected_media_items(project, prior_selection)
    local selection_restored = media_item_selection_matches(project, prior_selection)
    if not selection_restored then
      rollback_created_media_items(created_items)
      restore_selected_media_items(project, prior_selection)
      error("invalid_media_item_request: prior item selection was not restored")
    end

    local duplicated_item = created_items[1]
    reaper.UpdateItemInProject(duplicated_item)
    reaper.UpdateArrange()
    return {
      source_item_guid = envelope.args.item_guid,
      item = media_item_snapshot(project, duplicated_item),
      selection_restored = selection_restored,
      changes_applied = true,
    }
  end,
}

local function resolve_media_item_split(project, item, split_at)
  validate_musical_position(split_at)
  local resolved = musical_position(project, split_at)
  local item_start = safe_number_call(reaper.GetMediaItemInfo_Value, 0, item, "D_POSITION")
  local item_length = safe_number_call(reaper.GetMediaItemInfo_Value, 0, item, "D_LENGTH")
  local item_end = item_start + item_length
  if resolved.start_seconds <= item_start or resolved.start_seconds >= item_end then
    error("invalid_media_item_request: split position must be inside the media item")
  end
  return resolved.start_seconds
end

COMMANDS.split_media_item = {
  mutates_project = true,
  preflight_handler = function(envelope)
    local project = current_project()
    local item = require_media_item_by_guid(project, envelope.args.item_guid)
    resolve_media_item_split(project, item, envelope.args.split_at)
  end,
  handler = function(envelope)
    local project = current_project()
    local item = require_media_item_by_guid(project, envelope.args.item_guid)
    local split_seconds = resolve_media_item_split(project, item, envelope.args.split_at)
    local right_item = reaper.SplitMediaItem(item, split_seconds)
    if not right_item then
      error("invalid_media_item_request: REAPER rejected the split position")
    end
    reaper.UpdateItemInProject(item)
    reaper.UpdateItemInProject(right_item)
    reaper.UpdateArrange()
    return {
      left_item = media_item_snapshot(project, item),
      right_item = media_item_snapshot(project, right_item),
      changes_applied = true,
    }
  end,
}

local function require_boolean_item_value(value, field_name)
  if type(value) ~= "boolean" then
    error("invalid_media_item_request: " .. field_name .. " must be a boolean")
  end
end

local function require_item_number(value, field_name, minimum, maximum)
  if type(value) ~= "number" or value < minimum or value > maximum then
    error(
      "invalid_media_item_request: "
      .. field_name
      .. " must be between "
      .. tostring(minimum)
      .. " and "
      .. tostring(maximum)
    )
  end
end

local function set_media_item_value(project, item, parameter, value)
  if not reaper.SetMediaItemInfo_Value(item, parameter, value) then
    error("invalid_media_item_request: REAPER rejected the media item property")
  end
  return media_item_mutation_result(project, item)
end

COMMANDS.set_media_item_mute = {
  mutates_project = true,
  preflight_handler = function(envelope)
    require_media_item_by_guid(current_project(), envelope.args.item_guid)
    require_boolean_item_value(envelope.args.muted, "muted")
  end,
  handler = function(envelope)
    local project = current_project()
    local item = require_media_item_by_guid(project, envelope.args.item_guid)
    require_boolean_item_value(envelope.args.muted, "muted")
    return set_media_item_value(project, item, "B_MUTE", envelope.args.muted and 1 or 0)
  end,
}

COMMANDS.set_media_item_gain = {
  mutates_project = true,
  preflight_handler = function(envelope)
    require_media_item_by_guid(current_project(), envelope.args.item_guid)
    require_item_number(envelope.args.gain, "gain", 0, 4)
  end,
  handler = function(envelope)
    local project = current_project()
    local item = require_media_item_by_guid(project, envelope.args.item_guid)
    require_item_number(envelope.args.gain, "gain", 0, 4)
    return set_media_item_value(project, item, "D_VOL", envelope.args.gain)
  end,
}

local function require_item_fade_length(item, length_seconds)
  require_item_number(length_seconds, "length_seconds", 0, 3600)
  local item_length = safe_number_call(reaper.GetMediaItemInfo_Value, 0, item, "D_LENGTH")
  if length_seconds > item_length then
    error("invalid_media_item_request: fade length cannot exceed the media item length")
  end
end

local function media_item_fade_command(parameter)
  return {
    mutates_project = true,
    preflight_handler = function(envelope)
      local item = require_media_item_by_guid(current_project(), envelope.args.item_guid)
      require_item_fade_length(item, envelope.args.length_seconds)
    end,
    handler = function(envelope)
      local project = current_project()
      local item = require_media_item_by_guid(project, envelope.args.item_guid)
      require_item_fade_length(item, envelope.args.length_seconds)
      return set_media_item_value(project, item, parameter, envelope.args.length_seconds)
    end,
  }
end

COMMANDS.set_media_item_fade_in = media_item_fade_command("D_FADEINLEN")
COMMANDS.set_media_item_fade_out = media_item_fade_command("D_FADEOUTLEN")

COMMANDS.delete_media_item = {
  mutates_project = true,
  preflight_handler = function(envelope)
    local project = current_project()
    require_media_item_by_guid(project, envelope.args.item_guid)
  end,
  handler = function(envelope)
    local args = envelope.args
    local project = current_project()
    local item = require_media_item_by_guid(project, args.item_guid)
    local track = reaper.GetMediaItemTrack(item)
    if not track or not reaper.DeleteTrackMediaItem(track, item) then
      error("invalid_media_item_request: REAPER could not delete the media item")
    end
    reaper.UpdateArrange()
    return {
      deleted_item_guid = args.item_guid,
      item_count = safe_number_call(reaper.CountMediaItems, 0, project),
      changes_applied = true,
    }
  end,
}

COMMANDS.get_midi_notes = {
  mutates_project = false,
  handler = function(envelope)
    local project = current_project()
    local take = require_midi_take_by_guid(project, envelope.args.take_guid)
    local notes = midi_notes(project, take)
    return {
      take_guid = envelope.args.take_guid,
      notes = notes,
      note_count = #notes,
    }
  end,
}

COMMANDS.calculate_take_loudness = {
  mutates_project = false,
  handler = function(envelope)
    local project = current_project()
    local take = require_take_by_guid(project, envelope.args.take_guid)
    local source = reaper.GetMediaItemTake_Source(take)
    if not source then
      error("audio_loudness_failed: take has no media source")
    end

    local source_path = reaper.GetMediaSourceFileName(source)
    return {
      take_guid = envelope.args.take_guid,
      calculation_status = -1,
      source_path = source_path ~= "" and source_path or nil,
      render_stats = "",
      render_stats_summary = "",
    }
  end,
}

local function finalize_midi_take_mutation(project, take)
  reaper.MIDI_Sort(take)
  local item = reaper.GetMediaItemTake_Item(take)
  if item then
    local track = reaper.GetMediaItemTrack(item)
    if track and reaper.MarkTrackItemsDirty then
      reaper.MarkTrackItemsDirty(track, item)
    end
    reaper.UpdateItemInProject(item)
  end
  reaper.MarkProjectDirty(project)
  reaper.UpdateArrange()
end

COMMANDS.add_midi_notes = {
  mutates_project = true,
  preflight_handler = function(envelope)
    local project = current_project()
    local take = require_midi_take_by_guid(project, envelope.args.take_guid)
    if type(envelope.args.notes) ~= "table" or #envelope.args.notes == 0 then
      error("invalid_midi_note_request: notes must be a non-empty array")
    end
    for _, note in ipairs(envelope.args.notes) do
      validate_midi_note(note)
    end
    require_distinct_midi_note_insertions(project, take, envelope.args.notes)
  end,
  handler = function(envelope)
    local project = current_project()
    local take = require_midi_take_by_guid(project, envelope.args.take_guid)
    require_distinct_midi_note_insertions(project, take, envelope.args.notes)
    local snapshot_ok, before_events = reaper.MIDI_GetAllEvts(take, "")
    if not snapshot_ok then
      error("midi_insert_failed: REAPER could not snapshot the MIDI take")
    end

    local mutation_ok, result_or_error = pcall(function()
      for note_index, note in ipairs(envelope.args.notes) do
        local resolved = musical_range(project, note.start, note.length)
        local start_ppq = reaper.MIDI_GetPPQPosFromProjQN(take, resolved.start_qn)
        local end_ppq = reaper.MIDI_GetPPQPosFromProjQN(take, resolved.end_qn)
        local inserted = reaper.MIDI_InsertNote(
          take,
          note.selected or false,
          note.muted or false,
          start_ppq,
          end_ppq,
          note.channel or 0,
          note.pitch,
          note.velocity or 96,
          true
        )
        if not inserted then
          error("midi_insert_failed: REAPER rejected MIDI note at batch index " .. tostring(note_index))
        end
      end
      finalize_midi_take_mutation(project, take)
      local notes = midi_notes(project, take)
      local new_notes = find_requested_midi_notes(project, take, envelope.args.notes, notes)
      return {
        take_guid = envelope.args.take_guid,
        notes = notes,
        note_count = #notes,
        inserted_count = #envelope.args.notes,
        inserted_notes = new_notes,
        changes_applied = true,
      }
    end)

    if not mutation_ok then
      reaper.MIDI_SetAllEvts(take, before_events)
      finalize_midi_take_mutation(project, take)
      error(result_or_error)
    end
    return result_or_error
  end,
}

COMMANDS.update_midi_note = {
  mutates_project = true,
  preflight_handler = function(envelope)
    local project = current_project()
    local take = require_midi_take_by_guid(project, envelope.args.take_guid)
    require_midi_note_identity(take, envelope.args.note_identity)
    validate_midi_note(envelope.args.note)
  end,
  handler = function(envelope)
    local project = current_project()
    local take = require_midi_take_by_guid(project, envelope.args.take_guid)
    require_midi_note_identity(take, envelope.args.note_identity)
    local note = envelope.args.note
    local resolved = musical_range(project, note.start, note.length)
    local start_ppq = reaper.MIDI_GetPPQPosFromProjQN(take, resolved.start_qn)
    local end_ppq = reaper.MIDI_GetPPQPosFromProjQN(take, resolved.end_qn)
    local updated = reaper.MIDI_SetNote(
      take,
      envelope.args.note_identity.index,
      note.selected or false,
      note.muted or false,
      start_ppq,
      end_ppq,
      note.channel or 0,
      note.pitch,
      note.velocity or 96,
      true
    )
    if not updated then
      error("midi_note_conflict: REAPER rejected MIDI note update")
    end
    finalize_midi_take_mutation(project, take)
    local notes = midi_notes(project, take)
    local updated_note = nil
    for _, current_note in ipairs(notes) do
      if
        current_note.pitch == note.pitch
        and current_note.channel == (note.channel or 0)
        and math.floor(current_note.start_ppq + 0.5) == math.floor(start_ppq + 0.5)
        and math.floor(current_note.end_ppq + 0.5) == math.floor(end_ppq + 0.5)
      then
        updated_note = current_note
        break
      end
    end
    return {
      take_guid = envelope.args.take_guid,
      updated_note = updated_note or midi_note_snapshot(project, take, envelope.args.note_identity.index),
      notes = notes,
      note_count = #notes,
      changes_applied = true,
    }
  end,
}

COMMANDS.delete_midi_notes = {
  mutates_project = true,
  preflight_handler = function(envelope)
    local project = current_project()
    local take = require_midi_take_by_guid(project, envelope.args.take_guid)
    validate_midi_note_identities(take, envelope.args.notes)
  end,
  handler = function(envelope)
    local project = current_project()
    local take = require_midi_take_by_guid(project, envelope.args.take_guid)
    validate_midi_note_identities(take, envelope.args.notes)
    table.sort(envelope.args.notes, function(left, right)
      return left.index > right.index
    end)
    local deleted_count = 0
    for _, identity in ipairs(envelope.args.notes) do
      local deleted = reaper.MIDI_DeleteNote(take, identity.index)
      if not deleted then
        error("midi_note_conflict: REAPER rejected MIDI note delete")
      end
      deleted_count = deleted_count + 1
    end
    finalize_midi_take_mutation(project, take)
    local notes = midi_notes(project, take)
    return {
      take_guid = envelope.args.take_guid,
      notes = notes,
      note_count = #notes,
      deleted_count = deleted_count,
      changes_applied = true,
    }
  end,
}

COMMANDS.get_midi_controller_events = {
  mutates_project = false,
  handler = function(envelope)
    local project = current_project()
    local take = require_midi_take_by_guid(project, envelope.args.take_guid)
    return MIDI_CONTROLLER.result(project, take, envelope.args.take_guid)
  end,
}

COMMANDS.add_midi_controller_events = {
  mutates_project = true,
  preflight_handler = function(envelope)
    local project = current_project()
    local take = require_midi_take_by_guid(project, envelope.args.take_guid)
    if type(envelope.args.events) ~= "table" or #envelope.args.events == 0 then
      error("invalid_midi_controller_request: events must be a non-empty array")
    end
    for _, event in ipairs(envelope.args.events) do
      MIDI_CONTROLLER.validate_event(event)
    end
    MIDI_CONTROLLER.require_distinct_insertions(project, take, envelope.args.events)
  end,
  handler = function(envelope)
    local project = current_project()
    local take = require_midi_take_by_guid(project, envelope.args.take_guid)
    MIDI_CONTROLLER.require_distinct_insertions(project, take, envelope.args.events)
    local snapshot_ok, before_events = reaper.MIDI_GetAllEvts(take, "")
    if not snapshot_ok then
      error("midi_controller_insert_failed: REAPER could not snapshot the MIDI take")
    end
    local mutation_ok, result_or_error = pcall(function()
      for _, event in ipairs(envelope.args.events) do
        local position_qn = musical_position(project, event.position).start_qn
        local position_ppq = reaper.MIDI_GetPPQPosFromProjQN(take, position_qn)
        local chanmsg, msg2, msg3 = MIDI_CONTROLLER.event_spec(event)
        local inserted = reaper.MIDI_InsertCC(
          take,
          event.selected or false,
          event.muted or false,
          position_ppq,
          chanmsg,
          event.channel or 0,
          msg2,
          msg3
        )
        if not inserted then
          error("midi_controller_insert_failed: REAPER rejected controller event")
        end
      end
      finalize_midi_take_mutation(project, take)
      local result = MIDI_CONTROLLER.result(project, take, envelope.args.take_guid)
      result.inserted_count = #envelope.args.events
      result.inserted_events = {}
      for _, requested in ipairs(envelope.args.events) do
        local position_qn = musical_position(project, requested.position).start_qn
        local position_ppq = reaper.MIDI_GetPPQPosFromProjQN(take, position_qn)
        local requested_key = MIDI_CONTROLLER.event_key(requested, position_ppq)
        for _, current_event in ipairs(result.events) do
          if MIDI_CONTROLLER.snapshot_key(current_event) == requested_key then
            result.inserted_events[#result.inserted_events + 1] = current_event
            break
          end
        end
      end
      result.changes_applied = true
      return result
    end)
    if not mutation_ok then
      reaper.MIDI_SetAllEvts(take, before_events)
      finalize_midi_take_mutation(project, take)
      error(result_or_error)
    end
    return result_or_error
  end,
}

COMMANDS.update_midi_controller_event = {
  mutates_project = true,
  preflight_handler = function(envelope)
    local project = current_project()
    local take = require_midi_take_by_guid(project, envelope.args.take_guid)
    MIDI_CONTROLLER.require_identity(take, envelope.args.identity)
    MIDI_CONTROLLER.validate_event(envelope.args.event)
  end,
  handler = function(envelope)
    local project = current_project()
    local take = require_midi_take_by_guid(project, envelope.args.take_guid)
    MIDI_CONTROLLER.require_identity(take, envelope.args.identity)
    local event = envelope.args.event
    local position_qn = musical_position(project, event.position).start_qn
    local position_ppq = reaper.MIDI_GetPPQPosFromProjQN(take, position_qn)
    local chanmsg, msg2, msg3 = MIDI_CONTROLLER.event_spec(event)
    local updated = reaper.MIDI_SetCC(
      take,
      envelope.args.identity.index,
      event.selected or false,
      event.muted or false,
      position_ppq,
      chanmsg,
      event.channel or 0,
      msg2,
      msg3,
      true
    )
    if not updated then
      error("midi_controller_conflict: REAPER rejected controller update")
    end
    finalize_midi_take_mutation(project, take)
    local result = MIDI_CONTROLLER.result(project, take, envelope.args.take_guid)
    local updated_event = MIDI_CONTROLLER.event_snapshot(project, take, envelope.args.identity.index)
    if not updated_event then
      error("midi_controller_conflict: updated controller event was not returned")
    end
    result.updated_event = updated_event
    result.changes_applied = true
    return result
  end,
}

COMMANDS.delete_midi_controller_events = {
  mutates_project = true,
  preflight_handler = function(envelope)
    local project = current_project()
    local take = require_midi_take_by_guid(project, envelope.args.take_guid)
    if type(envelope.args.events) ~= "table" or #envelope.args.events == 0 then
      error("invalid_midi_controller_request: events must be a non-empty array")
    end
    for _, identity in ipairs(envelope.args.events) do
      MIDI_CONTROLLER.require_identity(take, identity)
    end
  end,
  handler = function(envelope)
    local project = current_project()
    local take = require_midi_take_by_guid(project, envelope.args.take_guid)
    for _, identity in ipairs(envelope.args.events) do
      MIDI_CONTROLLER.require_identity(take, identity)
    end
    table.sort(envelope.args.events, function(left, right)
      return left.index > right.index
    end)
    local deleted_count = 0
    for _, identity in ipairs(envelope.args.events) do
      if not reaper.MIDI_DeleteCC(take, identity.index) then
        error("midi_controller_conflict: REAPER rejected controller delete")
      end
      deleted_count = deleted_count + 1
    end
    finalize_midi_take_mutation(project, take)
    local result = MIDI_CONTROLLER.result(project, take, envelope.args.take_guid)
    result.deleted_count = deleted_count
    result.changes_applied = true
    return result
  end,
}

do
local MIDI_TRANSFORM_EPSILON = 0.000000001
local MIDI_SCALE_INTERVALS = {
  major = { 0, 2, 4, 5, 7, 9, 11 },
  natural_minor = { 0, 2, 3, 5, 7, 8, 10 },
  harmonic_minor = { 0, 2, 3, 5, 7, 8, 11 },
  dorian = { 0, 2, 3, 5, 7, 9, 10 },
  mixolydian = { 0, 2, 4, 5, 7, 9, 10 },
  major_pentatonic = { 0, 2, 4, 7, 9 },
  minor_pentatonic = { 0, 3, 5, 7, 10 },
  blues = { 0, 3, 5, 6, 7, 10 },
  chromatic = { 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11 },
}

local function require_transform_number(value, field_name, minimum, maximum)
  if type(value) ~= "number" or value < minimum or value > maximum then
    error(
      "invalid_midi_note_request: "
      .. field_name
      .. " must be between "
      .. tostring(minimum)
      .. " and "
      .. tostring(maximum)
    )
  end
end

local function midi_transform_targets(take, identities)
  validate_midi_note_identities(take, identities)
  local targets = {}
  for _, identity in ipairs(identities) do
    targets[#targets + 1] = require_midi_note_identity(take, identity)
  end
  return targets
end

local function midi_take_qn_bounds(project, take)
  local item = reaper.GetMediaItemTake_Item(take)
  if not item then
    error("invalid_midi_note_request: MIDI take has no media item")
  end
  local item_start = safe_number_call(reaper.GetMediaItemInfo_Value, 0, item, "D_POSITION")
  local item_length = safe_number_call(reaper.GetMediaItemInfo_Value, 0, item, "D_LENGTH")
  return {
    start_qn = reaper.TimeMap2_timeToQN(project, item_start),
    end_qn = reaper.TimeMap2_timeToQN(project, item_start + item_length),
  }
end

local function validate_transformed_timing(bounds, start_qn, end_qn)
  if start_qn < bounds.start_qn - MIDI_TRANSFORM_EPSILON then
    error("invalid_midi_note_request: transformed note would start before its media item")
  end
  if end_qn > bounds.end_qn + MIDI_TRANSFORM_EPSILON then
    error("invalid_midi_note_request: transformed note would end after its media item")
  end
  if end_qn <= start_qn + MIDI_TRANSFORM_EPSILON then
    error("invalid_midi_note_request: transformed note must retain a positive duration")
  end
end

local function append_midi_transform_change(
  changes,
  note,
  start_qn,
  end_qn,
  pitch,
  velocity
)
  local changed = math.abs(note.start_qn - start_qn) > MIDI_TRANSFORM_EPSILON
    or math.abs(note.end_qn - end_qn) > MIDI_TRANSFORM_EPSILON
    or note.pitch ~= pitch
    or note.velocity ~= velocity
  if changed then
    changes[#changes + 1] = {
      index = note.index,
      start_qn = start_qn,
      end_qn = end_qn,
      pitch = pitch,
      velocity = velocity,
      before = note,
    }
  end
end

local function require_nonempty_transform(changes)
  if #changes == 0 then
    error("invalid_midi_note_request: transform would not change any targeted notes")
  end
  return changes
end

local function transpose_midi_plan(project, take, args)
  require_transform_number(args.semitones, "semitones", -127, 127)
  if args.semitones == 0 or args.semitones % 1 ~= 0 then
    error("invalid_midi_note_request: semitones must be a non-zero integer")
  end
  local changes = {}
  for _, note in ipairs(midi_transform_targets(take, args.notes)) do
    local pitch = note.pitch + args.semitones
    if pitch < 0 or pitch > 127 then
      error("invalid_midi_note_request: transpose would move a pitch outside 0 to 127")
    end
    append_midi_transform_change(
      changes,
      note,
      note.start_qn,
      note.end_qn,
      pitch,
      note.velocity
    )
  end
  return require_nonempty_transform(changes)
end

local function nudge_midi_plan(project, take, args)
  require_transform_number(args.offset_beats, "offset_beats", -64, 64)
  if args.offset_beats == 0 then
    error("invalid_midi_note_request: offset_beats must not be zero")
  end
  local bounds = midi_take_qn_bounds(project, take)
  local changes = {}
  for _, note in ipairs(midi_transform_targets(take, args.notes)) do
    local start_qn = note.start_qn + args.offset_beats
    local end_qn = note.end_qn + args.offset_beats
    validate_transformed_timing(bounds, start_qn, end_qn)
    append_midi_transform_change(
      changes,
      note,
      start_qn,
      end_qn,
      note.pitch,
      note.velocity
    )
  end
  return require_nonempty_transform(changes)
end

local function quantized_qn(position_qn, grid_beats, swing)
  local base_index = math.floor(position_qn / grid_beats)
  local best_position = nil
  local best_distance = nil
  for grid_index = math.max(0, base_index - 2), base_index + 2 do
    local candidate = grid_index * grid_beats
    if grid_index % 2 == 1 then
      candidate = candidate + (swing * grid_beats / 3)
    end
    local distance = math.abs(position_qn - candidate)
    if best_distance == nil
      or distance < best_distance - MIDI_TRANSFORM_EPSILON
      or (
        math.abs(distance - best_distance) <= MIDI_TRANSFORM_EPSILON
        and candidate < best_position
      ) then
      best_position = candidate
      best_distance = distance
    end
  end
  return best_position
end

local function quantize_midi_plan(project, take, args)
  require_transform_number(args.grid_beats, "grid_beats", MIDI_TRANSFORM_EPSILON, 16)
  require_transform_number(args.strength, "strength", MIDI_TRANSFORM_EPSILON, 1)
  require_transform_number(args.swing, "swing", 0, 1)
  local bounds = midi_take_qn_bounds(project, take)
  local changes = {}
  for _, note in ipairs(midi_transform_targets(take, args.notes)) do
    local target_qn = quantized_qn(note.start_qn, args.grid_beats, args.swing)
    local start_qn = note.start_qn + ((target_qn - note.start_qn) * args.strength)
    local end_qn = note.end_qn + (start_qn - note.start_qn)
    validate_transformed_timing(bounds, start_qn, end_qn)
    append_midi_transform_change(
      changes,
      note,
      start_qn,
      end_qn,
      note.pitch,
      note.velocity
    )
  end
  return require_nonempty_transform(changes)
end

local function clamp(value, minimum, maximum)
  return math.max(minimum, math.min(maximum, value))
end

local function humanize_midi_plan(project, take, args)
  require_transform_number(
    args.max_timing_offset_beats,
    "max_timing_offset_beats",
    0,
    1
  )
  require_transform_number(args.max_velocity_offset, "max_velocity_offset", 0, 64)
  local targets = midi_transform_targets(take, args.notes)
  if type(args.timing_offsets) ~= "table" or #args.timing_offsets ~= #targets then
    error("invalid_midi_note_request: timing_offsets must match the target count")
  end
  if type(args.velocity_offsets) ~= "table" or #args.velocity_offsets ~= #targets then
    error("invalid_midi_note_request: velocity_offsets must match the target count")
  end

  local bounds = midi_take_qn_bounds(project, take)
  local changes = {}
  for target_index, note in ipairs(targets) do
    local timing_offset = args.timing_offsets[target_index]
    local velocity_offset = args.velocity_offsets[target_index]
    require_transform_number(
      timing_offset,
      "timing offset",
      -args.max_timing_offset_beats,
      args.max_timing_offset_beats
    )
    require_transform_number(
      velocity_offset,
      "velocity offset",
      -args.max_velocity_offset,
      args.max_velocity_offset
    )
    if velocity_offset % 1 ~= 0 then
      error("invalid_midi_note_request: velocity offsets must be integers")
    end

    local duration_qn = note.end_qn - note.start_qn
    local start_qn = clamp(
      note.start_qn + timing_offset,
      bounds.start_qn,
      bounds.end_qn - duration_qn
    )
    local end_qn = start_qn + duration_qn
    local velocity = clamp(note.velocity + velocity_offset, 1, 127)
    validate_transformed_timing(bounds, start_qn, end_qn)
    append_midi_transform_change(
      changes,
      note,
      start_qn,
      end_qn,
      note.pitch,
      velocity
    )
  end
  return require_nonempty_transform(changes)
end

local function scale_pitch_classes(root_pitch_class, intervals)
  local pitch_classes = {}
  for _, interval in ipairs(intervals) do
    pitch_classes[(root_pitch_class + interval) % 12] = true
  end
  return pitch_classes
end

local function snapped_scale_pitch(pitch, pitch_classes, direction)
  if pitch_classes[pitch % 12] then
    return pitch
  end
  for distance = 1, 127 do
    local lower = pitch - distance
    local upper = pitch + distance
    if direction ~= "up" and lower >= 0 and pitch_classes[lower % 12] then
      return lower
    end
    if direction ~= "down" and upper <= 127 and pitch_classes[upper % 12] then
      return upper
    end
  end
  error("invalid_midi_note_request: scale direction has no valid MIDI pitch")
end

local function snap_midi_scale_plan(project, take, args)
  require_transform_number(args.root_pitch_class, "root_pitch_class", 0, 11)
  if args.root_pitch_class % 1 ~= 0 then
    error("invalid_midi_note_request: root_pitch_class must be an integer")
  end
  local intervals = MIDI_SCALE_INTERVALS[args.scale]
  if not intervals then
    error("invalid_midi_note_request: scale is not supported")
  end
  if args.direction ~= "nearest" and args.direction ~= "up" and args.direction ~= "down" then
    error("invalid_midi_note_request: direction must be nearest, up, or down")
  end
  local pitch_classes = scale_pitch_classes(args.root_pitch_class, intervals)
  local changes = {}
  for _, note in ipairs(midi_transform_targets(take, args.notes)) do
    append_midi_transform_change(
      changes,
      note,
      note.start_qn,
      note.end_qn,
      snapped_scale_pitch(note.pitch, pitch_classes, args.direction),
      note.velocity
    )
  end
  return require_nonempty_transform(changes)
end

local function shape_midi_velocity_plan(project, take, args)
  require_transform_number(args.factor, "factor", 0, 4)
  require_transform_number(args.offset, "offset", -127, 127)
  if args.factor == 1 and args.offset == 0 then
    error("invalid_midi_note_request: velocity shape would not change notes")
  end
  if args.offset % 1 ~= 0 then
    error("invalid_midi_note_request: offset must be an integer")
  end
  local changes = {}
  for _, note in ipairs(midi_transform_targets(take, args.notes)) do
    local velocity = clamp(math.floor((note.velocity * args.factor) + 0.5) + args.offset, 1, 127)
    append_midi_transform_change(
      changes,
      note,
      note.start_qn,
      note.end_qn,
      note.pitch,
      velocity
    )
  end
  return require_nonempty_transform(changes)
end

local function remove_midi_overlaps_plan(project, take, args)
  local groups = {}
  for _, note in ipairs(midi_transform_targets(take, args.notes)) do
    local key = tostring(note.channel) .. ":" .. tostring(note.pitch)
    groups[key] = groups[key] or {}
    groups[key][#groups[key] + 1] = note
  end

  local changes = {}
  for _, group in pairs(groups) do
    table.sort(group, function(left, right)
      if left.start_qn == right.start_qn then
        return left.index < right.index
      end
      return left.start_qn < right.start_qn
    end)
    for index = 1, #group - 1 do
      local current = group[index]
      local next_note = group[index + 1]
      if current.end_qn > next_note.start_qn + MIDI_TRANSFORM_EPSILON then
        if next_note.start_qn <= current.start_qn + MIDI_TRANSFORM_EPSILON then
          error(
            "invalid_midi_note_request: same-onset overlaps cannot be trimmed without deletion"
          )
        end
        append_midi_transform_change(
          changes,
          current,
          current.start_qn,
          next_note.start_qn,
          current.pitch,
          current.velocity
        )
      end
    end
  end
  return require_nonempty_transform(changes)
end

local function rollback_midi_transform_changes(take, applied_changes)
  for index = #applied_changes, 1, -1 do
    local change = applied_changes[index]
    local before = change.before
    reaper.MIDI_SetNote(
      take,
      change.index,
      before.selected,
      before.muted,
      before.start_ppq,
      before.end_ppq,
      before.channel,
      before.pitch,
      before.velocity,
      true
    )
  end
  reaper.MIDI_Sort(take)
end

local function apply_midi_transform_plan(project, take, changes)
  local applied_changes = {}
  for _, change in ipairs(changes) do
    local updated = reaper.MIDI_SetNote(
      take,
      change.index,
      nil,
      nil,
      reaper.MIDI_GetPPQPosFromProjQN(take, change.start_qn),
      reaper.MIDI_GetPPQPosFromProjQN(take, change.end_qn),
      nil,
      change.pitch,
      change.velocity,
      true
    )
    if not updated then
      rollback_midi_transform_changes(take, applied_changes)
      error("midi_note_conflict: REAPER rejected a planned MIDI note transform")
    end
    applied_changes[#applied_changes + 1] = change
  end
  finalize_midi_take_mutation(project, take)
end

local function midi_transform_command(plan_builder)
  return {
    mutates_project = true,
    preflight_handler = function(envelope)
      local project = current_project()
      local take = require_midi_take_by_guid(project, envelope.args.take_guid)
      plan_builder(project, take, envelope.args)
    end,
    handler = function(envelope)
      local project = current_project()
      local take = require_midi_take_by_guid(project, envelope.args.take_guid)
      local changes = plan_builder(project, take, envelope.args)
      apply_midi_transform_plan(project, take, changes)
      local notes = midi_notes(project, take)
      return {
        take_guid = envelope.args.take_guid,
        notes = notes,
        note_count = #notes,
        transformed_count = #changes,
        changes_applied = true,
      }
    end,
  }
end

COMMANDS.transpose_midi_notes = midi_transform_command(transpose_midi_plan)
COMMANDS.nudge_midi_notes = midi_transform_command(nudge_midi_plan)
COMMANDS.quantize_midi_notes = midi_transform_command(quantize_midi_plan)
COMMANDS.humanize_midi_notes = midi_transform_command(humanize_midi_plan)
COMMANDS.snap_midi_notes_to_scale = midi_transform_command(snap_midi_scale_plan)
COMMANDS.shape_midi_note_velocities = midi_transform_command(shape_midi_velocity_plan)
COMMANDS.remove_midi_note_overlaps = midi_transform_command(remove_midi_overlaps_plan)
end
