-- Keep expansion helpers in one closure to stay below Lua's chunk-local limit.
local function register_expansion_commands()
local AUTOMATION_MODES = {
  [0] = "trim_read",
  [1] = "read",
  [2] = "touch",
  [3] = "write",
  [4] = "latch",
  [5] = "latch_preview",
}

local AUTOMATION_MODE_VALUES = {
  trim_read = 0,
  read = 1,
  touch = 2,
  write = 3,
  latch = 4,
  latch_preview = 5,
}

local ENVELOPE_TYPES = {
  volume = { chunk = "<VOLENV2", action = 40406 },
  pan = { chunk = "<PANENV2", action = 40407 },
  mute = { chunk = "<MUTEENV", action = 40867 },
  pre_fx_volume = { chunk = "<VOLENV", action = 40408 },
  pre_fx_pan = { chunk = "<PANENV", action = 40409 },
  trim_volume = { chunk = "<VOLENV3", action = 42020 },
}

local function envelope_guid(envelope)
  local ok, guid = reaper.GetSetEnvelopeInfo_String(envelope, "GUID", "", false)
  return ok and guid or ""
end

local function envelope_snapshot(track, envelope, index)
  local _, name = reaper.GetEnvelopeName(envelope, "")
  return {
    guid = envelope_guid(envelope),
    track_guid = safe_string_call(reaper.GetTrackGUID, "", track),
    index = index,
    name = name or "",
    point_count = safe_number_call(reaper.CountEnvelopePointsEx, 0, envelope, -1),
  }
end

local function require_envelope(project, identity)
  if type(identity) ~= "table" then
    error("invalid_envelope_reference: envelope_identity must be an object")
  end
  local track = require_track_by_guid(project, identity.track_guid)
  if type(identity.envelope_guid) ~= "string" or identity.envelope_guid == "" then
    error("invalid_envelope_reference: envelope_guid must be a non-empty string")
  end
  local count = safe_number_call(reaper.CountTrackEnvelopes, 0, track)
  for index = 0, count - 1 do
    local envelope = reaper.GetTrackEnvelope(track, index)
    if envelope and envelope_guid(envelope) == identity.envelope_guid then
      return track, envelope, index
    end
  end
  error("invalid_envelope_reference: envelope_guid was not found on the track")
end

local function point_fingerprint(time, value, shape, tension, selected)
  return string.format(
    "%.12g:%.12g:%d:%.12g:%d",
    time,
    value,
    shape,
    tension,
    selected and 1 or 0
  )
end

local function envelope_point_snapshot(envelope, index)
  local ok, time, value, shape, tension, selected = reaper.GetEnvelopePointEx(
    envelope,
    -1,
    index
  )
  if not ok then
    return nil
  end
  local scaling_mode = safe_number_call(reaper.GetEnvelopeScalingMode, 0, envelope)
  local scaled_value = safe_number_call(
    reaper.ScaleFromEnvelopeMode,
    value,
    scaling_mode,
    value
  )
  return {
    index = index,
    fingerprint = point_fingerprint(time, value, shape, tension, selected),
    time_seconds = time,
    value = scaled_value,
    shape = shape,
    tension = tension,
    selected = selected,
    formatted_value = safe_string_call(reaper.Envelope_FormatValue, "", envelope, value),
  }
end

local function envelope_raw_value(envelope, scaled_value)
  local scaling_mode = safe_number_call(reaper.GetEnvelopeScalingMode, 0, envelope)
  return safe_number_call(
    reaper.ScaleToEnvelopeMode,
    scaled_value,
    scaling_mode,
    scaled_value
  )
end

local function envelope_points_result(track, envelope, envelope_index, changed)
  local points = {}
  local point_count = safe_number_call(reaper.CountEnvelopePointsEx, 0, envelope, -1)
  for point_index = 0, point_count - 1 do
    local point = envelope_point_snapshot(envelope, point_index)
    if point then
      points[#points + 1] = point
    end
  end
  return {
    envelope = envelope_snapshot(track, envelope, envelope_index),
    points = points,
    point_count = #points,
    changes_applied = changed or false,
  }
end

local function require_finite_number(value, field)
  if type(value) ~= "number" or value ~= value or math.abs(value) == math.huge then
    error("invalid_automation_request: " .. field .. " must be a finite number")
  end
end

local function validate_envelope_point_input(point)
  if type(point) ~= "table" then
    error("invalid_automation_request: every point must be an object")
  end
  require_finite_number(point.time_seconds, "time_seconds")
  require_finite_number(point.value, "value")
  require_finite_number(point.tension, "tension")
  if point.time_seconds < 0 then
    error("invalid_automation_request: time_seconds must be >= 0")
  end
  if type(point.shape) ~= "number" or point.shape < 0 or point.shape > 5
    or point.shape % 1 ~= 0 then
    error("invalid_automation_request: shape must be an integer from 0 to 5")
  end
  if point.tension < -1 or point.tension > 1 then
    error("invalid_automation_request: tension must be between -1 and 1")
  end
  if type(point.selected) ~= "boolean" then
    error("invalid_automation_request: selected must be a boolean")
  end
end

local function require_point_identity(envelope, identity)
  if type(identity) ~= "table" or type(identity.index) ~= "number"
    or identity.index < 0 or identity.index % 1 ~= 0 then
    error("invalid_automation_request: point index must be a non-negative integer")
  end
  if type(identity.expected_fingerprint) ~= "string"
    or identity.expected_fingerprint == "" then
    error("invalid_automation_request: expected_fingerprint must be non-empty")
  end
  local point = envelope_point_snapshot(envelope, identity.index)
  if not point or point.fingerprint ~= identity.expected_fingerprint then
    error("invalid_envelope_reference: envelope point identity no longer matches")
  end
  return point
end

local function ensure_point_time_available(envelope, time_seconds, excluded_index)
  local point_count = safe_number_call(reaper.CountEnvelopePointsEx, 0, envelope, -1)
  for index = 0, point_count - 1 do
    if index ~= excluded_index then
      local point = envelope_point_snapshot(envelope, index)
      if point and math.abs(point.time_seconds - time_seconds) < 1e-9 then
        error("invalid_automation_request: envelope already has a point at this time")
      end
    end
  end
end

COMMANDS.list_track_envelopes = {
  mutates_project = false,
  handler = function(envelope)
    local project = current_project()
    local track = require_track_by_guid(project, envelope.args.track_guid)
    local envelopes = {}
    local count = safe_number_call(reaper.CountTrackEnvelopes, 0, track)
    for index = 0, count - 1 do
      local track_envelope = reaper.GetTrackEnvelope(track, index)
      if track_envelope then
        envelopes[#envelopes + 1] = envelope_snapshot(track, track_envelope, index)
      end
    end
    return {
      track_guid = envelope.args.track_guid,
      envelopes = envelopes,
      envelope_count = #envelopes,
    }
  end,
}

local function ensure_track_envelope_plan(envelope)
  local project = current_project()
  local track = require_track_by_guid(project, envelope.args.track_guid)
  local definition = ENVELOPE_TYPES[envelope.args.envelope_type]
  if not definition then
    error("invalid_automation_request: unsupported built-in envelope type")
  end
  return project, track, definition
end

COMMANDS.ensure_track_envelope = {
  mutates_project = true,
  preflight_handler = ensure_track_envelope_plan,
  handler = function(envelope)
    local project, track, definition = ensure_track_envelope_plan(envelope)
    local track_envelope = reaper.GetTrackEnvelopeByChunkName(track, definition.chunk)
    local function find_envelope_index(target)
      local envelope_count = safe_number_call(reaper.CountTrackEnvelopes, 0, track)
      for index = 0, envelope_count - 1 do
        if reaper.GetTrackEnvelope(track, index) == target then
          return index
        end
      end
      return -1
    end
    local envelope_index = track_envelope and find_envelope_index(track_envelope) or -1
    local created = false
    if envelope_index < 0 then
      local selection = {}
      local track_count = safe_number_call(reaper.CountTracks, 0, project)
      for index = 0, track_count - 1 do
        local project_track = reaper.GetTrack(project, index)
        selection[#selection + 1] = {
          track = project_track,
          selected = reaper.IsTrackSelected(project_track),
        }
        reaper.SetTrackSelected(project_track, project_track == track)
      end
      local ok, action_error = pcall(
        reaper.Main_OnCommandEx,
        definition.action,
        0,
        project
      )
      for _, state in ipairs(selection) do
        if reaper.ValidatePtr2(project, state.track, "MediaTrack*") then
          reaper.SetTrackSelected(state.track, state.selected)
        end
      end
      if not ok then
        error(
          "invalid_automation_request: envelope action failed: "
            .. tostring(action_error)
        )
      end
      track_envelope = reaper.GetTrackEnvelopeByChunkName(track, definition.chunk)
      if not track_envelope then
        error("invalid_automation_request: REAPER did not create the envelope")
      end
      envelope_index = find_envelope_index(track_envelope)
      created = true
    end
    if envelope_index < 0 then
      error("invalid_automation_request: created envelope is not enumerable")
    end
    reaper.TrackList_AdjustWindows(false)
    reaper.UpdateArrange()
    return {
      envelope = envelope_snapshot(track, track_envelope, envelope_index),
      created = created,
      changes_applied = created,
    }
  end,
}

COMMANDS.get_envelope_points = {
  mutates_project = false,
  handler = function(envelope)
    local project = current_project()
    local track, track_envelope, index = require_envelope(
      project,
      envelope.args.envelope_identity
    )
    return envelope_points_result(track, track_envelope, index, false)
  end,
}

local function validate_add_envelope_points(envelope)
  local project = current_project()
  local _, track_envelope = require_envelope(project, envelope.args.envelope_identity)
  if type(envelope.args.points) ~= "table" or #envelope.args.points == 0 then
    error("invalid_automation_request: points must be a non-empty array")
  end
  local times = {}
  for _, point in ipairs(envelope.args.points) do
    validate_envelope_point_input(point)
    local key = string.format("%.12g", point.time_seconds)
    if times[key] then
      error("invalid_automation_request: point times must be unique")
    end
    times[key] = true
    ensure_point_time_available(track_envelope, point.time_seconds, nil)
  end
end

COMMANDS.add_envelope_points = {
  mutates_project = true,
  preflight_handler = validate_add_envelope_points,
  handler = function(envelope)
    local project = current_project()
    local track, track_envelope, index = require_envelope(
      project,
      envelope.args.envelope_identity
    )
    validate_add_envelope_points(envelope)
    for _, point in ipairs(envelope.args.points) do
      local inserted = reaper.InsertEnvelopePointEx(
        track_envelope,
        -1,
        point.time_seconds,
        envelope_raw_value(track_envelope, point.value),
        point.shape,
        point.tension,
        point.selected,
        true
      )
      if not inserted then
        error("invalid_automation_request: REAPER rejected an envelope point")
      end
    end
    reaper.Envelope_SortPointsEx(track_envelope, -1)
    reaper.UpdateArrange()
    return envelope_points_result(track, track_envelope, index, true)
  end,
}

local function update_envelope_point_plan(envelope)
  local project = current_project()
  local track, track_envelope, index = require_envelope(
    project,
    envelope.args.envelope_identity
  )
  local current = require_point_identity(track_envelope, envelope.args.point_identity)
  local updated = {
    time_seconds = envelope.args.time_seconds or current.time_seconds,
    value = envelope.args.value or current.value,
    shape = envelope.args.shape or current.shape,
    tension = envelope.args.tension or current.tension,
    selected = envelope.args.selected,
  }
  if updated.selected == nil then
    updated.selected = current.selected
  end
  validate_envelope_point_input(updated)
  ensure_point_time_available(track_envelope, updated.time_seconds, current.index)
  return track, track_envelope, index, current, updated
end

COMMANDS.update_envelope_point = {
  mutates_project = true,
  preflight_handler = update_envelope_point_plan,
  handler = function(envelope)
    local track, track_envelope, index, current, updated = update_envelope_point_plan(envelope)
    local changed = reaper.SetEnvelopePointEx(
      track_envelope,
      -1,
      current.index,
      updated.time_seconds,
      envelope_raw_value(track_envelope, updated.value),
      updated.shape,
      updated.tension,
      updated.selected,
      true
    )
    if not changed then
      error("invalid_automation_request: REAPER rejected the envelope point update")
    end
    reaper.Envelope_SortPointsEx(track_envelope, -1)
    reaper.UpdateArrange()
    return envelope_points_result(track, track_envelope, index, true)
  end,
}

local function guarded_delete_points(envelope)
  local project = current_project()
  local track, track_envelope, index = require_envelope(
    project,
    envelope.args.envelope_identity
  )
  if type(envelope.args.points) ~= "table" or #envelope.args.points == 0 then
    error("invalid_automation_request: points must be a non-empty array")
  end
  local indexes = {}
  for _, identity in ipairs(envelope.args.points) do
    require_point_identity(track_envelope, identity)
    if indexes[identity.index] then
      error("invalid_automation_request: point indexes must be unique")
    end
    indexes[identity.index] = true
  end
  return track, track_envelope, index, indexes
end

COMMANDS.delete_envelope_points = {
  mutates_project = true,
  preflight_handler = guarded_delete_points,
  handler = function(envelope)
    local track, track_envelope, index, indexes = guarded_delete_points(envelope)
    local descending = {}
    for point_index in pairs(indexes) do
      descending[#descending + 1] = point_index
    end
    table.sort(descending, function(left, right) return left > right end)
    for _, point_index in ipairs(descending) do
      if not reaper.DeleteEnvelopePointEx(track_envelope, -1, point_index) then
        error("invalid_automation_request: REAPER rejected an envelope point deletion")
      end
    end
    reaper.Envelope_SortPointsEx(track_envelope, -1)
    reaper.UpdateArrange()
    return envelope_points_result(track, track_envelope, index, true)
  end,
}

local function envelope_range_plan(envelope)
  local project = current_project()
  local track, track_envelope, index = require_envelope(
    project,
    envelope.args.envelope_identity
  )
  require_finite_number(envelope.args.start_seconds, "start_seconds")
  require_finite_number(envelope.args.end_seconds, "end_seconds")
  if envelope.args.start_seconds < 0
    or envelope.args.end_seconds <= envelope.args.start_seconds then
    error("invalid_automation_request: envelope range must be non-empty")
  end
  local matching = 0
  local point_count = safe_number_call(reaper.CountEnvelopePointsEx, 0, track_envelope, -1)
  for point_index = 0, point_count - 1 do
    local point = envelope_point_snapshot(track_envelope, point_index)
    if point and point.time_seconds >= envelope.args.start_seconds
      and point.time_seconds < envelope.args.end_seconds then
      matching = matching + 1
    end
  end
  if matching == 0 then
    error("invalid_automation_request: envelope range contains no points")
  end
  return track, track_envelope, index
end

COMMANDS.delete_envelope_points_in_range = {
  mutates_project = true,
  preflight_handler = envelope_range_plan,
  handler = function(envelope)
    local track, track_envelope, index = envelope_range_plan(envelope)
    reaper.DeleteEnvelopePointRangeEx(
      track_envelope,
      -1,
      envelope.args.start_seconds,
      envelope.args.end_seconds
    )
    reaper.Envelope_SortPointsEx(track_envelope, -1)
    reaper.UpdateArrange()
    return envelope_points_result(track, track_envelope, index, true)
  end,
}

local function track_automation_mode_result(track, changed)
  local value = safe_number_call(reaper.GetTrackAutomationMode, -1, track)
  local mode = AUTOMATION_MODES[value]
  if not mode then
    error("invalid_automation_request: REAPER returned an unsupported automation mode")
  end
  return {
    track_guid = safe_string_call(reaper.GetTrackGUID, "", track),
    mode = mode,
    changes_applied = changed or false,
  }
end

COMMANDS.get_track_automation_mode = {
  mutates_project = false,
  handler = function(envelope)
    local project = current_project()
    local track = require_track_by_guid(project, envelope.args.track_guid)
    return track_automation_mode_result(track, false)
  end,
}

local function validate_automation_mode(envelope)
  local project = current_project()
  local track = require_track_by_guid(project, envelope.args.track_guid)
  local mode_value = AUTOMATION_MODE_VALUES[envelope.args.mode]
  if mode_value == nil then
    error("invalid_automation_request: unsupported track automation mode")
  end
  return track, mode_value
end

COMMANDS.set_track_automation_mode = {
  mutates_project = true,
  preflight_handler = validate_automation_mode,
  handler = function(envelope)
    local track, mode_value = validate_automation_mode(envelope)
    reaper.SetTrackAutomationMode(track, mode_value)
    reaper.TrackList_AdjustWindows(false)
    return track_automation_mode_result(track, true)
  end,
}

local function managed_take_snapshot(item, take, index)
  local _, name = reaper.GetSetMediaItemTakeInfo_String(take, "P_NAME", "", false)
  return {
    guid = take_guid(take),
    item_guid = item_guid(item),
    index = index,
    name = name or "",
    is_active = reaper.GetActiveTake(item) == take,
    is_midi = reaper.TakeIsMIDI(take),
    volume = safe_number_call(reaper.GetMediaItemTakeInfo_Value, 1, take, "D_VOL"),
    pan = safe_number_call(reaper.GetMediaItemTakeInfo_Value, 0, take, "D_PAN"),
    pitch_semitones = safe_number_call(
      reaper.GetMediaItemTakeInfo_Value,
      0,
      take,
      "D_PITCH"
    ),
    playback_rate = safe_number_call(
      reaper.GetMediaItemTakeInfo_Value,
      1,
      take,
      "D_PLAYRATE"
    ),
    start_offset_seconds = safe_number_call(
      reaper.GetMediaItemTakeInfo_Value,
      0,
      take,
      "D_STARTOFFS"
    ),
    preserve_pitch = safe_number_call(
      reaper.GetMediaItemTakeInfo_Value,
      0,
      take,
      "B_PPITCH"
    ) ~= 0,
  }
end

local function take_list_result(item, changed_take, changed)
  local takes = {}
  local active_take = reaper.GetActiveTake(item)
  local take_count = safe_number_call(reaper.CountTakes, 0, item)
  for index = 0, take_count - 1 do
    local take = reaper.GetTake(item, index)
    if take then
      takes[#takes + 1] = managed_take_snapshot(item, take, index)
    end
  end
  return {
    item_guid = item_guid(item),
    takes = takes,
    take_count = #takes,
    active_take_guid = active_take and take_guid(active_take) or nil,
    changed_take = changed_take,
    changes_applied = changed or false,
  }
end

COMMANDS.list_item_takes = {
  mutates_project = false,
  handler = function(envelope)
    local project = current_project()
    local item = require_media_item_by_guid(project, envelope.args.item_guid)
    local result = take_list_result(item, nil, false)
    result.changed_take = nil
    result.changes_applied = nil
    return result
  end,
}

local function validate_add_empty_take(envelope)
  local project = current_project()
  local item = require_media_item_by_guid(project, envelope.args.item_guid)
  if type(envelope.args.name) ~= "string" or envelope.args.name == ""
    or #envelope.args.name > 200 then
    error("invalid_take_request: take name must contain 1 to 200 characters")
  end
  return project, item
end

COMMANDS.add_empty_take = {
  mutates_project = true,
  preflight_handler = validate_add_empty_take,
  handler = function(envelope)
    local project, item = validate_add_empty_take(envelope)
    local take = reaper.AddTakeToMediaItem(item)
    if not take then
      error("invalid_take_request: REAPER did not create an empty take")
    end
    reaper.GetSetMediaItemTakeInfo_String(take, "P_NAME", envelope.args.name, true)
    reaper.SetActiveTake(take)
    reaper.UpdateItemInProject(item)
    reaper.UpdateArrange()
    local _, _, take_index = find_take_by_guid(project, take_guid(take))
    return take_list_result(item, managed_take_snapshot(item, take, take_index), true)
  end,
}

COMMANDS.set_active_take = {
  mutates_project = true,
  preflight_handler = function(envelope)
    local project = current_project()
    require_take_by_guid(project, envelope.args.take_guid)
  end,
  handler = function(envelope)
    local project = current_project()
    local take, item, take_index = require_take_by_guid(project, envelope.args.take_guid)
    reaper.SetActiveTake(take)
    reaper.UpdateItemInProject(item)
    reaper.UpdateArrange()
    return take_list_result(item, managed_take_snapshot(item, take, take_index), true)
  end,
}

local function validate_rename_take(envelope)
  local project = current_project()
  local take, item, take_index = require_take_by_guid(project, envelope.args.take_guid)
  if type(envelope.args.name) ~= "string" or envelope.args.name == ""
    or #envelope.args.name > 200 then
    error("invalid_take_request: take name must contain 1 to 200 characters")
  end
  return take, item, take_index
end

COMMANDS.rename_take = {
  mutates_project = true,
  preflight_handler = validate_rename_take,
  handler = function(envelope)
    local take, item, take_index = validate_rename_take(envelope)
    local renamed = reaper.GetSetMediaItemTakeInfo_String(
      take,
      "P_NAME",
      envelope.args.name,
      true
    )
    if not renamed then
      error("invalid_take_request: REAPER rejected the take name")
    end
    reaper.UpdateItemInProject(item)
    return take_list_result(item, managed_take_snapshot(item, take, take_index), true)
  end,
}

local TAKE_PROPERTIES = {
  volume = { key = "D_VOL", minimum = 0.0, maximum = 4.0 },
  pan = { key = "D_PAN", minimum = -1.0, maximum = 1.0 },
  pitch_semitones = { key = "D_PITCH", minimum = -80.0, maximum = 80.0 },
  playback_rate = { key = "D_PLAYRATE", minimum = 0.05, maximum = 8.0 },
}

local function validate_take_property(envelope)
  local project = current_project()
  local take, item, take_index = require_take_by_guid(project, envelope.args.take_guid)
  local property = TAKE_PROPERTIES[envelope.args.property]
  if not property then
    error("invalid_take_request: unsupported take property")
  end
  local value = envelope.args.value
  if type(value) ~= "number" or value ~= value or value < property.minimum
    or value > property.maximum then
    error("invalid_take_request: take property value is outside the supported range")
  end
  if envelope.args.preserve_pitch ~= nil
    and type(envelope.args.preserve_pitch) ~= "boolean" then
    error("invalid_take_request: preserve_pitch must be a boolean")
  end
  return take, item, take_index, property
end

COMMANDS.set_take_property = {
  mutates_project = true,
  preflight_handler = validate_take_property,
  handler = function(envelope)
    local take, item, take_index, property = validate_take_property(envelope)
    if not reaper.SetMediaItemTakeInfo_Value(take, property.key, envelope.args.value) then
      error("invalid_take_request: REAPER rejected the take property")
    end
    if envelope.args.property == "playback_rate"
      and envelope.args.preserve_pitch ~= nil then
      local preserve_pitch = envelope.args.preserve_pitch and 1 or 0
      if not reaper.SetMediaItemTakeInfo_Value(take, "B_PPITCH", preserve_pitch) then
        error("invalid_take_request: REAPER rejected the preserve-pitch setting")
      end
    end
    reaper.UpdateItemInProject(item)
    reaper.UpdateArrange()
    return take_list_result(item, managed_take_snapshot(item, take, take_index), true)
  end,
}

local function crop_to_active_take_plan(envelope)
  local project = current_project()
  local item = require_media_item_by_guid(project, envelope.args.item_guid)
  local active_take = reaper.GetActiveTake(item)
  local take_count = safe_number_call(reaper.CountTakes, 0, item)
  if not active_take or take_guid(active_take) ~= envelope.args.expected_active_take_guid then
    error("invalid_take_reference: active take identity no longer matches")
  end
  if type(envelope.args.expected_take_count) ~= "number"
    or envelope.args.expected_take_count ~= take_count or take_count < 2 then
    error("invalid_take_reference: take count no longer matches")
  end
  return project, item, active_take
end

COMMANDS.crop_to_active_take = {
  mutates_project = true,
  preflight_handler = crop_to_active_take_plan,
  handler = function(envelope)
    local project, item, active_take = crop_to_active_take_plan(envelope)
    local selection = {}
    local item_count = safe_number_call(reaper.CountMediaItems, 0, project)
    for index = 0, item_count - 1 do
      local project_item = reaper.GetMediaItem(project, index)
      selection[#selection + 1] = {
        item = project_item,
        selected = reaper.IsMediaItemSelected(project_item),
      }
      reaper.SetMediaItemSelected(project_item, project_item == item)
    end
    local ok, action_error = pcall(reaper.Main_OnCommandEx, 40131, 0, project)
    for _, state in ipairs(selection) do
      if reaper.ValidatePtr2(project, state.item, "MediaItem*") then
        reaper.SetMediaItemSelected(state.item, state.selected)
      end
    end
    if not ok then
      error("invalid_take_request: crop action failed: " .. tostring(action_error))
    end
    local remaining_take = reaper.GetActiveTake(item)
    if safe_number_call(reaper.CountTakes, 0, item) ~= 1
      or not remaining_take or take_guid(remaining_take) ~= take_guid(active_take) then
      error("invalid_take_request: crop action did not preserve exactly the active take")
    end
    reaper.UpdateItemInProject(item)
    reaper.UpdateArrange()
    return take_list_result(item, managed_take_snapshot(item, remaining_take, 0), true)
  end,
}

local function fixed_lane_name(track, lane_index)
  local _, name = reaper.GetSetMediaTrackInfo_String(
    track,
    "P_LANENAME:" .. lane_index,
    "",
    false
  )
  return name or ""
end

local function fixed_lane_play_state(track, lane_index)
  return math.floor(safe_number_call(
    reaper.GetMediaTrackInfo_Value,
    0,
    track,
    "C_LANEPLAYS:" .. lane_index
  ))
end

local function fixed_lane_items(track, lane_index)
  local items = {}
  local item_count = safe_number_call(reaper.CountTrackMediaItems, 0, track)
  for item_index = 0, item_count - 1 do
    local item = reaper.GetTrackMediaItem(track, item_index)
    local item_lane = item and math.floor(safe_number_call(
      reaper.GetMediaItemInfo_Value,
      -1,
      item,
      "I_FIXEDLANE"
    )) or -1
    if item and item_lane == lane_index then
      items[#items + 1] = {
        guid = item_guid(item),
        position_seconds = safe_number_call(
          reaper.GetMediaItemInfo_Value,
          0,
          item,
          "D_POSITION"
        ),
        length_seconds = safe_number_call(
          reaper.GetMediaItemInfo_Value,
          0,
          item,
          "D_LENGTH"
        ),
        muted = safe_number_call(
          reaper.GetMediaItemInfo_Value,
          0,
          item,
          "B_MUTE"
        ) ~= 0,
      }
    end
  end
  return items
end

local function fingerprint_field(value)
  local text = tostring(value or "")
  return tostring(#text) .. ":" .. text
end

local function fixed_lane_layout(track, track_guid_value, changed)
  local mode = math.floor(safe_number_call(
    reaper.GetMediaTrackInfo_Value,
    0,
    track,
    "I_FREEMODE"
  ))
  if mode ~= 2 then
    error("invalid_fixed_lane_request: track is not in REAPER fixed-lane mode")
  end
  local lane_count = math.floor(safe_number_call(
    reaper.GetMediaTrackInfo_Value,
    0,
    track,
    "I_NUMFIXEDLANES"
  ))
  if lane_count < 1 then
    error("invalid_fixed_lane_request: fixed-lane track has no lanes")
  end

  local lanes = {}
  local fingerprint = {
    fingerprint_field(track_guid_value),
    tostring(mode),
    tostring(lane_count),
  }
  for lane_index = 0, lane_count - 1 do
    local name = fixed_lane_name(track, lane_index)
    local play_state = fixed_lane_play_state(track, lane_index)
    if play_state < 0 or play_state > 2 then
      error("invalid_fixed_lane_request: REAPER returned an invalid lane play state")
    end
    local items = fixed_lane_items(track, lane_index)
    lanes[#lanes + 1] = {
      index = lane_index,
      name = name,
      play_state = play_state,
      items = items,
    }
    fingerprint[#fingerprint + 1] = tostring(lane_index)
    fingerprint[#fingerprint + 1] = fingerprint_field(name)
    fingerprint[#fingerprint + 1] = tostring(play_state)
    fingerprint[#fingerprint + 1] = tostring(#items)
    for _, item in ipairs(items) do
      fingerprint[#fingerprint + 1] = fingerprint_field(item.guid)
      fingerprint[#fingerprint + 1] = string.format("%.17g", item.position_seconds)
      fingerprint[#fingerprint + 1] = string.format("%.17g", item.length_seconds)
      fingerprint[#fingerprint + 1] = item.muted and "1" or "0"
    end
  end
  return {
    track_guid = track_guid_value,
    lane_count = lane_count,
    layout_fingerprint = table.concat(fingerprint, "|"),
    lanes = lanes,
    changes_applied = changed or false,
  }
end

COMMANDS.list_fixed_lanes = {
  mutates_project = false,
  handler = function(envelope)
    local project = current_project()
    local track = require_track_by_guid(project, envelope.args.track_guid)
    return fixed_lane_layout(track, envelope.args.track_guid, false)
  end,
}

local function select_fixed_lane_plan(envelope)
  local project = current_project()
  local track = require_track_by_guid(project, envelope.args.track_guid)
  local layout = fixed_lane_layout(track, envelope.args.track_guid, false)
  local lane_index = envelope.args.lane_index
  if type(lane_index) ~= "number" or lane_index < 0
    or lane_index % 1 ~= 0 or lane_index >= layout.lane_count then
    error("invalid_fixed_lane_request: lane_index is outside the current layout")
  end
  if type(envelope.args.expected_layout_fingerprint) ~= "string"
    or envelope.args.expected_layout_fingerprint ~= layout.layout_fingerprint then
    error("invalid_fixed_lane_request: fixed-lane layout no longer matches")
  end
  return track, layout, lane_index
end

COMMANDS.select_fixed_lane = {
  mutates_project = true,
  preflight_handler = select_fixed_lane_plan,
  handler = function(envelope)
    local track, previous, lane_index = select_fixed_lane_plan(envelope)
    local changed = reaper.SetMediaTrackInfo_Value(
      track,
      "C_LANEPLAYS:" .. lane_index,
      1
    )
    if not changed then
      error("invalid_fixed_lane_request: REAPER rejected fixed-lane selection")
    end
    reaper.TrackList_AdjustWindows(false)
    reaper.UpdateArrange()

    local updated = fixed_lane_layout(track, envelope.args.track_guid, true)
    local valid = true
    for _, lane in ipairs(updated.lanes) do
      local expected = lane.index == lane_index and 1 or 0
      if lane.play_state ~= expected then
        valid = false
        break
      end
    end
    if not valid then
      for _, lane in ipairs(previous.lanes) do
        reaper.SetMediaTrackInfo_Value(
          track,
          "C_LANEPLAYS:" .. lane.index,
          lane.play_state
        )
      end
      reaper.TrackList_AdjustWindows(false)
      reaper.UpdateArrange()
      error("postcondition_failed: fixed-lane playback state did not match")
    end
    return updated
  end,
}

local function timeline_range(start_seconds, end_seconds)
  return {
    start_seconds = start_seconds,
    end_seconds = end_seconds,
    length_seconds = end_seconds - start_seconds,
    is_set = end_seconds > start_seconds,
  }
end

local function project_navigation_snapshot(project, changed, saved)
  local _, path = reaper.EnumProjects(-1, "")
  local selection_start, selection_end = reaper.GetSet_LoopTimeRange2(
    project,
    false,
    false,
    0,
    0,
    false
  )
  local loop_start, loop_end = reaper.GetSet_LoopTimeRange2(
    project,
    false,
    true,
    0,
    0,
    false
  )
  return {
    project_path = path ~= "" and path or nil,
    dirty = safe_number_call(reaper.IsProjectDirty, 0, project) ~= 0,
    edit_cursor_seconds = safe_number_call(reaper.GetCursorPositionEx, 0, project),
    time_selection = timeline_range(selection_start, selection_end),
    loop_points = timeline_range(loop_start, loop_end),
    loop_enabled = safe_number_call(reaper.GetSetRepeat, 0, -1) == 1,
    changes_applied = changed or false,
    saved = saved or false,
  }
end

local function require_timeline_range(args)
  if type(args.start_seconds) ~= "number" or type(args.end_seconds) ~= "number"
    or args.start_seconds < 0 or args.end_seconds <= args.start_seconds then
    error("invalid_navigation_request: timeline range must be non-empty and non-negative")
  end
end

COMMANDS.get_project_navigation = {
  mutates_project = false,
  handler = function()
    local project = current_project()
    local result = project_navigation_snapshot(project, false, false)
    result.changes_applied = nil
    result.saved = nil
    return result
  end,
}

COMMANDS.set_edit_cursor = {
  mutates_project = false,
  handler = function(envelope)
    local project = current_project()
    if type(envelope.args.position_seconds) ~= "number"
      or envelope.args.position_seconds < 0
      or type(envelope.args.move_view) ~= "boolean"
      or type(envelope.args.seek_playback) ~= "boolean" then
      error("invalid_navigation_request: invalid edit cursor request")
    end
    reaper.SetEditCurPos2(
      project,
      envelope.args.position_seconds,
      envelope.args.move_view,
      envelope.args.seek_playback
    )
    return project_navigation_snapshot(project, true, false)
  end,
}

COMMANDS.set_time_selection = {
  mutates_project = false,
  handler = function(envelope)
    local project = current_project()
    require_timeline_range(envelope.args)
    reaper.GetSet_LoopTimeRange2(
      project,
      true,
      false,
      envelope.args.start_seconds,
      envelope.args.end_seconds,
      false
    )
    return project_navigation_snapshot(project, true, false)
  end,
}

COMMANDS.clear_time_selection = {
  mutates_project = false,
  handler = function()
    local project = current_project()
    reaper.GetSet_LoopTimeRange2(project, true, false, 0, 0, false)
    return project_navigation_snapshot(project, true, false)
  end,
}

COMMANDS.set_loop_points = {
  mutates_project = false,
  handler = function(envelope)
    local project = current_project()
    require_timeline_range(envelope.args)
    reaper.GetSet_LoopTimeRange2(
      project,
      true,
      true,
      envelope.args.start_seconds,
      envelope.args.end_seconds,
      false
    )
    return project_navigation_snapshot(project, true, false)
  end,
}

COMMANDS.set_loop_enabled = {
  mutates_project = false,
  handler = function(envelope)
    local project = current_project()
    if type(envelope.args.enabled) ~= "boolean" then
      error("invalid_navigation_request: enabled must be a boolean")
    end
    reaper.GetSetRepeat(envelope.args.enabled and 1 or 0)
    return project_navigation_snapshot(project, true, false)
  end,
}

COMMANDS.save_project = {
  mutates_project = false,
  handler = function()
    local project, path = current_project()
    if path == "" then
      error("project_save_failed: active project does not have a project path")
    end
    reaper.Main_SaveProject(project, false)
    if safe_number_call(reaper.IsProjectDirty, 0, project) ~= 0 then
      error("project_save_failed: REAPER did not clear the project dirty state")
    end
    return project_navigation_snapshot(project, true, true)
  end,
}

COMMANDS.save_project_as = {
  mutates_project = false,
  handler = function(envelope)
    local project = current_project()
    local path = envelope.args.project_path
    if type(path) ~= "string" or path == "" or path:lower():sub(-4) ~= ".rpp" then
      error("invalid_navigation_request: project_path must be a non-empty .rpp path")
    end
    if reaper.file_exists(path) and not envelope.args.overwrite then
      error("project_save_failed: project path already exists")
    end
    reaper.Main_SaveProjectEx(project, path, 8)
    local _, active_path = reaper.EnumProjects(-1, "")
    if active_path ~= path or not reaper.file_exists(path)
      or safe_number_call(reaper.IsProjectDirty, 0, project) ~= 0 then
      error("project_save_failed: REAPER did not confirm the new project path")
    end
    return project_navigation_snapshot(project, true, true)
  end,
}
end

register_expansion_commands();
