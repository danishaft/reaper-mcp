assert((function()
local TUNING_EPSILON = 0.000001

local function require_vocal_tuning_plan(envelope)
  local args = envelope.args
  if type(args.approval_hash) ~= "string" or args.approval_hash == "" then
    error("invalid_vocal_tuning_request: approval_hash must be a non-empty string")
  end
  if args.provider_id ~= "reaper_take_pitch" then
    error("vocal_tuning_provider_unavailable: provider is not bridge-controlled")
  end
  if type(args.context) ~= "table" then
    error("invalid_vocal_tuning_request: context must be an object")
  end
  local context = args.context
  local project = current_project()
  local state_change_count = safe_number_call(
    reaper.GetProjectStateChangeCount,
    -1,
    project
  )
  if state_change_count ~= context.state_change_count then
    error("vocal_tuning_plan_stale: project state change count changed")
  end

  local item = require_media_item_by_guid(project, context.item_guid)
  local track = reaper.GetMediaItemTrack(item)
  local track_guid = track and safe_string_call(reaper.GetTrackGUID, "", track) or ""
  if track_guid ~= context.track_guid then
    error("vocal_tuning_plan_stale: media item track changed")
  end
  local position = safe_number_call(
    reaper.GetMediaItemInfo_Value,
    0,
    item,
    "D_POSITION"
  )
  local length = safe_number_call(
    reaper.GetMediaItemInfo_Value,
    0,
    item,
    "D_LENGTH"
  )
  if math.abs(position - context.item_position_seconds) > TUNING_EPSILON
    or math.abs(length - context.item_length_seconds) > TUNING_EPSILON then
    error("vocal_tuning_plan_stale: media item boundaries changed")
  end
  if safe_number_call(reaper.CountTakes, 0, item) ~= 1 then
    error("vocal_tuning_plan_stale: media item no longer has one take")
  end

  local take = reaper.GetActiveTake(item)
  if not take or take_guid(take) ~= context.take_guid then
    error("vocal_tuning_plan_stale: active take changed")
  end
  if reaper.TakeIsMIDI(take) then
    error("invalid_vocal_tuning_request: target take must contain audio")
  end
  local base_pitch = safe_number_call(
    reaper.GetMediaItemTakeInfo_Value,
    0,
    take,
    "D_PITCH"
  )
  if math.abs(base_pitch - context.take_pitch_semitones) > TUNING_EPSILON then
    error("vocal_tuning_plan_stale: take pitch changed")
  end

  if type(args.corrections) ~= "table" or #args.corrections == 0 then
    error("invalid_vocal_tuning_request: corrections must be a non-empty list")
  end
  local item_end = position + length
  local previous_end = nil
  local segment_ids = {}
  for _, correction in ipairs(args.corrections) do
    if type(correction) ~= "table"
      or type(correction.segment_id) ~= "string"
      or correction.segment_id == "" then
      error("invalid_vocal_tuning_request: every correction needs a segment_id")
    end
    if segment_ids[correction.segment_id] then
      error("invalid_vocal_tuning_request: segment_id values must be unique")
    end
    segment_ids[correction.segment_id] = true
    if type(correction.start_seconds) ~= "number"
      or type(correction.end_seconds) ~= "number"
      or correction.start_seconds < position
      or correction.end_seconds > item_end
      or correction.end_seconds <= correction.start_seconds then
      error("invalid_vocal_tuning_request: correction range is outside the item")
    end
    if previous_end and correction.start_seconds < previous_end then
      error("invalid_vocal_tuning_request: corrections must not overlap")
    end
    previous_end = correction.end_seconds
    if type(correction.correction_cents) ~= "number"
      or correction.correction_cents ~= correction.correction_cents
      or math.abs(correction.correction_cents) > 200
      or math.abs(correction.correction_cents) < 0.000001 then
      error("invalid_vocal_tuning_request: correction_cents is invalid")
    end
    if correction.preserve_vibrato ~= true then
      error("invalid_vocal_tuning_request: provider preserves vibrato")
    end
    local result_pitch = base_pitch + correction.correction_cents / 100
    if result_pitch < -80 or result_pitch > 80 then
      error("invalid_vocal_tuning_request: result pitch is outside REAPER range")
    end
  end
  return project, track, item, take, base_pitch, args.corrections
end

COMMANDS.apply_vocal_tuning_plan = {
  mutates_project = true,
  preflight_handler = require_vocal_tuning_plan,
  handler = function(envelope)
    local project, track, item, take, base_pitch, corrections =
      require_vocal_tuning_plan(envelope)
    local original_length = safe_number_call(
      reaper.GetMediaItemInfo_Value,
      0,
      item,
      "D_LENGTH"
    )
    local created_items = {}
    local applied = {}
    local working_item = item
    local mutation_ok, mutation_error = pcall(function()
      for correction_index = #corrections, 1, -1 do
        local correction = corrections[correction_index]
        local working_position = safe_number_call(
          reaper.GetMediaItemInfo_Value,
          0,
          working_item,
          "D_POSITION"
        )
        local working_length = safe_number_call(
          reaper.GetMediaItemInfo_Value,
          0,
          working_item,
          "D_LENGTH"
        )
        local working_end = working_position + working_length
        if correction.end_seconds < working_end - TUNING_EPSILON then
          local right_item = reaper.SplitMediaItem(
            working_item,
            correction.end_seconds
          )
          if not right_item then
            error("postcondition_failed: REAPER rejected tuning segment end split")
          end
          created_items[#created_items + 1] = right_item
        end

        local segment_item = working_item
        if correction.start_seconds > working_position + TUNING_EPSILON then
          segment_item = reaper.SplitMediaItem(
            working_item,
            correction.start_seconds
          )
          if not segment_item then
            error("postcondition_failed: REAPER rejected tuning segment start split")
          end
          created_items[#created_items + 1] = segment_item
        end
        local segment_take = reaper.GetActiveTake(segment_item)
        if not segment_take or reaper.TakeIsMIDI(segment_take) then
          error("postcondition_failed: tuning split did not preserve the audio take")
        end
        local result_pitch = base_pitch + correction.correction_cents / 100
        local set_ok = reaper.SetMediaItemTakeInfo_Value(
          segment_take,
          "D_PITCH",
          result_pitch
        )
        if set_ok == false then
          error("postcondition_failed: REAPER rejected tuning segment pitch")
        end
        local actual_pitch = safe_number_call(
          reaper.GetMediaItemTakeInfo_Value,
          0,
          segment_take,
          "D_PITCH"
        )
        if math.abs(actual_pitch - result_pitch) > TUNING_EPSILON then
          error("postcondition_failed: tuning segment pitch did not match")
        end
        local segment_position = safe_number_call(
          reaper.GetMediaItemInfo_Value,
          correction.start_seconds,
          segment_item,
          "D_POSITION"
        )
        local segment_length = safe_number_call(
          reaper.GetMediaItemInfo_Value,
          correction.end_seconds - correction.start_seconds,
          segment_item,
          "D_LENGTH"
        )
        reaper.UpdateItemInProject(segment_item)
        applied[#applied + 1] = {
          segment_id = correction.segment_id,
          item_guid = item_guid(segment_item),
          take_guid = take_guid(segment_take),
          start_seconds = segment_position,
          end_seconds = segment_position + segment_length,
          correction_cents = correction.correction_cents,
          result_pitch_semitones = actual_pitch,
        }
      end
    end)
    if not mutation_ok then
      for created_index = #created_items, 1, -1 do
        local created_item = created_items[created_index]
        if created_item then
          reaper.DeleteTrackMediaItem(track, created_item)
        end
      end
      reaper.SetMediaItemInfo_Value(item, "D_LENGTH", original_length)
      reaper.SetMediaItemTakeInfo_Value(take, "D_PITCH", base_pitch)
      reaper.UpdateItemInProject(item)
      reaper.UpdateArrange()
      error(tostring(mutation_error))
    end

    table.sort(applied, function(left, right)
      return left.start_seconds < right.start_seconds
    end)
    reaper.UpdateArrange()
    return {
      approval_hash = envelope.args.approval_hash,
      provider_id = envelope.args.provider_id,
      applied_correction_count = #applied,
      segments = applied,
      changes_applied = true,
    }
  end,
}

local function reatune_fx_snapshots(track, track_guid_value)
  local matches = {}
  local fx_count = safe_number_call(reaper.TrackFX_GetCount, 0, track)
  for fx_index = 0, fx_count - 1 do
    local fx = track_fx_snapshot(track, track_guid_value, fx_index)
    local searchable = string.lower((fx.name or "") .. " " .. (fx.identifier or ""))
    if string.find(searchable, "reatune", 1, true) then
      matches[#matches + 1] = fx
    end
  end
  return matches
end

local function current_fx_preset_name(track, fx_index)
  local _, preset_name = reaper.TrackFX_GetPreset(track, fx_index, "")
  return preset_name or ""
end

local function require_vocal_tuning_preset_plan(envelope)
  local args = envelope.args
  if type(args.approval_hash) ~= "string" or args.approval_hash == "" then
    error("invalid_vocal_tuning_request: approval_hash must be a non-empty string")
  end
  if args.provider_id ~= "reatune" then
    error("vocal_tuning_provider_unavailable: preset provider is not bridge-controlled")
  end
  if type(args.preset_name) ~= "string" or args.preset_name == "" then
    error("invalid_vocal_tuning_request: preset_name must be a non-empty string")
  end
  if type(args.context) ~= "table" then
    error("invalid_vocal_tuning_request: context must be an object")
  end

  local context = args.context
  if context.insert_index ~= 0 then
    error("invalid_vocal_tuning_request: ReaTune must be inserted at FX index 0")
  end
  if type(context.installed_fx_identifier) ~= "string"
    or context.installed_fx_identifier == "" then
    error("invalid_vocal_tuning_request: installed_fx_identifier is required")
  end

  local project = current_project()
  local state_change_count = safe_number_call(
    reaper.GetProjectStateChangeCount,
    -1,
    project
  )
  if state_change_count ~= context.state_change_count then
    error("vocal_tuning_plan_stale: project state change count changed")
  end
  if not installed_fx_matches(context.installed_fx_identifier) then
    error("vocal_tuning_provider_unavailable: ReaTune is no longer installed")
  end

  local track = require_fx_track_by_guid(project, context.track_guid)
  local _, track_name = reaper.GetTrackName(track, "")
  track_name = track_name or ""
  if track_name ~= context.track_name then
    error("vocal_tuning_plan_stale: target track name changed")
  end

  local matches = reatune_fx_snapshots(track, context.track_guid)
  if #matches > 1 then
    error("invalid_vocal_tuning_request: target track has multiple ReaTune instances")
  end

  local existing_fx = nil
  if context.existing_fx_identity ~= nil then
    local _, guarded_fx = require_fx_identity(project, context.existing_fx_identity)
    local searchable = string.lower(
      (guarded_fx.name or "") .. " " .. (guarded_fx.identifier or "")
    )
    if not string.find(searchable, "reatune", 1, true) then
      error("vocal_tuning_plan_stale: guarded FX is no longer ReaTune")
    end
    if guarded_fx.index ~= 0 then
      error("vocal_tuning_plan_stale: ReaTune is no longer first in the FX chain")
    end
    if #matches ~= 1 or matches[1].guid ~= guarded_fx.guid then
      error("vocal_tuning_plan_stale: ReaTune instance changed")
    end
    local preset_name = current_fx_preset_name(track, guarded_fx.index)
    if preset_name ~= context.existing_preset_name then
      error("vocal_tuning_plan_stale: current ReaTune preset changed")
    end
    if preset_name == "" then
      error("invalid_vocal_tuning_request: existing ReaTune needs a named rollback preset")
    end
    existing_fx = guarded_fx
  elseif #matches ~= 0 then
    error("vocal_tuning_plan_stale: a ReaTune instance was added after preview")
  end

  return project, track, track_name, existing_fx
end

COMMANDS.apply_vocal_tuning_preset_plan = {
  mutates_project = true,
  preflight_handler = require_vocal_tuning_preset_plan,
  handler = function(envelope)
    local project, track, track_name, existing_fx =
      require_vocal_tuning_preset_plan(envelope)
    local args = envelope.args
    local inserted = false
    local fx_index = existing_fx and existing_fx.index or nil
    local previous_preset = existing_fx
      and current_fx_preset_name(track, existing_fx.index)
      or nil
    local previous_enabled = existing_fx
      and reaper.TrackFX_GetEnabled(track, existing_fx.index)
      or nil

    local mutation_ok, mutation_error = pcall(function()
      if fx_index == nil then
        fx_index = reaper.TrackFX_AddByName(
          track,
          args.context.installed_fx_identifier,
          false,
          -1000
        )
        if fx_index == nil or fx_index ~= 0 then
          error("postcondition_failed: ReaTune was not inserted first in the FX chain")
        end
        inserted = true
      end

      local before_preset = current_fx_preset_name(track, fx_index)
      if before_preset ~= args.preset_name then
        local set_ok = reaper.TrackFX_SetPreset(track, fx_index, args.preset_name)
        if not set_ok then
          error("invalid_vocal_tuning_request: REAPER rejected the ReaTune preset")
        end
      end
      local actual_preset = current_fx_preset_name(track, fx_index)
      if actual_preset ~= args.preset_name then
        error("postcondition_failed: recalled ReaTune preset name did not match")
      end

      reaper.TrackFX_SetEnabled(track, fx_index, true)
      if not reaper.TrackFX_GetEnabled(track, fx_index) then
        error("postcondition_failed: ReaTune was not enabled")
      end
    end)

    if not mutation_ok then
      if inserted and fx_index ~= nil then
        reaper.TrackFX_Delete(track, fx_index)
      elseif existing_fx then
        if previous_preset and previous_preset ~= "" then
          reaper.TrackFX_SetPreset(track, existing_fx.index, previous_preset)
        end
        reaper.TrackFX_SetEnabled(
          track,
          existing_fx.index,
          previous_enabled == true
        )
      end
      reaper.TrackList_AdjustWindows(false)
      reaper.UpdateArrange()
      error(tostring(mutation_error))
    end

    local preset_index, preset_count = reaper.TrackFX_GetPresetIndex(track, fx_index)
    local result_fx = track_fx_snapshot(track, args.context.track_guid, fx_index)
    local changed = inserted
      or previous_preset ~= args.preset_name
      or previous_enabled ~= true
    reaper.TrackList_AdjustWindows(false)
    reaper.UpdateArrange()
    return {
      approval_hash = args.approval_hash,
      provider_id = args.provider_id,
      track_guid = args.context.track_guid,
      track_name = track_name,
      fx = result_fx,
      preset_name = current_fx_preset_name(track, fx_index),
      preset_index = math.floor(preset_index or -1),
      preset_count = math.floor(preset_count or 0),
      inserted = inserted,
      changes_applied = changed,
    }
  end,
}
return true
end)())

assert((function()
local X42_AUTOTUNE_URI = "http://gareus.org/oss/lv2/fat1"
local X42_PARAMETER_EPSILON = 0.000001
local X42_PARAMETER_NAMES = {
  [0] = "Mode",
  [1] = "Filter Channel",
  [2] = "Tuning",
  [3] = "Bias",
  [4] = "Filter",
  [5] = "Correction",
  [6] = "Offset",
  [7] = "Pitch Bend Range",
  [8] = "Fast Correction",
  [9] = "C",
  [10] = "C#",
  [11] = "D",
  [12] = "D#",
  [13] = "E",
  [14] = "F",
  [15] = "F#",
  [16] = "G",
  [17] = "G#",
  [18] = "A",
  [19] = "A#",
  [20] = "B",
  [25] = "Bypass",
  [26] = "Wet",
  [27] = "Delta",
}

local function x42_fx_snapshots(track, track_guid_value)
  local matches = {}
  local fx_count = safe_number_call(reaper.TrackFX_GetCount, 0, track)
  for fx_index = 0, fx_count - 1 do
    local fx = track_fx_snapshot(track, track_guid_value, fx_index)
    if fx.identifier == X42_AUTOTUNE_URI then
      matches[#matches + 1] = fx
    end
  end
  return matches
end

local function require_x42_parameter_targets(track, fx_index, targets)
  if type(targets) ~= "table" then
    error("invalid_vocal_tuning_request: target_parameters must be a list")
  end
  local validated = {}
  local seen = {}
  local count = 0
  for _, target in ipairs(targets) do
    if type(target) ~= "table"
      or type(target.index) ~= "number"
      or math.floor(target.index) ~= target.index
      or type(target.name) ~= "string"
      or type(target.normalized_value) ~= "number"
      or target.normalized_value < 0
      or target.normalized_value > 1 then
      error("invalid_vocal_tuning_request: target parameter is invalid")
    end
    local expected_name = X42_PARAMETER_NAMES[target.index]
    if expected_name == nil or target.name ~= expected_name or seen[target.index] then
      error("invalid_vocal_tuning_request: x42 parameter contract did not match")
    end
    local actual = fx_parameter_snapshot(track, fx_index, target.index)
    if not actual or actual.name ~= expected_name then
      error("vocal_tuning_provider_unavailable: x42 parameter contract changed")
    end
    seen[target.index] = true
    count = count + 1
    validated[#validated + 1] = target
  end
  local expected_count = 0
  for parameter_index, _ in pairs(X42_PARAMETER_NAMES) do
    expected_count = expected_count + 1
    if not seen[parameter_index] then
      error("invalid_vocal_tuning_request: x42 parameter target is missing")
    end
  end
  if count ~= expected_count then
    error("invalid_vocal_tuning_request: x42 parameter target count did not match")
  end
  table.sort(validated, function(left, right)
    return left.index < right.index
  end)
  return validated
end

local function require_vocal_tuning_plugin_plan(envelope)
  local args = envelope.args
  if type(args.approval_hash) ~= "string" or args.approval_hash == "" then
    error("invalid_vocal_tuning_request: approval_hash must be a non-empty string")
  end
  if args.provider_id ~= "x42_autotune" then
    error("vocal_tuning_provider_unavailable: plugin provider is not bridge-controlled")
  end
  if type(args.context) ~= "table" then
    error("invalid_vocal_tuning_request: context must be an object")
  end

  local context = args.context
  if context.installed_fx_identifier ~= X42_AUTOTUNE_URI then
    error("invalid_vocal_tuning_request: x42 plugin URI did not match")
  end
  if context.insert_index ~= 0 then
    error("invalid_vocal_tuning_request: x42 Auto Tune must be FX index 0")
  end

  local project = current_project()
  local state_change_count = safe_number_call(
    reaper.GetProjectStateChangeCount,
    -1,
    project
  )
  if state_change_count ~= context.state_change_count then
    error("vocal_tuning_plan_stale: project state change count changed")
  end
  if not installed_fx_matches(X42_AUTOTUNE_URI) then
    error("vocal_tuning_provider_unavailable: x42 Auto Tune is no longer installed")
  end

  local track = require_fx_track_by_guid(project, context.track_guid)
  local _, track_name = reaper.GetTrackName(track, "")
  track_name = track_name or ""
  if track_name ~= context.track_name then
    error("vocal_tuning_plan_stale: target track name changed")
  end

  local matches = x42_fx_snapshots(track, context.track_guid)
  if #matches > 1 then
    error("invalid_vocal_tuning_request: track has multiple x42 Auto Tune instances")
  end

  local existing_fx = nil
  if context.existing_fx_identity ~= nil then
    local _, guarded_fx = require_fx_identity(project, context.existing_fx_identity)
    if guarded_fx.identifier ~= X42_AUTOTUNE_URI then
      error("vocal_tuning_plan_stale: guarded FX is no longer x42 Auto Tune")
    end
    if guarded_fx.index ~= 0 then
      error("vocal_tuning_plan_stale: x42 Auto Tune is no longer first")
    end
    if #matches ~= 1 or matches[1].guid ~= guarded_fx.guid then
      error("vocal_tuning_plan_stale: x42 Auto Tune instance changed")
    end
    if reaper.TrackFX_GetEnabled(track, guarded_fx.index)
      ~= (context.existing_fx_enabled == true) then
      error("vocal_tuning_plan_stale: x42 Auto Tune enabled state changed")
    end
    local current_parameters = context.current_parameters
    if type(current_parameters) ~= "table" then
      error("invalid_vocal_tuning_request: current_parameters must be a list")
    end
    local guarded_parameters = require_x42_parameter_targets(
      track,
      guarded_fx.index,
      current_parameters
    )
    for _, expected in ipairs(guarded_parameters) do
      local actual = reaper.TrackFX_GetParamNormalized(
        track,
        guarded_fx.index,
        expected.index
      )
      if math.abs(actual - expected.normalized_value) > X42_PARAMETER_EPSILON then
        error("vocal_tuning_plan_stale: x42 Auto Tune parameter changed")
      end
    end
    existing_fx = guarded_fx
  elseif #matches ~= 0 then
    error("vocal_tuning_plan_stale: x42 Auto Tune was added after preview")
  end

  return project, track, track_name, existing_fx
end

COMMANDS.apply_vocal_tuning_plugin_plan = {
  mutates_project = true,
  preflight_handler = require_vocal_tuning_plugin_plan,
  handler = function(envelope)
    local _, track, track_name, existing_fx =
      require_vocal_tuning_plugin_plan(envelope)
    local args = envelope.args
    local inserted = false
    local fx_index = existing_fx and existing_fx.index or nil
    local previous_enabled = existing_fx
      and reaper.TrackFX_GetEnabled(track, existing_fx.index)
      or nil
    local previous_parameters = {}

    local mutation_ok, mutation_error = pcall(function()
      if fx_index == nil then
        fx_index = reaper.TrackFX_AddByName(
          track,
          X42_AUTOTUNE_URI,
          false,
          -1000
        )
        if fx_index == nil or fx_index ~= 0 then
          error("postcondition_failed: x42 Auto Tune was not inserted first")
        end
        inserted = true
      end

      local fx = track_fx_snapshot(track, args.context.track_guid, fx_index)
      if fx.identifier ~= X42_AUTOTUNE_URI then
        error("postcondition_failed: inserted FX was not x42 Auto Tune")
      end
      local targets = require_x42_parameter_targets(
        track,
        fx_index,
        args.target_parameters
      )
      for _, target in ipairs(targets) do
        previous_parameters[#previous_parameters + 1] = {
          index = target.index,
          normalized_value = reaper.TrackFX_GetParamNormalized(
            track,
            fx_index,
            target.index
          ),
        }
        local set_ok = reaper.TrackFX_SetParamNormalized(
          track,
          fx_index,
          target.index,
          target.normalized_value
        )
        if set_ok == false then
          error("postcondition_failed: REAPER rejected an x42 parameter")
        end
      end
      for _, target in ipairs(targets) do
        local actual = reaper.TrackFX_GetParamNormalized(
          track,
          fx_index,
          target.index
        )
        if math.abs(actual - target.normalized_value) > X42_PARAMETER_EPSILON then
          error("postcondition_failed: x42 parameter value did not match")
        end
      end

      reaper.TrackFX_SetEnabled(track, fx_index, true)
      if not reaper.TrackFX_GetEnabled(track, fx_index) then
        error("postcondition_failed: x42 Auto Tune was not enabled")
      end
    end)

    if not mutation_ok then
      if inserted and fx_index ~= nil then
        reaper.TrackFX_Delete(track, fx_index)
      elseif existing_fx then
        for _, parameter in ipairs(previous_parameters) do
          reaper.TrackFX_SetParamNormalized(
            track,
            existing_fx.index,
            parameter.index,
            parameter.normalized_value
          )
        end
        reaper.TrackFX_SetEnabled(
          track,
          existing_fx.index,
          previous_enabled == true
        )
      end
      reaper.TrackList_AdjustWindows(false)
      reaper.UpdateArrange()
      error(tostring(mutation_error))
    end

    local parameters = {}
    local changed = inserted or previous_enabled ~= true
    for _, target in ipairs(args.target_parameters) do
      local parameter = fx_parameter_snapshot(track, fx_index, target.index)
      parameters[#parameters + 1] = parameter
      local previous = nil
      for _, before in ipairs(previous_parameters) do
        if before.index == target.index then
          previous = before.normalized_value
          break
        end
      end
      if previous == nil
        or math.abs(previous - target.normalized_value) > X42_PARAMETER_EPSILON then
        changed = true
      end
    end

    local result_fx = track_fx_snapshot(
      track,
      args.context.track_guid,
      fx_index
    )
    reaper.TrackList_AdjustWindows(false)
    reaper.UpdateArrange()
    return {
      approval_hash = args.approval_hash,
      provider_id = args.provider_id,
      track_guid = args.context.track_guid,
      track_name = track_name,
      fx = result_fx,
      parameters = parameters,
      inserted = inserted,
      changes_applied = changed,
    }
  end,
}
return true
end)())
