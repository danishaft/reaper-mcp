COMMANDS.list_available_fx = {
  mutates_project = false,
  handler = function()
    local fx = available_fx_list()
    return {
      fx = fx,
      fx_count = #fx,
    }
  end,
}

COMMANDS.list_track_fx = {
  mutates_project = false,
  handler = function(envelope)
    local project = current_project()
    local track = require_fx_track_by_guid(project, envelope.args.track_guid)
    local fx = track_fx_list(track, envelope.args.track_guid)
    return {
      track_guid = envelope.args.track_guid,
      fx = fx,
      fx_count = #fx,
    }
  end,
}

COMMANDS.list_take_fx = {
  mutates_project = false,
  handler = function(envelope)
    local project = current_project()
    local take = require_take_by_guid(project, envelope.args.take_guid)
    local fx = take_fx_list(take, envelope.args.take_guid)
    return {
      take_guid = envelope.args.take_guid,
      fx = fx,
      fx_count = #fx,
    }
  end,
}

COMMANDS.add_fx = {
  mutates_project = true,
  preflight_handler = function(envelope)
    local project = current_project()
    require_fx_track_by_guid(project, envelope.args.track_guid)
    if type(envelope.args.fx_identifier) ~= "string" or envelope.args.fx_identifier == "" then
      error("fx_not_found: fx_identifier must be a non-empty string")
    end
    if envelope.args.index ~= nil and (type(envelope.args.index) ~= "number" or envelope.args.index < 0) then
      error("invalid_fx_reference: FX insert index must be >= 0")
    end
    if not installed_fx_matches(envelope.args.fx_identifier) then
      error("fx_not_found: installed FX was not found")
    end
  end,
  handler = function(envelope)
    local args = envelope.args
    local project = current_project()
    local track = require_fx_track_by_guid(project, args.track_guid)
    if not installed_fx_matches(args.fx_identifier) then
      error("fx_not_found: installed FX was not found")
    end

    local insert_mode = -1
    if args.index ~= nil then
      insert_mode = -1000 - math.floor(args.index)
    end
    local fx_index = reaper.TrackFX_AddByName(track, args.fx_identifier, false, insert_mode)
    if fx_index == nil or fx_index < 0 then
      error("fx_insert_failed: REAPER rejected FX insertion")
    end

    if args.enabled == false then
      reaper.TrackFX_SetEnabled(track, fx_index, false)
    end

    local fx = track_fx_list(track, args.track_guid)
    return {
      track_guid = args.track_guid,
      added_fx = track_fx_snapshot(track, args.track_guid, fx_index),
      fx = fx,
      fx_count = #fx,
      changes_applied = true,
    }
  end,
}

COMMANDS.add_take_fx = {
  mutates_project = true,
  preflight_handler = function(envelope)
    local project = current_project()
    local take = require_take_by_guid(project, envelope.args.take_guid)
    if type(envelope.args.fx_identifier) ~= "string" or envelope.args.fx_identifier == "" then
      error("fx_not_found: fx_identifier must be a non-empty string")
    end
    local fx_count = safe_number_call(reaper.TakeFX_GetCount, 0, take)
    if envelope.args.index ~= nil
        and (type(envelope.args.index) ~= "number" or envelope.args.index < 0
          or envelope.args.index > fx_count) then
      error("invalid_fx_reference: take FX insert index was not found")
    end
  end,
  handler = function(envelope)
    local args = envelope.args
    local project = current_project()
    local take = require_take_by_guid(project, args.take_guid)
    local fx_index = reaper.TakeFX_AddByName(take, args.fx_identifier, 1)
    if fx_index == nil or fx_index < 0 then
      error("fx_insert_failed: REAPER rejected take FX insertion")
    end
    if args.index ~= nil and math.floor(args.index) ~= fx_index then
      reaper.TakeFX_CopyToTake(take, fx_index, take, math.floor(args.index), true)
      fx_index = math.floor(args.index)
    end
    if args.enabled == false then
      reaper.TakeFX_SetEnabled(take, fx_index, false)
    end
    local fx = take_fx_list(take, args.take_guid)
    return {
      take_guid = args.take_guid,
      added_fx = take_fx_snapshot(take, args.take_guid, fx_index),
      fx = fx,
      fx_count = #fx,
      changes_applied = true,
    }
  end,
}

COMMANDS.remove_fx = {
  mutates_project = true,
  preflight_handler = function(envelope)
    local project = current_project()
    require_fx_identity(project, envelope.args.fx_identity)
  end,
  handler = function(envelope)
    local project = current_project()
    local track, fx = require_fx_identity(project, envelope.args.fx_identity)
    local removed = reaper.TrackFX_Delete(track, fx.index)
    if not removed then
      error("fx_not_found: REAPER rejected FX removal")
    end
    local fx_list = track_fx_list(track, envelope.args.fx_identity.track_guid)
    return {
      track_guid = envelope.args.fx_identity.track_guid,
      removed_fx_identity = fx.identity,
      fx = fx_list,
      fx_count = #fx_list,
      changes_applied = true,
    }
  end,
}

COMMANDS.remove_take_fx = {
  mutates_project = true,
  preflight_handler = function(envelope)
    require_take_fx_identity(current_project(), envelope.args.fx_identity)
  end,
  handler = function(envelope)
    local project = current_project()
    local take, fx_identity = require_take_fx_identity(project, envelope.args.fx_identity)
    if not reaper.TakeFX_Delete(take, fx_identity.index) then
      error("fx_not_found: REAPER rejected take FX removal")
    end
    local fx = take_fx_list(take, envelope.args.fx_identity.take_guid)
    return {
      take_guid = envelope.args.fx_identity.take_guid,
      removed_fx_identity = fx_identity.identity,
      fx = fx,
      fx_count = #fx,
      changes_applied = true,
    }
  end,
}

COMMANDS.set_fx_enabled = {
  mutates_project = true,
  preflight_handler = function(envelope)
    local project = current_project()
    require_fx_identity(project, envelope.args.fx_identity)
    if type(envelope.args.enabled) ~= "boolean" then
      error("invalid_fx_reference: enabled must be a boolean")
    end
  end,
  handler = function(envelope)
    local project = current_project()
    local track, fx = require_fx_identity(project, envelope.args.fx_identity)
    reaper.TrackFX_SetEnabled(track, fx.index, envelope.args.enabled)
    local updated_fx = track_fx_snapshot(track, envelope.args.fx_identity.track_guid, fx.index)
    local fx_list = track_fx_list(track, envelope.args.fx_identity.track_guid)
    return {
      track_guid = envelope.args.fx_identity.track_guid,
      updated_fx = updated_fx,
      fx = fx_list,
      fx_count = #fx_list,
      changes_applied = true,
    }
  end,
}

COMMANDS.set_take_fx_enabled = {
  mutates_project = true,
  preflight_handler = function(envelope)
    require_take_fx_identity(current_project(), envelope.args.fx_identity)
    if type(envelope.args.enabled) ~= "boolean" then
      error("invalid_fx_reference: enabled must be a boolean")
    end
  end,
  handler = function(envelope)
    local project = current_project()
    local take, fx_identity = require_take_fx_identity(project, envelope.args.fx_identity)
    reaper.TakeFX_SetEnabled(take, fx_identity.index, envelope.args.enabled)
    local fx = take_fx_list(take, envelope.args.fx_identity.take_guid)
    return {
      take_guid = envelope.args.fx_identity.take_guid,
      updated_fx = take_fx_snapshot(
        take,
        envelope.args.fx_identity.take_guid,
        fx_identity.index
      ),
      fx = fx,
      fx_count = #fx,
      changes_applied = true,
    }
  end,
}

COMMANDS.get_fx_parameters = {
  mutates_project = false,
  handler = function(envelope)
    local project = current_project()
    local track, fx = require_fx_identity(project, envelope.args.fx_identity)
    local parameters = fx_parameter_list(track, fx.index)
    return {
      fx_identity = envelope.args.fx_identity,
      parameters = parameters,
      parameter_count = #parameters,
    }
  end,
}

COMMANDS.set_fx_parameter = {
  mutates_project = true,
  preflight_handler = function(envelope)
    local project = current_project()
    local track, fx = require_fx_identity(project, envelope.args.fx_identity)
    require_fx_parameter(track, fx.index, envelope.args.parameter_index)
    require_normalized_fx_parameter_value(envelope.args.normalized_value)
  end,
  handler = function(envelope)
    local project = current_project()
    local track, fx = require_fx_identity(project, envelope.args.fx_identity)
    require_fx_parameter(track, fx.index, envelope.args.parameter_index)
    require_normalized_fx_parameter_value(envelope.args.normalized_value)

    local set_ok = reaper.TrackFX_SetParamNormalized(
      track,
      fx.index,
      envelope.args.parameter_index,
      envelope.args.normalized_value
    )
    if set_ok == false then
      error("invalid_fx_parameter: REAPER rejected FX parameter value")
    end

    local updated_parameter = require_fx_parameter(track, fx.index, envelope.args.parameter_index)
    local parameters = fx_parameter_list(track, fx.index)
    return {
      fx_identity = envelope.args.fx_identity,
      updated_parameter = updated_parameter,
      parameters = parameters,
      parameter_count = #parameters,
      changes_applied = true,
    }
  end,
}

local function mastering_fx_plan_operations(envelope)
  local args = envelope.args
  if type(args.approval_hash) ~= "string" or args.approval_hash == "" then
    error("invalid_mastering_request: approval_hash must be a non-empty string")
  end
  if type(args.master_track_guid) ~= "string"
      or args.master_track_guid == "" then
    error(
      "invalid_mastering_request: master_track_guid must be a non-empty string"
    )
  end
  local master_track = reaper.GetMasterTrack(current_project())
  local master_guid = safe_string_call(reaper.GetTrackGUID, "", master_track)
  if master_guid ~= args.master_track_guid then
    error("mastering_plan_stale: master track GUID changed")
  end
  if type(args.operations) ~= "table" or #args.operations == 0 then
    error("invalid_mastering_request: operations must be a non-empty list")
  end

  for _, operation in ipairs(args.operations) do
    if type(operation) ~= "table" then
      error("invalid_mastering_request: each operation must be an object")
    end
    if type(operation.fx_identity) ~= "table"
        or operation.fx_identity.track_guid ~= master_guid then
      error("mastering_plan_stale: operation does not target the master track")
    end
    local track, fx = require_fx_identity(
      current_project(),
      operation.fx_identity
    )
    if operation.action == "set_parameter" then
      local parameter = require_fx_parameter(
        track,
        fx.index,
        operation.parameter_index
      )
      if parameter.name ~= operation.expected_parameter_name then
        error("mastering_plan_stale: FX parameter name changed")
      end
      require_normalized_fx_parameter_value(operation.normalized_value)
    elseif operation.action == "set_enabled" then
      if type(operation.enabled) ~= "boolean" then
        error("invalid_mastering_request: enabled must be boolean")
      end
    else
      error("invalid_mastering_request: unsupported mastering FX action")
    end
  end
  return master_track, args.operations
end

COMMANDS.apply_mastering_fx_plan = {
  mutates_project = true,
  preflight_handler = mastering_fx_plan_operations,
  handler = function(envelope)
    local master_track, operations = mastering_fx_plan_operations(envelope)
    local rollback = {}
    local ok, apply_error = pcall(function()
      for _, operation in ipairs(operations) do
        local track, fx = require_fx_identity(
          current_project(),
          operation.fx_identity
        )
        if operation.action == "set_parameter" then
          local before = reaper.TrackFX_GetParamNormalized(
            track,
            fx.index,
            operation.parameter_index
          )
          rollback[#rollback + 1] = {
            action = "set_parameter",
            track = track,
            fx_index = fx.index,
            parameter_index = operation.parameter_index,
            value = before,
          }
          local set_ok = reaper.TrackFX_SetParamNormalized(
            track,
            fx.index,
            operation.parameter_index,
            operation.normalized_value
          )
          if set_ok == false then
            error("postcondition_failed: REAPER rejected mastering parameter")
          end
          local actual = reaper.TrackFX_GetParamNormalized(
            track,
            fx.index,
            operation.parameter_index
          )
          if math.abs(actual - operation.normalized_value) > 0.000000001 then
            error("postcondition_failed: mastering parameter did not match")
          end
        else
          local before = reaper.TrackFX_GetEnabled(track, fx.index)
          rollback[#rollback + 1] = {
            action = "set_enabled",
            track = track,
            fx_index = fx.index,
            value = before,
          }
          reaper.TrackFX_SetEnabled(track, fx.index, operation.enabled)
          if reaper.TrackFX_GetEnabled(track, fx.index) ~= operation.enabled then
            error("postcondition_failed: mastering FX enabled state did not match")
          end
        end
      end
    end)
    if not ok then
      for index = #rollback, 1, -1 do
        local change = rollback[index]
        if change.action == "set_parameter" then
          reaper.TrackFX_SetParamNormalized(
            change.track,
            change.fx_index,
            change.parameter_index,
            change.value
          )
        else
          reaper.TrackFX_SetEnabled(
            change.track,
            change.fx_index,
            change.value
          )
        end
      end
      error(tostring(apply_error))
    end

    local fx = track_fx_list(master_track, envelope.args.master_track_guid)
    return {
      approval_hash = envelope.args.approval_hash,
      master_track_guid = envelope.args.master_track_guid,
      applied_operation_count = #operations,
      fx = fx,
      fx_count = #fx,
      changes_applied = true,
    }
  end,
}

local function register_fx_workflow_commands()
local function fx_preset_snapshot(track, identity)
  local _, preset_name = reaper.TrackFX_GetPreset(track, identity.index, "")
  return {
    fx_identity = identity,
    preset_name = preset_name or "",
    changes_applied = false,
  }
end

local function fx_preset_bank_snapshot(track, identity, changes_applied)
  local preset_index, preset_count = reaper.TrackFX_GetPresetIndex(
    track,
    identity.index
  )
  local _, preset_name = reaper.TrackFX_GetPreset(track, identity.index, "")
  return {
    fx_identity = identity,
    preset_index = math.floor(preset_index or -1),
    preset_count = math.floor(preset_count or 0),
    preset_name = preset_name or "",
    changes_applied = changes_applied == true,
  }
end

COMMANDS.get_fx_preset = {
  mutates_project = false,
  handler = function(envelope)
    local project = current_project()
    local track = require_fx_identity(project, envelope.args.fx_identity)
    return fx_preset_snapshot(track, envelope.args.fx_identity)
  end,
}

COMMANDS.set_fx_preset = {
  mutates_project = true,
  preflight_handler = function(envelope)
    local project = current_project()
    require_fx_identity(project, envelope.args.fx_identity)
    if type(envelope.args.preset_name) ~= "string" or envelope.args.preset_name == "" then
      error("invalid_fx_request: preset_name must be a non-empty string")
    end
  end,
  handler = function(envelope)
    local project = current_project()
    local track = require_fx_identity(project, envelope.args.fx_identity)
    local set_ok = reaper.TrackFX_SetPreset(
      track,
      envelope.args.fx_identity.index,
      envelope.args.preset_name
    )
    if not set_ok then
      error("invalid_fx_request: REAPER rejected FX preset")
    end
    local result = fx_preset_snapshot(track, envelope.args.fx_identity)
    result.changes_applied = true
    return result
  end,
}

COMMANDS.get_fx_preset_index = {
  mutates_project = false,
  handler = function(envelope)
    local project = current_project()
    local track = require_fx_identity(project, envelope.args.fx_identity)
    return fx_preset_bank_snapshot(track, envelope.args.fx_identity, false)
  end,
}

COMMANDS.set_fx_preset_index = {
  mutates_project = true,
  preflight_handler = function(envelope)
    local project = current_project()
    require_fx_identity(project, envelope.args.fx_identity)
    if type(envelope.args.preset_index) ~= "number"
        or envelope.args.preset_index < -2 then
      error("invalid_fx_request: preset_index must be >= -2")
    end
  end,
  handler = function(envelope)
    local project = current_project()
    local track = require_fx_identity(project, envelope.args.fx_identity)
    local set_ok = reaper.TrackFX_SetPresetByIndex(
      track,
      envelope.args.fx_identity.index,
      math.floor(envelope.args.preset_index)
    )
    if not set_ok then
      error("invalid_fx_request: REAPER rejected FX preset index")
    end
    return fx_preset_bank_snapshot(track, envelope.args.fx_identity, true)
  end,
}

COMMANDS.navigate_fx_presets = {
  mutates_project = true,
  preflight_handler = function(envelope)
    local project = current_project()
    require_fx_identity(project, envelope.args.fx_identity)
    if type(envelope.args.direction) ~= "number"
        or envelope.args.direction == 0 then
      error("invalid_fx_request: direction must not be zero")
    end
  end,
  handler = function(envelope)
    local project = current_project()
    local track = require_fx_identity(project, envelope.args.fx_identity)
    local moved = reaper.TrackFX_NavigatePresets(
      track,
      envelope.args.fx_identity.index,
      math.floor(envelope.args.direction)
    )
    if not moved then
      error("invalid_fx_request: FX preset navigation failed")
    end
    return fx_preset_bank_snapshot(track, envelope.args.fx_identity, true)
  end,
}

COMMANDS.move_fx = {
  mutates_project = true,
  preflight_handler = function(envelope)
    local project = current_project()
    local track, fx = require_fx_identity(project, envelope.args.fx_identity)
    local fx_count = safe_number_call(reaper.TrackFX_GetCount, 0, track)
    if type(envelope.args.destination_index) ~= "number"
        or envelope.args.destination_index < 0
        or envelope.args.destination_index >= fx_count then
      error("invalid_fx_reference: destination_index was not found")
    end
    if fx.index == envelope.args.destination_index then
      error("invalid_fx_reference: destination_index is unchanged")
    end
  end,
  handler = function(envelope)
    local project = current_project()
    local track, fx = require_fx_identity(project, envelope.args.fx_identity)
    local destination_index = math.floor(envelope.args.destination_index)
    reaper.TrackFX_CopyToTrack(track, fx.index, track, destination_index, true)
    local fx_list = track_fx_list(track, envelope.args.fx_identity.track_guid)
    local moved_fx = fx_list[math.min(destination_index + 1, #fx_list)]
    return {
      track_guid = envelope.args.fx_identity.track_guid,
      moved_fx = moved_fx,
      fx = fx_list,
      fx_count = #fx_list,
      changes_applied = true,
    }
  end,
}

COMMANDS.copy_fx_chain = {
  mutates_project = true,
  preflight_handler = function(envelope)
    local project = current_project()
    if envelope.args.source_track_guid == envelope.args.destination_track_guid then
      error("invalid_fx_request: source and destination tracks must differ")
    end
    local source = require_fx_track_by_guid(
      project,
      envelope.args.source_track_guid
    )
    require_fx_track_by_guid(project, envelope.args.destination_track_guid)
    if safe_number_call(reaper.TrackFX_GetCount, 0, source) == 0 then
      error("invalid_fx_request: source track has no FX")
    end
    if type(envelope.args.replace_destination) ~= "boolean" then
      error("invalid_fx_request: replace_destination must be boolean")
    end
  end,
  handler = function(envelope)
    local project = current_project()
    local source = require_fx_track_by_guid(
      project,
      envelope.args.source_track_guid
    )
    local destination = require_fx_track_by_guid(
      project,
      envelope.args.destination_track_guid
    )
    if envelope.args.replace_destination then
      for index = safe_number_call(reaper.TrackFX_GetCount, 0, destination) - 1, 0, -1 do
        reaper.TrackFX_Delete(destination, index)
      end
    end
    local source_count = safe_number_call(reaper.TrackFX_GetCount, 0, source)
    for index = 0, source_count - 1 do
      reaper.TrackFX_CopyToTrack(source, index, destination, -1, false)
    end
    local fx_list = track_fx_list(destination, envelope.args.destination_track_guid)
    return {
      source_track_guid = envelope.args.source_track_guid,
      track_guid = envelope.args.destination_track_guid,
      fx = fx_list,
      fx_count = #fx_list,
      changes_applied = true,
    }
  end,
}

COMMANDS.list_markers = {
  mutates_project = false,
  handler = function()
    local project = current_project()
    local markers = project_markers_and_regions(project)
    return {
      markers = markers,
      marker_count = #markers,
    }
  end,
}

COMMANDS.create_marker = {
  mutates_project = true,
  preflight_handler = function(envelope)
    require_non_negative_seconds(envelope.args.start_seconds, "start_seconds", "invalid_marker_reference")
    if envelope.args.color ~= nil and (type(envelope.args.color) ~= "number" or envelope.args.color < 0) then
      error("invalid_marker_reference: color must be >= 0")
    end
  end,
  handler = function(envelope)
    local project = current_project()
    local name = envelope.args.name or ""
    local color = envelope.args.color or 0
    local marker_id = reaper.AddProjectMarker2(
      project,
      false,
      envelope.args.start_seconds,
      0,
      name,
      -1,
      color
    )
    if marker_id == nil or marker_id < 0 then
      error("marker_not_found: REAPER rejected marker creation")
    end
    local marker = require_marker_identity(project, {
      id = marker_id,
      expected_name = name,
      expected_start_seconds = envelope.args.start_seconds,
    })
    local markers = project_markers_and_regions(project)
    reaper.UpdateTimeline()
    return {
      marker = marker_payload(marker),
      markers = markers,
      marker_count = #markers,
      changes_applied = true,
    }
  end,
}

COMMANDS.delete_marker = {
  mutates_project = true,
  preflight_handler = function(envelope)
    local project = current_project()
    require_marker_identity(project, envelope.args.marker_identity)
  end,
  handler = function(envelope)
    local project = current_project()
    local marker = require_marker_identity(project, envelope.args.marker_identity)
    local deleted = reaper.DeleteProjectMarker(project, marker.id, false)
    if not deleted then
      error("marker_not_found: REAPER rejected marker deletion")
    end
    local markers = project_markers_and_regions(project)
    reaper.UpdateTimeline()
    return {
      deleted_marker_id = marker.id,
      markers = markers,
      marker_count = #markers,
      changes_applied = true,
    }
  end,
}

COMMANDS.list_regions = {
  mutates_project = false,
  handler = function()
    local project = current_project()
    local _, regions = project_markers_and_regions(project)
    return {
      regions = regions,
      region_count = #regions,
    }
  end,
}

COMMANDS.create_region = {
  mutates_project = true,
  preflight_handler = function(envelope)
    require_non_negative_seconds(envelope.args.start_seconds, "start_seconds", "invalid_region_reference")
    require_non_negative_seconds(envelope.args.end_seconds, "end_seconds", "invalid_region_reference")
    if envelope.args.end_seconds <= envelope.args.start_seconds then
      error("invalid_region_reference: end_seconds must be greater than start_seconds")
    end
    if envelope.args.color ~= nil and (type(envelope.args.color) ~= "number" or envelope.args.color < 0) then
      error("invalid_region_reference: color must be >= 0")
    end
  end,
  handler = function(envelope)
    local project = current_project()
    local name = envelope.args.name or ""
    local color = envelope.args.color or 0
    local region_id = reaper.AddProjectMarker2(
      project,
      true,
      envelope.args.start_seconds,
      envelope.args.end_seconds,
      name,
      -1,
      color
    )
    if region_id == nil or region_id < 0 then
      error("region_not_found: REAPER rejected region creation")
    end
    local region = require_region_identity(project, {
      id = region_id,
      expected_name = name,
      expected_start_seconds = envelope.args.start_seconds,
      expected_end_seconds = envelope.args.end_seconds,
    })
    local _, regions = project_markers_and_regions(project)
    reaper.UpdateTimeline()
    return {
      region = region_payload(region),
      regions = regions,
      region_count = #regions,
      changes_applied = true,
    }
  end,
}

COMMANDS.delete_region = {
  mutates_project = true,
  preflight_handler = function(envelope)
    local project = current_project()
    require_region_identity(project, envelope.args.region_identity)
  end,
  handler = function(envelope)
    local project = current_project()
    local region = require_region_identity(project, envelope.args.region_identity)
    local deleted = reaper.DeleteProjectMarker(project, region.id, true)
    if not deleted then
      error("region_not_found: REAPER rejected region deletion")
    end
    local _, regions = project_markers_and_regions(project)
    reaper.UpdateTimeline()
    return {
      deleted_region_id = region.id,
      regions = regions,
      region_count = #regions,
      changes_applied = true,
    }
  end,
}

COMMANDS.get_tempo = {
  mutates_project = false,
  handler = function()
    local project = current_project()
    return {
      tempo = tempo_state(project).tempo,
    }
  end,
}

COMMANDS.set_tempo = {
  mutates_project = true,
  preflight_handler = function(envelope)
    if type(envelope.args.bpm) ~= "number" or envelope.args.bpm < 20 or envelope.args.bpm > 400 then
      error("invalid_tempo_request: bpm must be between 20 and 400")
    end
  end,
  handler = function(envelope)
    local project = current_project()
    reaper.SetCurrentBPM(project, envelope.args.bpm, false)
    reaper.UpdateTimeline()
    return {
      tempo = tempo_state(project).tempo,
      changes_applied = true,
    }
  end,
}

COMMANDS.get_time_signature = {
  mutates_project = false,
  handler = function()
    local project = current_project()
    return tempo_state(project)
  end,
}

COMMANDS.set_time_signature = {
  mutates_project = true,
  preflight_handler = function(envelope)
    if type(envelope.args.numerator) ~= "number" or envelope.args.numerator < 1 or envelope.args.numerator > 32 then
      error("invalid_tempo_request: numerator must be between 1 and 32")
    end
    if type(envelope.args.denominator) ~= "number" or not is_supported_time_signature_denominator(envelope.args.denominator) then
      error("invalid_tempo_request: denominator must be one of 1, 2, 4, 8, 16, 32, or 64")
    end
  end,
  handler = function(envelope)
    local project = current_project()
    local state = tempo_state(project)
    local ok = reaper.SetTempoTimeSigMarker(
      project,
      tempo_marker_index_at_project_start(project),
      0,
      -1,
      -1,
      state.tempo.bpm,
      envelope.args.numerator,
      envelope.args.denominator,
      false
    )
    if not ok then
      error("invalid_tempo_request: REAPER rejected time signature update")
    end
    reaper.UpdateTimeline()
    local updated_state = tempo_state(project)
    return {
      time_signature = updated_state.time_signature,
      tempo = updated_state.tempo,
      changes_applied = true,
    }
  end,
}

end

register_fx_workflow_commands()

local function register_tempo_map_commands()
local function tempo_marker_fingerprint(
  position_seconds,
  bpm,
  numerator,
  denominator,
  linear
)
  return table.concat({
    tostring(math.floor(position_seconds * 1000000 + 0.5)),
    tostring(math.floor(bpm * 1000 + 0.5)),
    tostring(numerator),
    tostring(denominator),
    tostring(linear and 1 or 0),
  }, ":")
end

local function tempo_marker_snapshot(project, index)
  local ok, position_seconds, _, _, bpm, numerator, denominator, linear =
    reaper.GetTempoTimeSigMarker(project, index)
  if not ok then
    return nil
  end
  numerator = numerator > 0 and numerator or 4
  denominator = denominator > 0 and denominator or 4
  return {
    index = index,
    fingerprint = tempo_marker_fingerprint(
      position_seconds,
      bpm,
      numerator,
      denominator,
      linear
    ),
    position_seconds = position_seconds,
    position_qn = reaper.TimeMap2_timeToQN(project, position_seconds),
    bpm = bpm,
    numerator = numerator,
    denominator = denominator,
    linear = linear,
  }
end

local function tempo_markers(project)
  local markers = {}
  local count = safe_number_call(reaper.CountTempoTimeSigMarkers, 0, project)
  for index = 0, count - 1 do
    local marker = tempo_marker_snapshot(project, index)
    if marker then
      markers[#markers + 1] = marker
    end
  end
  return markers
end

local function require_tempo_marker_identity(project, identity)
  if type(identity) ~= "table" or type(identity.index) ~= "number"
      or type(identity.expected_fingerprint) ~= "string" then
    error("invalid_tempo_request: invalid tempo-marker identity")
  end
  local marker = tempo_marker_snapshot(project, identity.index)
  if not marker then
    error("tempo_marker_conflict: tempo marker was not found")
  end
  if marker.fingerprint ~= identity.expected_fingerprint then
    error("tempo_marker_conflict: tempo marker fingerprint changed")
  end
  return marker
end

local function validate_tempo_marker_request(marker)
  if type(marker) ~= "table" then
    error("invalid_tempo_request: marker must be an object")
  end
  if type(marker.position_seconds) ~= "number" or marker.position_seconds < 0 then
    error("invalid_tempo_request: position_seconds must be >= 0")
  end
  if type(marker.bpm) ~= "number" or marker.bpm < 20 or marker.bpm > 400 then
    error("invalid_tempo_request: bpm must be between 20 and 400")
  end
  if type(marker.numerator) ~= "number" or marker.numerator < 1 or marker.numerator > 32 then
    error("invalid_tempo_request: numerator must be between 1 and 32")
  end
  if type(marker.denominator) ~= "number" or not is_supported_time_signature_denominator(marker.denominator) then
    error("invalid_tempo_request: denominator is not supported")
  end
end

local function tempo_marker_result(project, marker)
  local markers = tempo_markers(project)
  return {
    markers = markers,
    marker_count = #markers,
    marker = marker,
    changes_applied = true,
  }
end

COMMANDS.list_tempo_markers = {
  mutates_project = false,
  handler = function()
    local project = current_project()
    local markers = tempo_markers(project)
    return { markers = markers, marker_count = #markers }
  end,
}

COMMANDS.create_tempo_marker = {
  mutates_project = true,
  preflight_handler = function(envelope)
    validate_tempo_marker_request(envelope.args)
  end,
  handler = function(envelope)
    local project = current_project()
    validate_tempo_marker_request(envelope.args)
    local args = envelope.args
    local before_markers = tempo_markers(project)
    local before_fingerprints = {}
    for _, current_marker in ipairs(before_markers) do
      before_fingerprints[current_marker.fingerprint] = true
    end
    local inserted = reaper.SetTempoTimeSigMarker(
      project,
      -1,
      args.position_seconds,
      -1,
      -1,
      args.bpm,
      args.numerator,
      args.denominator,
      args.linear or false
    )
    if not inserted then
      error("invalid_tempo_request: REAPER rejected tempo-marker creation")
    end
    reaper.UpdateTimeline()
    local marker = nil
    for _, current_marker in ipairs(tempo_markers(project)) do
      if not before_fingerprints[current_marker.fingerprint]
          and math.abs(current_marker.bpm - args.bpm) < 0.001
          and current_marker.numerator == args.numerator
          and current_marker.denominator == args.denominator then
        marker = current_marker
        break
      end
    end
    if not marker then
      error("invalid_tempo_request: created tempo marker was not returned")
    end
    return tempo_marker_result(project, marker)
  end,
}

COMMANDS.update_tempo_marker = {
  mutates_project = true,
  preflight_handler = function(envelope)
    local project = current_project()
    require_tempo_marker_identity(project, envelope.args.identity)
    validate_tempo_marker_request(envelope.args.marker)
  end,
  handler = function(envelope)
    local project = current_project()
    require_tempo_marker_identity(project, envelope.args.identity)
    validate_tempo_marker_request(envelope.args.marker)
    local args = envelope.args.marker
    local updated = reaper.SetTempoTimeSigMarker(
      project,
      envelope.args.identity.index,
      args.position_seconds,
      -1,
      -1,
      args.bpm,
      args.numerator,
      args.denominator,
      args.linear or false
    )
    if not updated then
      error("tempo_marker_conflict: REAPER rejected tempo-marker update")
    end
    reaper.UpdateTimeline()
    local marker = tempo_marker_snapshot(project, envelope.args.identity.index)
    if not marker then
      error("tempo_marker_conflict: updated tempo marker was not returned")
    end
    return tempo_marker_result(project, marker)
  end,
}

COMMANDS.delete_tempo_marker = {
  mutates_project = true,
  preflight_handler = function(envelope)
    require_tempo_marker_identity(current_project(), envelope.args.identity)
  end,
  handler = function(envelope)
    local project = current_project()
    require_tempo_marker_identity(project, envelope.args.identity)
    if not reaper.DeleteTempoTimeSigMarker(project, envelope.args.identity.index) then
      error("tempo_marker_conflict: REAPER rejected tempo-marker deletion")
    end
    reaper.UpdateTimeline()
    local markers = tempo_markers(project)
    return {
      markers = markers,
      marker_count = #markers,
      deleted_marker_index = envelope.args.identity.index,
      changes_applied = true,
    }
  end,
}

end

register_tempo_map_commands()
