COMMANDS.get_project_snapshot = {
  mutates_project = false,
  handler = function()
    local project, path = current_project()
    local bpm, beats_per_measure = project_time_signature(project)
    local tracks, selected_track_guids = project_tracks(project)
    local markers, regions = project_markers_and_regions(project)
    return {
      project = {
        path = path,
        name = project_name(project, path),
        dirty = safe_number_call(reaper.IsProjectDirty, 0, project) ~= 0,
        state_change_count = safe_number_call(
          reaper.GetProjectStateChangeCount,
          0,
          project
        ),
      },
      tempo = {
        bpm = bpm,
        beats_per_measure = beats_per_measure,
      },
      transport = {
        play_state = safe_number_call(reaper.GetPlayState, 0),
      },
      tracks = tracks,
      markers = markers,
      regions = regions,
      selected_track_guids = selected_track_guids,
    }
  end,
}

COMMANDS.list_tracks = {
  mutates_project = false,
  handler = function()
    local project = current_project()
    local tracks = project_tracks(project)
    return {
      tracks = tracks,
      track_count = #tracks,
    }
  end,
}

local function create_track_preview(args)
  local project = current_project()
  local track_count = safe_number_call(reaper.CountTracks, 0, project)
  local requested_index = args.index
  local visible_index = requested_index or (track_count + 1)
  return {
    dry_run = true,
    changes_applied = false,
    track = {
      guid = "",
      name = args.name or "Track",
      index = visible_index,
      color = args.color or 0,
      mute = false,
      solo = false,
      armed = false,
      selected = false,
      media_item_count = 0,
    },
    track_count = track_count,
  }
end

COMMANDS.create_track = {
  mutates_project = true,
  dry_run_handler = function(envelope)
    return create_track_preview(envelope.args)
  end,
  preflight_handler = function(envelope)
    local args = envelope.args
    local project = current_project()
    local track_count = safe_number_call(reaper.CountTracks, 0, project)
    local visible_index = args.index or (track_count + 1)
    if visible_index < 1 or visible_index > track_count + 1 then
      error("Track index must be between 1 and " .. tostring(track_count + 1))
    end
  end,
  handler = function(envelope)
    local args = envelope.args
    local project = current_project()
    local track_count = safe_number_call(reaper.CountTracks, 0, project)
    local visible_index = args.index or (track_count + 1)
    if visible_index < 1 or visible_index > track_count + 1 then
      error("Track index must be between 1 and " .. tostring(track_count + 1))
    end

    local insert_index = visible_index - 1
    reaper.InsertTrackAtIndex(insert_index, true)
    local track = reaper.GetTrack(project, insert_index)
    if not track then
      error("REAPER did not return the created track")
    end

    reaper.GetSetMediaTrackInfo_String(track, "P_NAME", args.name or "Track", true)
    if args.color ~= nil then
      reaper.SetTrackColor(track, args.color)
    end
    reaper.TrackList_AdjustWindows(false)
    reaper.UpdateArrange()

    local snapshot = track_snapshot(track)
    require_postconditions(
      "created track",
      snapshot,
      { name = args.name or "Track", color = args.color }
    )
    return {
      track = snapshot,
      track_count = safe_number_call(reaper.CountTracks, 0, project),
      dry_run = false,
      changes_applied = true,
    }
  end,
}

COMMANDS.rename_track = {
  mutates_project = true,
  preflight_handler = function(envelope)
    local project = current_project()
    require_track_by_guid(project, envelope.args.track_guid)
  end,
  handler = function(envelope)
    local args = envelope.args
    local project = current_project()
    local track = require_track_by_guid(project, args.track_guid)
    reaper.GetSetMediaTrackInfo_String(track, "P_NAME", args.name or "", true)
    return track_mutation_result(project, track, { name = args.name or "" })
  end,
}

COMMANDS.set_track_color = {
  mutates_project = true,
  preflight_handler = function(envelope)
    local project = current_project()
    require_track_by_guid(project, envelope.args.track_guid)
  end,
  handler = function(envelope)
    local args = envelope.args
    local project = current_project()
    local track = require_track_by_guid(project, args.track_guid)
    reaper.SetTrackColor(track, args.color or 0)
    return track_mutation_result(project, track, { color = args.color or 0 })
  end,
}

COMMANDS.set_track_mute = {
  mutates_project = true,
  preflight_handler = function(envelope)
    local project = current_project()
    require_track_by_guid(project, envelope.args.track_guid)
  end,
  handler = function(envelope)
    local args = envelope.args
    local project = current_project()
    local track = require_track_by_guid(project, args.track_guid)
    reaper.SetMediaTrackInfo_Value(track, "B_MUTE", args.muted and 1 or 0)
    return track_mutation_result(project, track, { mute = args.muted })
  end,
}

COMMANDS.set_track_solo = {
  mutates_project = true,
  preflight_handler = function(envelope)
    local project = current_project()
    require_track_by_guid(project, envelope.args.track_guid)
  end,
  handler = function(envelope)
    local args = envelope.args
    local project = current_project()
    local track = require_track_by_guid(project, args.track_guid)
    reaper.SetMediaTrackInfo_Value(track, "I_SOLO", args.soloed and 1 or 0)
    return track_mutation_result(project, track, { solo = args.soloed })
  end,
}

COMMANDS.set_track_arm = {
  mutates_project = true,
  preflight_handler = function(envelope)
    local project = current_project()
    require_track_by_guid(project, envelope.args.track_guid)
  end,
  handler = function(envelope)
    local args = envelope.args
    local project = current_project()
    local track = require_track_by_guid(project, args.track_guid)
    reaper.SetMediaTrackInfo_Value(track, "I_RECARM", args.armed and 1 or 0)
    return track_mutation_result(project, track, { armed = args.armed })
  end,
}

COMMANDS.set_track_volume = {
  mutates_project = true,
  preflight_handler = function(envelope)
    local project = current_project()
    require_track_by_guid(project, envelope.args.track_guid)
  end,
  handler = function(envelope)
    local args = envelope.args
    local project = current_project()
    local track = require_track_by_guid(project, args.track_guid)
    reaper.SetMediaTrackInfo_Value(track, "D_VOL", args.volume)
    return track_mutation_result(project, track, { volume = args.volume })
  end,
}

COMMANDS.set_track_pan = {
  mutates_project = true,
  preflight_handler = function(envelope)
    local project = current_project()
    require_track_by_guid(project, envelope.args.track_guid)
  end,
  handler = function(envelope)
    local args = envelope.args
    local project = current_project()
    local track = require_track_by_guid(project, args.track_guid)
    reaper.SetMediaTrackInfo_Value(track, "D_PAN", args.pan)
    return track_mutation_result(project, track, { pan = args.pan })
  end,
}

COMMANDS.set_track_recording = {
  mutates_project = true,
  preflight_handler = function(envelope)
    local project = current_project()
    require_track_by_guid(project, envelope.args.track_guid)
    if type(envelope.args.recording_input) ~= "number"
        or envelope.args.recording_input < -1 or envelope.args.recording_input > 256 then
      error("invalid_track_request: recording_input must be between -1 and 256")
    end
    if type(envelope.args.input_monitoring) ~= "boolean" then
      error("invalid_track_request: input_monitoring must be boolean")
    end
  end,
  handler = function(envelope)
    local project = current_project()
    local track = require_track_by_guid(project, envelope.args.track_guid)
    reaper.SetMediaTrackInfo_Value(track, "I_RECINPUT", envelope.args.recording_input)
    reaper.SetMediaTrackInfo_Value(track, "I_RECMON", envelope.args.input_monitoring and 1 or 0)
    return track_mutation_result(
      project,
      track,
      {
        recording_input = envelope.args.recording_input,
        input_monitoring = envelope.args.input_monitoring,
      }
    )
  end,
}

COMMANDS.set_track_folder_depth = {
  mutates_project = true,
  preflight_handler = function(envelope)
    local project = current_project()
    require_track_by_guid(project, envelope.args.track_guid)
    if type(envelope.args.folder_depth) ~= "number"
        or envelope.args.folder_depth < -1 or envelope.args.folder_depth > 1 then
      error("invalid_track_request: folder_depth must be -1, 0, or 1")
    end
  end,
  handler = function(envelope)
    local project = current_project()
    local track = require_track_by_guid(project, envelope.args.track_guid)
    reaper.SetMediaTrackInfo_Value(track, "I_FOLDERDEPTH", envelope.args.folder_depth)
    reaper.TrackList_AdjustWindows(false)
    reaper.UpdateArrange()
    return track_mutation_result(
      project,
      track,
      { folder_depth = envelope.args.folder_depth }
    )
  end,
}

local function validate_batch_track_change(change)
  if type(change) ~= "table" or type(change.track_guid) ~= "string" or change.track_guid == "" then
    error("invalid_track_request: each batch change needs a track_guid")
  end
  local has_change = change.name ~= nil or change.color ~= nil or change.muted ~= nil
    or change.soloed ~= nil or change.armed ~= nil or change.volume ~= nil or change.pan ~= nil
  if not has_change then
    error("invalid_track_request: each batch change must set a property")
  end
  if change.name ~= nil and (type(change.name) ~= "string" or change.name == "") then
    error("invalid_track_request: track name must be non-empty")
  end
  if change.color ~= nil and (type(change.color) ~= "number" or change.color < 0) then
    error("invalid_track_request: track color must be >= 0")
  end
  if change.volume ~= nil and (type(change.volume) ~= "number" or change.volume < 0 or change.volume > 4) then
    error("invalid_track_request: track volume must be between 0 and 4")
  end
  if change.pan ~= nil and (type(change.pan) ~= "number" or change.pan < -1 or change.pan > 1) then
    error("invalid_track_request: track pan must be between -1 and 1")
  end
  for _, field in ipairs({"muted", "soloed", "armed"}) do
    if change[field] ~= nil and type(change[field]) ~= "boolean" then
      error("invalid_track_request: batch track state must be boolean")
    end
  end
end

COMMANDS.batch_update_tracks = {
  mutates_project = true,
  preflight_handler = function(envelope)
    local project = current_project()
    if type(envelope.args.changes) ~= "table" or #envelope.args.changes == 0 then
      error("invalid_track_request: changes must be a non-empty array")
    end
    if #envelope.args.changes > 64 then
      error("invalid_track_request: changes cannot contain more than 64 tracks")
    end
    local seen = {}
    for _, change in ipairs(envelope.args.changes) do
      validate_batch_track_change(change)
      if seen[change.track_guid] then
        error("invalid_track_request: duplicate track GUID in batch")
      end
      seen[change.track_guid] = true
      require_track_by_guid(project, change.track_guid)
    end
  end,
  handler = function(envelope)
    local project = current_project()
    local previous = {}
    for _, change in ipairs(envelope.args.changes) do
      local track = require_track_by_guid(project, change.track_guid)
      local _, previous_name = reaper.GetTrackName(track, "")
      previous[track] = {
        name = previous_name or "",
        color = reaper.GetTrackColor(track),
        mute = reaper.GetMediaTrackInfo_Value(track, "B_MUTE"),
        solo = reaper.GetMediaTrackInfo_Value(track, "I_SOLO"),
        armed = reaper.GetMediaTrackInfo_Value(track, "I_RECARM"),
        volume = reaper.GetMediaTrackInfo_Value(track, "D_VOL"),
        pan = reaper.GetMediaTrackInfo_Value(track, "D_PAN"),
      }
    end
    local mutation_ok, result_or_error = pcall(function()
      for _, change in ipairs(envelope.args.changes) do
        local track = require_track_by_guid(project, change.track_guid)
        if change.name ~= nil then reaper.GetSetMediaTrackInfo_String(track, "P_NAME", change.name, true) end
        if change.color ~= nil then reaper.SetTrackColor(track, change.color) end
        if change.muted ~= nil then reaper.SetMediaTrackInfo_Value(track, "B_MUTE", change.muted and 1 or 0) end
        if change.soloed ~= nil then reaper.SetMediaTrackInfo_Value(track, "I_SOLO", change.soloed and 1 or 0) end
        if change.armed ~= nil then reaper.SetMediaTrackInfo_Value(track, "I_RECARM", change.armed and 1 or 0) end
        if change.volume ~= nil then reaper.SetMediaTrackInfo_Value(track, "D_VOL", change.volume) end
        if change.pan ~= nil then reaper.SetMediaTrackInfo_Value(track, "D_PAN", change.pan) end
      end
      reaper.TrackList_AdjustWindows(false)
      reaper.UpdateArrange()
      for _, change in ipairs(envelope.args.changes) do
        local track = require_track_by_guid(project, change.track_guid)
        require_postconditions(
          "batch track",
          track_snapshot(track),
          track_expected_fields(change)
        )
      end
      local tracks = project_tracks(project)
      return {tracks = tracks, track_count = #tracks, changes_applied = true}
    end)
    if not mutation_ok then
      for track, state in pairs(previous) do
        reaper.GetSetMediaTrackInfo_String(track, "P_NAME", state.name, true)
        reaper.SetTrackColor(track, state.color)
        reaper.SetMediaTrackInfo_Value(track, "B_MUTE", state.mute)
        reaper.SetMediaTrackInfo_Value(track, "I_SOLO", state.solo)
        reaper.SetMediaTrackInfo_Value(track, "I_RECARM", state.armed)
        reaper.SetMediaTrackInfo_Value(track, "D_VOL", state.volume)
        reaper.SetMediaTrackInfo_Value(track, "D_PAN", state.pan)
      end
      reaper.UpdateArrange()
      error(result_or_error)
    end
    return result_or_error
  end,
}

COMMANDS.delete_track = {
  mutates_project = true,
  preflight_handler = function(envelope)
    local project = current_project()
    require_track_by_guid(project, envelope.args.track_guid)
  end,
  handler = function(envelope)
    local args = envelope.args
    local project = current_project()
    local track = require_track_by_guid(project, args.track_guid)
    reaper.DeleteTrack(track)
    reaper.TrackList_AdjustWindows(false)
    reaper.UpdateArrange()
    if find_track_by_guid(project, args.track_guid) then
      error("postcondition_failed: deleted track is still present")
    end
    return {
      deleted_track_guid = args.track_guid,
      track_count = safe_number_call(reaper.CountTracks, 0, project),
      changes_applied = true,
    }
  end,
}

local function require_template_path(path)
  if type(path) ~= "string" or path == "" then
    error("template_path_not_allowed: template_path must be a non-empty string")
  end
  if not path:lower():match("%.rtracktemplate$") then
    error("template_path_not_allowed: template path must use .RTrackTemplate")
  end
  return path
end

COMMANDS.save_track_template = {
  mutates_project = false,
  preflight_handler = function(envelope)
    require_track_by_guid(current_project(), envelope.args.track_guid)
    require_template_path(envelope.args.template_path)
  end,
  handler = function(envelope)
    local project = current_project()
    local track = require_track_by_guid(project, envelope.args.track_guid)
    local path = require_template_path(envelope.args.template_path)
    local ok, chunk = reaper.GetTrackStateChunk(track, "", 10485760, false)
    if not ok or type(chunk) ~= "string" or chunk == "" then
      error("template_path_not_allowed: REAPER could not read the track state")
    end
    local file = io.open(path, "wb")
    if not file then
      error("template_path_not_allowed: could not write the template path")
    end
    file:write(chunk)
    file:close()
    return {
      template_path = path,
      track_count = safe_number_call(reaper.CountTracks, 0, project),
      changes_applied = false,
    }
  end,
}

COMMANDS.apply_track_template = {
  mutates_project = true,
  preflight_handler = function(envelope)
    require_template_path(envelope.args.template_path)
    if envelope.args.index ~= nil and (type(envelope.args.index) ~= "number" or envelope.args.index < 1) then
      error("invalid_track_request: template index must be >= 1")
    end
    local file = io.open(envelope.args.template_path, "rb")
    if not file then
      error("template_path_not_allowed: template file does not exist")
    end
    file:close()
  end,
  handler = function(envelope)
    local project = current_project()
    local file = io.open(envelope.args.template_path, "rb")
    if not file then
      error("template_path_not_allowed: template file does not exist")
    end
    local chunk = file:read("*a")
    file:close()
    local track_count = safe_number_call(reaper.CountTracks, 0, project)
    local visible_index = envelope.args.index or (track_count + 1)
    local insert_index = math.floor(visible_index - 1)
    if insert_index < 0 or insert_index > track_count then
      error("invalid_track_request: template index is outside the track list")
    end
    reaper.InsertTrackAtIndex(insert_index, true)
    local track = reaper.GetTrack(project, insert_index)
    local generated_guid = track and reaper.GetTrackGUID(track) or ""
    if not track or not reaper.SetTrackStateChunk(track, chunk, false) then
      error("invalid_track_request: REAPER could not apply the track template")
    end
    if generated_guid ~= "" then
      reaper.GetSetMediaTrackInfo_String(track, "GUID", generated_guid, true)
    end
    reaper.TrackList_AdjustWindows(false)
    reaper.UpdateArrange()
    return {
      template_path = envelope.args.template_path,
      track = track_snapshot(track),
      track_count = safe_number_call(reaper.CountTracks, 0, project),
      changes_applied = true,
    }
  end,
}

COMMANDS.get_master_track = {
  mutates_project = false,
  handler = function()
    local project = current_project()
    return master_track_snapshot(project)
  end,
}

COMMANDS.set_master_volume = {
  mutates_project = true,
  handler = function(envelope)
    local project = current_project()
    local master_track = reaper.GetMasterTrack(project)
    reaper.SetMediaTrackInfo_Value(master_track, "D_VOL", envelope.args.volume)
    return master_track_mutation_result(project, { volume = envelope.args.volume })
  end,
}

COMMANDS.set_master_pan = {
  mutates_project = true,
  handler = function(envelope)
    local project = current_project()
    local master_track = reaper.GetMasterTrack(project)
    reaper.SetMediaTrackInfo_Value(master_track, "D_PAN", envelope.args.pan)
    return master_track_mutation_result(project, { pan = envelope.args.pan })
  end,
}

COMMANDS.set_master_mute = {
  mutates_project = true,
  handler = function(envelope)
    local project = current_project()
    local master_track = reaper.GetMasterTrack(project)
    local muted = envelope.args.muted and 1 or 0
    reaper.SetMediaTrackInfo_Value(master_track, "B_MUTE", muted)
    return master_track_mutation_result(project, { mute = envelope.args.muted })
  end,
}

COMMANDS.list_track_sends = {
  mutates_project = false,
  handler = function(envelope)
    local project = current_project()
    local source_track_guid = envelope.args.source_track_guid
    local source_track = require_track_by_guid(project, source_track_guid)
    local sends = track_send_list(source_track, source_track_guid)
    return {
      source_track_guid = source_track_guid,
      sends = sends,
      send_count = #sends,
    }
  end,
}

COMMANDS.create_track_send = {
  mutates_project = true,
  preflight_handler = function(envelope)
    local project = current_project()
    local args = envelope.args
    require_track_by_guid(project, args.source_track_guid)
    require_track_by_guid(project, args.destination_track_guid)
    if args.source_track_guid == args.destination_track_guid then
      error("invalid_send_reference: source and destination tracks must differ")
    end
  end,
  handler = function(envelope)
    local project = current_project()
    local args = envelope.args
    local source_track = require_track_by_guid(project, args.source_track_guid)
    local destination_track = require_track_by_guid(
      project,
      args.destination_track_guid
    )
    local send_index = reaper.CreateTrackSend(source_track, destination_track)
    if type(send_index) ~= "number" or send_index < 0 then
      error("invalid_send_reference: REAPER could not create the track send")
    end
    reaper.SetTrackSendInfo_Value(source_track, 0, send_index, "D_VOL", args.volume)
    reaper.SetTrackSendInfo_Value(source_track, 0, send_index, "D_PAN", args.pan)
    reaper.SetTrackSendInfo_Value(
      source_track,
      0,
      send_index,
      "B_MUTE",
      args.muted and 1 or 0
    )
    reaper.UpdateArrange()
    return {
      send = track_send_snapshot(
        source_track,
        args.source_track_guid,
        send_index
      ),
      send_count = safe_number_call(
        reaper.GetTrackNumSends,
        0,
        source_track,
        0
      ),
      changes_applied = true,
    }
  end,
}

COMMANDS.configure_reference_track = {
  mutates_project = true,
  preflight_handler = function(envelope)
    local project = current_project()
    local args = envelope.args
    local track = require_track_by_guid(project, args.track_guid)
    if type(args.hardware_output_pair) ~= "number"
        or args.hardware_output_pair % 1 ~= 0
        or args.hardware_output_pair < 1
        or args.hardware_output_pair > 64 then
      error("invalid_send_reference: hardware_output_pair must be an integer from 1 to 64")
    end
    if type(args.volume) ~= "number" or args.volume < 0 or args.volume > 4 then
      error("invalid_send_reference: reference output volume must be between 0 and 4")
    end
    if type(args.pan) ~= "number" or args.pan < -1 or args.pan > 1 then
      error("invalid_send_reference: reference output pan must be between -1 and 1")
    end
    local destination_channel = (args.hardware_output_pair - 1) * 2
    find_hardware_output_send(track, destination_channel)
  end,
  handler = function(envelope)
    local project = current_project()
    local args = envelope.args
    local track = require_track_by_guid(project, args.track_guid)
    local destination_channel = (args.hardware_output_pair - 1) * 2
    local main_send_before = safe_number_call(
      reaper.GetMediaTrackInfo_Value,
      1,
      track,
      "B_MAINSEND"
    )
    local send_index = find_hardware_output_send(track, destination_channel)
    local hardware_send_created = false
    local previous_send = nil
    if send_index ~= nil then
      previous_send = hardware_output_snapshot(track, args.track_guid, send_index)
    end

    local mutation_ok, mutation_error = pcall(function()
      if send_index == nil then
        send_index = reaper.CreateTrackSend(track, nil)
        if type(send_index) ~= "number" or send_index < 0 then
          error("invalid_send_reference: REAPER could not create the direct hardware send")
        end
        hardware_send_created = true
      end
      reaper.SetTrackSendInfo_Value(
        track, 1, send_index, "I_DSTCHAN", destination_channel
      )
      reaper.SetTrackSendInfo_Value(track, 1, send_index, "I_SENDMODE", 0)
      reaper.SetTrackSendInfo_Value(track, 1, send_index, "D_VOL", args.volume)
      reaper.SetTrackSendInfo_Value(track, 1, send_index, "D_PAN", args.pan)
      reaper.SetTrackSendInfo_Value(track, 1, send_index, "B_MUTE", 0)
      reaper.SetMediaTrackInfo_Value(track, "B_MAINSEND", 0)

      local main_send_enabled = safe_number_call(
        reaper.GetMediaTrackInfo_Value,
        1,
        track,
        "B_MAINSEND"
      ) ~= 0
      local hardware_output = hardware_output_snapshot(
        track,
        args.track_guid,
        send_index
      )
      if main_send_enabled
          or hardware_output.hardware_output_pair ~= args.hardware_output_pair
          or math.abs(hardware_output.volume - args.volume) > 0.000001
          or math.abs(hardware_output.pan - args.pan) > 0.000001
          or hardware_output.muted
          or hardware_output.send_mode ~= 0 then
        error("postcondition_failed: reference track routing did not match")
      end
    end)

    if not mutation_ok then
      reaper.SetMediaTrackInfo_Value(track, "B_MAINSEND", main_send_before)
      if hardware_send_created and send_index ~= nil then
        reaper.RemoveTrackSend(track, 1, send_index)
      elseif previous_send and send_index ~= nil then
        reaper.SetTrackSendInfo_Value(
          track, 1, send_index, "I_DSTCHAN",
          (previous_send.hardware_output_pair - 1) * 2
        )
        reaper.SetTrackSendInfo_Value(
          track, 1, send_index, "I_SENDMODE", previous_send.send_mode
        )
        reaper.SetTrackSendInfo_Value(
          track, 1, send_index, "D_VOL", previous_send.volume
        )
        reaper.SetTrackSendInfo_Value(
          track, 1, send_index, "D_PAN", previous_send.pan
        )
        reaper.SetTrackSendInfo_Value(
          track, 1, send_index, "B_MUTE", previous_send.muted and 1 or 0
        )
      end
      reaper.UpdateArrange()
      error(mutation_error)
    end

    reaper.UpdateArrange()
    local hardware_output = hardware_output_snapshot(
      track,
      args.track_guid,
      send_index
    )
    local changes_applied = hardware_send_created
      or main_send_before ~= 0
      or not previous_send
      or math.abs(previous_send.volume - args.volume) > 0.000001
      or math.abs(previous_send.pan - args.pan) > 0.000001
      or previous_send.muted
      or previous_send.send_mode ~= 0
    return {
      track_guid = args.track_guid,
      master_send_enabled = false,
      hardware_output = hardware_output,
      hardware_send_created = hardware_send_created,
      changes_applied = changes_applied,
    }
  end,
}

COMMANDS.setup_sidechain = {
  mutates_project = true,
  preflight_handler = function(envelope)
    local project = current_project()
    require_track_by_guid(project, envelope.args.source_track_guid)
    require_track_by_guid(project, envelope.args.destination_track_guid)
    if envelope.args.source_track_guid == envelope.args.destination_track_guid then
      error("invalid_send_reference: source and destination tracks must differ")
    end
    if type(envelope.args.volume) ~= "number" or envelope.args.volume < 0 or envelope.args.volume > 4 then
      error("invalid_send_reference: sidechain amount must be between 0 and 4")
    end
  end,
  handler = function(envelope)
    local project = current_project()
    local source = require_track_by_guid(project, envelope.args.source_track_guid)
    local destination = require_track_by_guid(project, envelope.args.destination_track_guid)
    local send_index = reaper.CreateTrackSend(source, destination)
    if type(send_index) ~= "number" or send_index < 0 then
      error("invalid_send_reference: REAPER could not create the sidechain send")
    end
    reaper.SetTrackSendInfo_Value(source, 0, send_index, "D_VOL", envelope.args.volume)
    reaper.SetTrackSendInfo_Value(source, 0, send_index, "I_SRCCHAN", 0)
    reaper.SetTrackSendInfo_Value(source, 0, send_index, "I_DSTCHAN", 2)
    reaper.UpdateArrange()
    return {
      source_track_guid = envelope.args.source_track_guid,
      destination_track_guid = envelope.args.destination_track_guid,
      send = track_send_snapshot(source, envelope.args.source_track_guid, send_index),
      source_channels = "1/2",
      destination_channels = "3/4",
      changes_applied = true,
    }
  end,
}

COMMANDS.set_track_send = {
  mutates_project = true,
  preflight_handler = function(envelope)
    local project = current_project()
    require_track_send(project, envelope.args.send_identity)
  end,
  handler = function(envelope)
    local project = current_project()
    local args = envelope.args
    local source_track, send = require_track_send(project, args.send_identity)
    if args.volume ~= nil then
      reaper.SetTrackSendInfo_Value(
        source_track,
        0,
        send.index,
        "D_VOL",
        args.volume
      )
    end
    if args.pan ~= nil then
      reaper.SetTrackSendInfo_Value(
        source_track,
        0,
        send.index,
        "D_PAN",
        args.pan
      )
    end
    if args.muted ~= nil then
      reaper.SetTrackSendInfo_Value(
        source_track,
        0,
        send.index,
        "B_MUTE",
        args.muted and 1 or 0
      )
    end
    reaper.UpdateArrange()
    return {
      send = track_send_snapshot(
        source_track,
        send.source_track_guid,
        send.index
      ),
      changes_applied = true,
    }
  end,
}

COMMANDS.remove_track_send = {
  mutates_project = true,
  preflight_handler = function(envelope)
    local project = current_project()
    require_track_send(project, envelope.args.send_identity)
  end,
  handler = function(envelope)
    local project = current_project()
    local identity = envelope.args.send_identity
    local source_track, send = require_track_send(project, identity)
    if not reaper.RemoveTrackSend(source_track, 0, send.index) then
      error("invalid_send_reference: REAPER could not remove the track send")
    end
    reaper.UpdateArrange()
    return {
      source_track_guid = send.source_track_guid,
      destination_track_guid = send.destination_track_guid,
      removed_index = send.index,
      send_count = safe_number_call(
        reaper.GetTrackNumSends,
        0,
        source_track,
        0
      ),
      changes_applied = true,
    }
  end,
}

COMMANDS.get_track_freeze_state = {
  mutates_project = false,
  handler = function(envelope)
    local project = current_project()
    local track = require_track_by_guid(project, envelope.args.track_guid)
    return track_freeze_state(project, track)
  end,
}

local function run_track_freeze_action(
  project,
  track,
  action_id,
  freeze_count_before,
  is_freeze
)
  local selected_tracks = snapshot_selected_tracks(project)
  reaper.SetOnlyTrackSelected(track)
  local action_ok, action_error = pcall(reaper.Main_OnCommand, action_id, 0)
  restore_selected_tracks(project, selected_tracks)
  local selection_restored = track_selection_matches(project, selected_tracks)

  if not action_ok then
    error("track_freeze_failed: " .. tostring(action_error))
  end
  if not selection_restored then
    error("track_freeze_failed: prior track selection was not restored")
  end

  local state = track_freeze_state(project, track)
  if is_freeze and state.freeze_count <= freeze_count_before then
    error("track_freeze_failed: REAPER did not increase the freeze count")
  end
  if not is_freeze and state.freeze_count >= freeze_count_before then
    error("track_freeze_failed: REAPER did not decrease the freeze count")
  end

  reaper.TrackList_AdjustWindows(false)
  reaper.UpdateArrange()
  return {
    state = state,
    selection_restored = selection_restored,
    may_create_media_files = is_freeze,
    changes_applied = true,
  }
end

COMMANDS.freeze_track = {
  mutates_project = true,
  preflight_handler = function(envelope)
    local project = current_project()
    local track = require_track_by_guid(project, envelope.args.track_guid)
    if track_freeze_state(project, track).frozen then
      error("track_already_frozen: track already has a freeze state")
    end
  end,
  handler = function(envelope)
    local project = current_project()
    local track = require_track_by_guid(project, envelope.args.track_guid)
    local before = track_freeze_state(project, track)
    return run_track_freeze_action(project, track, 41223, before.freeze_count, true)
  end,
}

COMMANDS.unfreeze_track = {
  mutates_project = true,
  preflight_handler = function(envelope)
    local project = current_project()
    local track = require_track_by_guid(project, envelope.args.track_guid)
    if not track_freeze_state(project, track).frozen then
      error("track_not_frozen: track has no freeze state")
    end
  end,
  handler = function(envelope)
    local project = current_project()
    local track = require_track_by_guid(project, envelope.args.track_guid)
    local before = track_freeze_state(project, track)
    return run_track_freeze_action(project, track, 41644, before.freeze_count, false)
  end,
}

COMMANDS.play = {
  mutates_project = false,
  handler = function()
    reaper.OnPlayButton()
    return transport_result("play")
  end,
}

COMMANDS.stop = {
  mutates_project = false,
  handler = function()
    if transport_state().recording then
      error("recording_stop_requires_stop_recording: use stop_recording while recording")
    end
    reaper.OnStopButton()
    return transport_result("stop")
  end,
}

COMMANDS.stop_recording = {
  mutates_project = true,
  preflight_handler = function()
    if not transport_state().recording then
      error("not_recording: REAPER is not currently recording")
    end
  end,
  handler = function()
    if not transport_state().recording then
      error("not_recording: REAPER is not currently recording")
    end
    reaper.OnStopButton()
    return transport_result("stop_recording")
  end,
}

COMMANDS.pause = {
  mutates_project = false,
  handler = function()
    reaper.OnPauseButton()
    return transport_result("pause")
  end,
}

COMMANDS.record = {
  mutates_project = true,
  preflight_handler = function()
    local project = current_project()
    if armed_track_count(project) == 0 then
      error("record_requires_armed_track: at least one track must be armed")
    end
  end,
  handler = function()
    local project = current_project()
    if armed_track_count(project) == 0 then
      error("record_requires_armed_track: at least one track must be armed")
    end
    reaper.Main_OnCommand(1013, 0)
    return transport_result("record")
  end,
}

local function register_project_control_commands()
local function project_grid_snapshot(project)
  local _, division, swing_mode, swing = reaper.GetSetProjectGrid(
    project,
    false,
    0,
    0,
    0
  )
  return {
    division = division,
    swing = swing,
    swing_mode = swing_mode,
    snap_enabled = reaper.GetToggleCommandState(1157) == 1,
  }
end

local function project_control_result(action, project)
  return {
    action = action,
    changes_applied = true,
    grid = project and project_grid_snapshot(project) or nil,
  }
end

COMMANDS.undo = {
  mutates_project = false,
  handler = function()
    local project = current_project()
    reaper.Undo_DoUndo2(project)
    return project_control_result("undo", project)
  end,
}

COMMANDS.redo = {
  mutates_project = false,
  handler = function()
    local project = current_project()
    reaper.Undo_DoRedo2(project)
    return project_control_result("redo", project)
  end,
}

COMMANDS.get_grid = {
  mutates_project = false,
  handler = function()
    return {
      action = "get_grid",
      changes_applied = false,
      grid = project_grid_snapshot(current_project()),
    }
  end,
}

COMMANDS.set_grid = {
  mutates_project = false,
  preflight_handler = function(envelope)
    local args = envelope.args
    if type(args.division) ~= "number" or args.division <= 0 or args.division > 64 then
      error("invalid_navigation_request: grid division must be between 0 and 64")
    end
    if type(args.swing) ~= "number" or args.swing < -1 or args.swing > 1 then
      error("invalid_navigation_request: grid swing must be between -1 and 1")
    end
    if type(args.swing_mode) ~= "number" or args.swing_mode < 0 or args.swing_mode > 2 then
      error("invalid_navigation_request: grid swing_mode must be between 0 and 2")
    end
    if type(args.snap_enabled) ~= "boolean" then
      error("invalid_navigation_request: snap_enabled must be boolean")
    end
  end,
  handler = function(envelope)
    local project = current_project()
    local args = envelope.args
    reaper.GetSetProjectGrid(
      project,
      true,
      args.division,
      args.swing_mode,
      args.swing
    )
    local snap_enabled = reaper.GetToggleCommandState(1157) == 1
    if snap_enabled ~= args.snap_enabled then
      reaper.Main_OnCommand(1157, 0)
    end
    return {
      action = "set_grid",
      changes_applied = true,
      grid = project_grid_snapshot(project),
    }
  end,
}

COMMANDS.get_metronome = {
  mutates_project = false,
  handler = function()
    return {
      action = "get_metronome",
      changes_applied = false,
      metronome_enabled = reaper.GetToggleCommandState(40364) == 1,
    }
  end,
}

COMMANDS.set_metronome = {
  mutates_project = false,
  preflight_handler = function(envelope)
    if type(envelope.args.enabled) ~= "boolean" then
      error("invalid_navigation_request: enabled must be boolean")
    end
  end,
  handler = function(envelope)
    local enabled = reaper.GetToggleCommandState(40364) == 1
    if enabled ~= envelope.args.enabled then
      reaper.Main_OnCommand(40364, 0)
    end
    return {
      action = "set_metronome",
      changes_applied = true,
      metronome_enabled = reaper.GetToggleCommandState(40364) == 1,
    }
  end,
}

local function project_playback_rate(project, set_value, value)
  if set_value then
    reaper.CSurf_OnPlayRateChange(value)
  end
  return reaper.Master_GetPlayRate(project)
end

COMMANDS.get_playback_rate = {
  mutates_project = false,
  handler = function()
    local project = current_project()
    return {
      action = "get_playback_rate",
      changes_applied = false,
      playback_rate = project_playback_rate(project, false),
    }
  end,
}

COMMANDS.set_playback_rate = {
  mutates_project = false,
  preflight_handler = function(envelope)
    if type(envelope.args.rate) ~= "number" or envelope.args.rate <= 0 or envelope.args.rate > 4 then
      error("invalid_navigation_request: playback rate must be between 0 and 4")
    end
  end,
  handler = function(envelope)
    local project = current_project()
    project_playback_rate(project, true, envelope.args.rate)
    return {
      action = "set_playback_rate",
      changes_applied = true,
      playback_rate = project_playback_rate(project, false),
    }
  end,
}

end

register_project_control_commands()
