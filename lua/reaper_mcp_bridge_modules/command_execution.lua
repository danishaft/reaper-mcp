local function expanded_command_error(request_id, envelope, error_text)
  local errors = {
    {
      prefix = "invalid_envelope_reference:",
      code = "invalid_envelope_reference",
      message = "The envelope or point identity no longer matches the project.",
      action = "Refresh track envelopes and points, then retry with current identities.",
    },
    {
      prefix = "invalid_automation_request:",
      code = "invalid_automation_request",
      message = "The automation envelope request is invalid.",
      action = "Check envelope point values, ranges, and guarded identities.",
    },
    {
      prefix = "invalid_take_request:",
      code = "invalid_take_request",
      message = "The media take request is invalid or REAPER rejected it.",
      action = "Refresh item takes and retry with supported values.",
    },
    {
      prefix = "invalid_navigation_request:",
      code = "invalid_navigation_request",
      message = "The project navigation request is invalid.",
      action = "Check cursor, range, loop, and project path values.",
    },
    {
      prefix = "project_save_failed:",
      code = "project_save_failed",
      message = "REAPER could not confirm the requested project save.",
      action = "Check the project path and permissions, then retry.",
    },
    {
      prefix = "invalid_track_request:",
      code = "invalid_track_request",
      message = "The track request is invalid or REAPER rejected it.",
      action = "Refresh tracks and retry with supported track values.",
    },
    {
      prefix = "invalid_fx_request:",
      code = "invalid_fx_request",
      message = "The FX request is invalid or REAPER rejected it.",
      action = "Refresh the FX chain and retry with supported values.",
    },
    {
      prefix = "invalid_mastering_request:",
      code = "invalid_mastering_request",
      message = "The mastering plan request is invalid.",
      action = "Preview a complete current plan and retry with its exact hash.",
    },
    {
      prefix = "invalid_vocal_tuning_request:",
      code = "invalid_vocal_tuning_request",
      message = "The vocal tuning plan request is invalid.",
      action = "Check the provider, target state, corrections, or named preset.",
    },
    {
      prefix = "vocal_tuning_plan_stale:",
      code = "vocal_tuning_plan_stale",
      message = "The vocal tuning plan no longer matches current REAPER state.",
      action = "Refresh the target state, then preview and approve a new plan.",
    },
    {
      prefix = "vocal_tuning_provider_unavailable:",
      code = "vocal_tuning_provider_unavailable",
      message = "The tuning provider has no verified control path.",
      action = "Use an installed provider and one of its reported control modes.",
    },
    {
      prefix = "mastering_plan_stale:",
      code = "mastering_plan_stale",
      message = "The mastering plan no longer matches current REAPER state.",
      action = "Refresh the source, project, and master chain, then preview again.",
    },
    {
      prefix = "invalid_midi_controller_request:",
      code = "invalid_midi_controller_request",
      message = "The MIDI controller request is invalid.",
      action = "Refresh controller events and check event values.",
    },
    {
      prefix = "midi_controller_conflict:",
      code = "midi_controller_conflict",
      message = "The MIDI controller identity no longer matches the take.",
      action = "Refresh controller events and retry with the current identity.",
    },
    {
      prefix = "midi_controller_insert_failed:",
      code = "midi_controller_insert_failed",
      message = "REAPER rejected the MIDI controller insertion.",
      action = "Refresh the MIDI take and retry the controller insertion.",
    },
    {
      prefix = "tempo_marker_conflict:",
      code = "tempo_marker_conflict",
      message = "The tempo marker identity no longer matches the project.",
      action = "Refresh tempo markers and retry with the current identity.",
    },
    {
      prefix = "audio_loudness_failed:",
      code = "audio_loudness_failed",
      message = "REAPER could not calculate loudness for the requested take.",
      action = "Refresh the take and confirm that it has a readable media source.",
    },
    {
      prefix = "template_path_not_allowed:",
      code = "template_path_not_allowed",
      message = "The track template path or file is not allowed.",
      action = "Choose an approved .RTrackTemplate path and retry.",
    },
    {
      prefix = "postcondition_failed:",
      code = "postcondition_failed",
      message = "REAPER did not confirm the requested project state.",
      action = "Inspect or undo the change, refresh project state, and retry if needed.",
    },
  }
  for _, definition in ipairs(errors) do
    if error_text:find(definition.prefix, 1, true) then
      return error_payload(
        request_id,
        definition.code,
        definition.message,
        { command = envelope.command, error = error_text },
        true,
        definition.action
      )
    end
  end
  return nil
end

local function execute_read_command(request_id, command_definition, envelope)
  local ok, result = pcall(command_definition.handler, envelope)
  if ok then
    return response_payload(request_id, true, result)
  end
  local error_text = tostring(result)
  local expanded_error = expanded_command_error(request_id, envelope, error_text)
  if expanded_error then
    return expanded_error
  end
  if error_text:find("record_requires_armed_track:", 1, true) then
    return error_payload(
      request_id,
      "record_requires_armed_track",
      "Recording requires at least one armed track.",
      { command = envelope.command, error = error_text },
      true,
      "Arm a track before starting recording."
    )
  end
  if error_text:find("recording_stop_requires_stop_recording:", 1, true) then
    return error_payload(
      request_id,
      "recording_stop_requires_stop_recording",
      "Stopping an active recording requires the stop_recording command.",
      { command = envelope.command, error = error_text },
      true,
      "Use stop_recording so the recording stop is undoable."
    )
  end
  if error_text:find("invalid_track_reference:", 1, true) then
    return error_payload(
      request_id,
      "invalid_track_reference",
      "The requested REAPER track could not be resolved.",
      { command = envelope.command, error = error_text },
      true,
      "Refresh the track list and retry with a current track_guid."
    )
  end
  if error_text:find("invalid_send_reference:", 1, true) then
    return error_payload(
      request_id,
      "invalid_send_reference",
      "The track send identity no longer matches the project.",
      { command = envelope.command, error = error_text },
      true,
      "Refresh track sends and retry with the current send identity."
    )
  end
  if error_text:find("invalid_time_position:", 1, true) then
    return error_payload(
      request_id,
      "invalid_time_position",
      "The musical position or duration is invalid.",
      { command = envelope.command, error = error_text },
      true,
      "Check measure, beat, and length values."
    )
  end
  if error_text:find("invalid_take_reference:", 1, true) then
    return error_payload(
      request_id,
      "invalid_take_reference",
      "The requested media take could not be resolved.",
      { command = envelope.command, error = error_text },
      true,
      "Refresh item takes and retry with a current take GUID."
    )
  end
  if error_text:find("fx_not_found:", 1, true) then
    return error_payload(
      request_id,
      "fx_not_found",
      "The requested FX could not be resolved.",
      { command = envelope.command, error = error_text },
      true,
      "Refresh available FX or track FX and retry with current identifiers."
    )
  end
  if error_text:find("invalid_fx_reference:", 1, true) then
    return error_payload(
      request_id,
      "invalid_fx_reference",
      "The FX identity no longer matches the track FX chain.",
      { command = envelope.command, error = error_text },
      true,
      "Refresh track FX and retry with the current FX identity."
    )
  end
  if error_text:find("invalid_fx_parameter:", 1, true) then
    return error_payload(
      request_id,
      "invalid_fx_parameter",
      "The FX parameter request is invalid.",
      { command = envelope.command, error = error_text },
      true,
      "Use a normalized parameter value between 0.0 and 1.0."
    )
  end
  if error_text:find("fx_parameter_not_found:", 1, true) then
    return error_payload(
      request_id,
      "fx_parameter_not_found",
      "The requested FX parameter could not be resolved.",
      { command = envelope.command, error = error_text },
      true,
      "Refresh FX parameters and retry with a current parameter index."
    )
  end
  if error_text:find("marker_not_found:", 1, true) then
    return error_payload(
      request_id,
      "marker_not_found",
      "The requested marker could not be resolved.",
      { command = envelope.command, error = error_text },
      true,
      "Refresh markers and retry with a current marker ID."
    )
  end
  if error_text:find("invalid_marker_reference:", 1, true) then
    return error_payload(
      request_id,
      "invalid_marker_reference",
      "The marker identity no longer matches the project.",
      { command = envelope.command, error = error_text },
      true,
      "Refresh markers and retry with current marker details."
    )
  end
  if error_text:find("region_not_found:", 1, true) then
    return error_payload(
      request_id,
      "region_not_found",
      "The requested region could not be resolved.",
      { command = envelope.command, error = error_text },
      true,
      "Refresh regions and retry with a current region ID."
    )
  end
  if error_text:find("invalid_region_reference:", 1, true) then
    return error_payload(
      request_id,
      "invalid_region_reference",
      "The region identity no longer matches the project.",
      { command = envelope.command, error = error_text },
      true,
      "Refresh regions and retry with current region details."
    )
  end
  if error_text:find("invalid_tempo_request:", 1, true) then
    return error_payload(
      request_id,
      "invalid_tempo_request",
      "The tempo or time signature request is invalid.",
      { command = envelope.command, error = error_text },
      true,
      "Check BPM, numerator, and denominator values."
    )
  end
  if error_text:find("invalid_render_request:", 1, true) then
    return error_payload(
      request_id,
      "invalid_render_request",
      "The render request is invalid.",
      { command = envelope.command, error = error_text },
      true,
      "Check render output path, format, and overwrite values."
    )
  end
  if error_text:find("render_output_exists:", 1, true) then
    return error_payload(
      request_id,
      "render_output_exists",
      "The render output file already exists.",
      render_error_details(envelope, error_text),
      true,
      "Set overwrite to true or choose a different output path."
    )
  end
  if error_text:find("render_failed:", 1, true) then
    return error_payload(
      request_id,
      "render_failed",
      "REAPER failed to render the project.",
      render_error_details(envelope, error_text),
      true,
      "Check REAPER render settings and retry."
    )
  end
  if error_text:find("render_output_remove_failed:", 1, true) then
    return error_payload(
      request_id,
      "render_output_remove_failed",
      "REAPER could not remove the existing render output.",
      render_error_details(envelope, error_text),
      true,
      "Check file permissions or choose a different output path."
    )
  end
  if error_text:find("render_snapshot_failed:", 1, true) then
    return error_payload(
      request_id,
      "render_snapshot_failed",
      "REAPER could not create the isolated render snapshot.",
      { command = envelope.command, error = error_text },
      true,
      "Check the snapshot directory and project media paths, then retry."
    )
  end
  if error_text:find("render_state_not_restored:", 1, true) then
    return error_payload(
      request_id,
      "render_state_not_restored",
      "The render transaction could not restore project state.",
      render_error_details(envelope, error_text),
      false,
      "Inspect the trace, verify REAPER state, and restart the bridge before retrying."
    )
  end
  if error_text:find("render_not_implemented:", 1, true) then
    return error_payload(
      request_id,
      "render_not_implemented",
      "The render bridge command is a Phase 6A skeleton and is not implemented yet.",
      { command = envelope.command, error = error_text },
      false,
      "Use Phase 6B render tools after render execution is implemented."
    )
  end
  return error_payload(
    request_id,
    "reaper_not_available",
    "The Lua bridge command failed while calling REAPER.",
    { command = envelope.command, error = error_text },
    true,
    "Check REAPER state and retry the command."
  )
end

local function execute_mutating_command(request_id, command_definition, envelope)
  if envelope.options.dry_run then
    if not command_definition.dry_run_handler then
      return response_payload(request_id, true, {
        dry_run = true,
        command = envelope.command,
        would_mutate_project = true,
        changes_applied = false,
      })
    end
    local ok, result = pcall(command_definition.dry_run_handler, envelope)
    if ok then
      return response_payload(request_id, true, result)
    end
    return error_payload(
      request_id,
      "reaper_not_available",
      "The Lua bridge dry run failed while calling REAPER.",
      { command = envelope.command, error = tostring(result) },
      true,
      "Check REAPER state and retry the command."
    )
  end

  if envelope.options.undo_label == nil or envelope.options.undo_label == "" then
    return error_payload(
      request_id,
      "mutation_undo_required",
      "Mutating bridge commands require options.undo_label.",
      { command = envelope.command },
      false,
      "Provide a non-empty undo label for mutating commands."
    )
  end

  if command_definition.preflight_handler then
    local preflight_ok, preflight_error = pcall(command_definition.preflight_handler, envelope)
    if not preflight_ok then
      local error_text = tostring(preflight_error)
      local expanded_error = expanded_command_error(request_id, envelope, error_text)
      if expanded_error then
        return expanded_error
      end
      if error_text:find("invalid_track_reference:", 1, true) then
        return error_payload(
          request_id,
          "invalid_track_reference",
          "The requested REAPER track could not be resolved.",
          { command = envelope.command, error = error_text },
          true,
          "Refresh the track list and retry with a current track_guid."
        )
      end
      if error_text:find("invalid_send_reference:", 1, true) then
        return error_payload(
          request_id,
          "invalid_send_reference",
          "The track send identity no longer matches the project.",
          { command = envelope.command, error = error_text },
          true,
          "Refresh track sends and retry with the current send identity."
        )
      end
      if error_text:find("track_already_frozen:", 1, true) then
        return error_payload(
          request_id,
          "track_already_frozen",
          "The track is already frozen.",
          { command = envelope.command, error = error_text },
          true,
          "Call get_track_freeze_state or unfreeze the track first."
        )
      end
      if error_text:find("track_not_frozen:", 1, true) then
        return error_payload(
          request_id,
          "track_not_frozen",
          "The track has no freeze state to remove.",
          { command = envelope.command, error = error_text },
          true,
          "Call get_track_freeze_state before unfreezing."
        )
      end
      if error_text:find("track_freeze_failed:", 1, true) then
        return error_payload(
          request_id,
          "track_freeze_failed",
          "REAPER did not complete the track freeze operation.",
          { command = envelope.command, error = error_text },
          true,
          "Check track content and render settings, then retry."
        )
      end
      if error_text:find("record_requires_armed_track:", 1, true) then
        return error_payload(
          request_id,
          "record_requires_armed_track",
          "Recording requires at least one armed track.",
          { command = envelope.command, error = error_text },
          true,
          "Arm a track before starting recording."
        )
      end
      if error_text:find("not_recording:", 1, true) then
        return error_payload(
          request_id,
          "not_recording",
          "REAPER is not currently recording.",
          { command = envelope.command, error = error_text },
          true,
          "Use stop for playback, or start recording before calling stop_recording."
        )
      end
      if error_text:find("invalid_time_position:", 1, true) then
        return error_payload(
          request_id,
          "invalid_time_position",
          "The musical position or duration is invalid.",
          { command = envelope.command, error = error_text },
          true,
          "Check measure, beat, and length values."
        )
      end
      if error_text:find("invalid_take_reference:", 1, true) then
        return error_payload(
          request_id,
          "invalid_take_reference",
          "The requested media take could not be resolved.",
          { command = envelope.command, error = error_text },
          true,
          "Refresh item takes and retry with a current take GUID."
        )
      end
      if error_text:find("invalid_media_item_request:", 1, true) then
        return error_payload(
          request_id,
          "invalid_media_item_request",
          "The media item request is invalid.",
          { command = envelope.command, error = error_text },
          true,
          "Check the track GUID, source path, and musical position values."
        )
      end
      if error_text:find("invalid_midi_note_request:", 1, true) then
        return error_payload(
          request_id,
          "invalid_midi_note_request",
          "The MIDI note request is invalid.",
          { command = envelope.command, error = error_text },
          true,
          "Check pitch, velocity, channel, and musical positions."
        )
      end
      if error_text:find("fx_not_found:", 1, true) then
        return error_payload(
          request_id,
          "fx_not_found",
          "The requested FX could not be resolved.",
          { command = envelope.command, error = error_text },
          true,
          "Refresh available FX or track FX and retry with current identifiers."
        )
      end
      if error_text:find("fx_insert_failed:", 1, true) then
        return error_payload(
          request_id,
          "fx_insert_failed",
          "REAPER rejected FX insertion.",
          { command = envelope.command, error = error_text },
          true,
          "Refresh available FX and retry with a supported FX identifier."
        )
      end
      if error_text:find("invalid_fx_reference:", 1, true) then
        return error_payload(
          request_id,
          "invalid_fx_reference",
          "The FX identity no longer matches the track FX chain.",
          { command = envelope.command, error = error_text },
          true,
          "Refresh track FX and retry with the current FX identity."
        )
      end
      if error_text:find("invalid_fx_parameter:", 1, true) then
        return error_payload(
          request_id,
          "invalid_fx_parameter",
          "The FX parameter request is invalid.",
          { command = envelope.command, error = error_text },
          true,
          "Use a normalized parameter value between 0.0 and 1.0."
        )
      end
      if error_text:find("fx_parameter_not_found:", 1, true) then
        return error_payload(
          request_id,
          "fx_parameter_not_found",
          "The requested FX parameter could not be resolved.",
          { command = envelope.command, error = error_text },
          true,
          "Refresh FX parameters and retry with a current parameter index."
        )
      end
      if error_text:find("marker_not_found:", 1, true) then
        return error_payload(
          request_id,
          "marker_not_found",
          "The requested marker could not be resolved.",
          { command = envelope.command, error = error_text },
          true,
          "Refresh markers and retry with a current marker ID."
        )
      end
      if error_text:find("invalid_marker_reference:", 1, true) then
        return error_payload(
          request_id,
          "invalid_marker_reference",
          "The marker identity no longer matches the project.",
          { command = envelope.command, error = error_text },
          true,
          "Refresh markers and retry with current marker details."
        )
      end
      if error_text:find("region_not_found:", 1, true) then
        return error_payload(
          request_id,
          "region_not_found",
          "The requested region could not be resolved.",
          { command = envelope.command, error = error_text },
          true,
          "Refresh regions and retry with a current region ID."
        )
      end
      if error_text:find("invalid_region_reference:", 1, true) then
        return error_payload(
          request_id,
          "invalid_region_reference",
          "The region identity no longer matches the project.",
          { command = envelope.command, error = error_text },
          true,
          "Refresh regions and retry with current region details."
        )
      end
      if error_text:find("invalid_tempo_request:", 1, true) then
        return error_payload(
          request_id,
          "invalid_tempo_request",
          "The tempo or time signature request is invalid.",
          { command = envelope.command, error = error_text },
          true,
          "Check BPM, numerator, and denominator values."
        )
      end
      if error_text:find("unsupported_workflow_time_signature:", 1, true) then
        return error_payload(
          request_id,
          "unsupported_workflow_time_signature",
          "The song starter currently requires a 4/4 project position.",
          { command = envelope.command, error = error_text },
          true,
          "Set the project and starter position to 4/4, then retry."
        )
      end
      if error_text:find("invalid_workflow_request:", 1, true) then
        return error_payload(
          request_id,
          "invalid_workflow_request",
          "The song starter request is invalid.",
          { command = envelope.command, error = error_text },
          true,
          "Check the name, start measure, bars, root note, and mode."
        )
      end
      if error_text:find("midi_note_conflict:", 1, true) then
        return error_payload(
          request_id,
          "midi_note_conflict",
          "The MIDI note identity no longer matches the take contents.",
          { command = envelope.command, error = error_text },
          true,
          "Refresh MIDI notes and retry with the current note index and fingerprint."
        )
      end
      return error_payload(
        request_id,
        "invalid_command_envelope",
        "The mutating command failed preflight validation.",
        { command = envelope.command, error = error_text },
        true,
        "Check the command arguments and retry."
      )
    end
  end

  local project = current_project()
  if reaper and reaper.Undo_BeginBlock2 then
    reaper.Undo_BeginBlock2(project)
  end
  local ok, result = pcall(command_definition.handler, envelope)
  if reaper and reaper.Undo_EndBlock2 then
    reaper.Undo_EndBlock2(project, envelope.options.undo_label, -1)
  end

  if ok then
    return response_payload(request_id, true, result)
  end
  local error_text = tostring(result)
  local expanded_error = expanded_command_error(request_id, envelope, error_text)
  if expanded_error then
    return expanded_error
  end
  if error_text:find("invalid_track_reference:", 1, true) then
    return error_payload(
      request_id,
      "invalid_track_reference",
      "The requested REAPER track could not be resolved.",
      { command = envelope.command, error = error_text },
      true,
      "Refresh the track list and retry with a current track_guid."
    )
  end
  if error_text:find("invalid_send_reference:", 1, true) then
    return error_payload(
      request_id,
      "invalid_send_reference",
      "The track send identity no longer matches the project.",
      { command = envelope.command, error = error_text },
      true,
      "Refresh track sends and retry with the current send identity."
    )
  end
  if error_text:find("track_already_frozen:", 1, true) then
    return error_payload(
      request_id,
      "track_already_frozen",
      "The track is already frozen.",
      { command = envelope.command, error = error_text },
      true,
      "Call get_track_freeze_state or unfreeze the track first."
    )
  end
  if error_text:find("track_not_frozen:", 1, true) then
    return error_payload(
      request_id,
      "track_not_frozen",
      "The track has no freeze state to remove.",
      { command = envelope.command, error = error_text },
      true,
      "Call get_track_freeze_state before unfreezing."
    )
  end
  if error_text:find("track_freeze_failed:", 1, true) then
    return error_payload(
      request_id,
      "track_freeze_failed",
      "REAPER did not complete the track freeze operation.",
      { command = envelope.command, error = error_text },
      true,
      "Check track content and render settings, then retry."
    )
  end
  if error_text:find("record_requires_armed_track:", 1, true) then
    return error_payload(
      request_id,
      "record_requires_armed_track",
      "Recording requires at least one armed track.",
      { command = envelope.command, error = error_text },
      true,
      "Arm a track before starting recording."
    )
  end
  if error_text:find("not_recording:", 1, true) then
    return error_payload(
      request_id,
      "not_recording",
      "REAPER is not currently recording.",
      { command = envelope.command, error = error_text },
      true,
      "Use stop for playback, or start recording before calling stop_recording."
    )
  end
  if error_text:find("invalid_time_position:", 1, true) then
    return error_payload(
      request_id,
      "invalid_time_position",
      "The musical position or duration is invalid.",
      { command = envelope.command, error = error_text },
      true,
      "Check measure, beat, and length values."
    )
  end
  if error_text:find("invalid_take_reference:", 1, true) then
    return error_payload(
      request_id,
      "invalid_take_reference",
      "The requested media take could not be resolved.",
      { command = envelope.command, error = error_text },
      true,
      "Refresh item takes and retry with a current take GUID."
    )
  end
  if error_text:find("invalid_media_item_request:", 1, true) then
    return error_payload(
      request_id,
      "invalid_media_item_request",
      "The media item request is invalid.",
      { command = envelope.command, error = error_text },
      true,
      "Check the track GUID, source path, and musical position values."
    )
  end
  if error_text:find("invalid_midi_note_request:", 1, true) then
    return error_payload(
      request_id,
      "invalid_midi_note_request",
      "The MIDI note request is invalid.",
      { command = envelope.command, error = error_text },
      true,
      "Check pitch, velocity, channel, and musical positions."
    )
  end
  if error_text:find("fx_not_found:", 1, true) then
    return error_payload(
      request_id,
      "fx_not_found",
      "The requested FX could not be resolved.",
      { command = envelope.command, error = error_text },
      true,
      "Refresh available FX or track FX and retry with current identifiers."
    )
  end
  if error_text:find("fx_insert_failed:", 1, true) then
    return error_payload(
      request_id,
      "fx_insert_failed",
      "REAPER rejected FX insertion.",
      { command = envelope.command, error = error_text },
      true,
      "Refresh available FX and retry with a supported FX identifier."
    )
  end
  if error_text:find("invalid_fx_reference:", 1, true) then
    return error_payload(
      request_id,
      "invalid_fx_reference",
      "The FX identity no longer matches the track FX chain.",
      { command = envelope.command, error = error_text },
      true,
      "Refresh track FX and retry with the current FX identity."
    )
  end
  if error_text:find("invalid_fx_parameter:", 1, true) then
    return error_payload(
      request_id,
      "invalid_fx_parameter",
      "The FX parameter request is invalid.",
      { command = envelope.command, error = error_text },
      true,
      "Use a normalized parameter value between 0.0 and 1.0."
    )
  end
  if error_text:find("fx_parameter_not_found:", 1, true) then
    return error_payload(
      request_id,
      "fx_parameter_not_found",
      "The requested FX parameter could not be resolved.",
      { command = envelope.command, error = error_text },
      true,
      "Refresh FX parameters and retry with a current parameter index."
    )
  end
  if error_text:find("marker_not_found:", 1, true) then
    return error_payload(
      request_id,
      "marker_not_found",
      "The requested marker could not be resolved.",
      { command = envelope.command, error = error_text },
      true,
      "Refresh markers and retry with a current marker ID."
    )
  end
  if error_text:find("invalid_marker_reference:", 1, true) then
    return error_payload(
      request_id,
      "invalid_marker_reference",
      "The marker identity no longer matches the project.",
      { command = envelope.command, error = error_text },
      true,
      "Refresh markers and retry with current marker details."
    )
  end
  if error_text:find("region_not_found:", 1, true) then
    return error_payload(
      request_id,
      "region_not_found",
      "The requested region could not be resolved.",
      { command = envelope.command, error = error_text },
      true,
      "Refresh regions and retry with a current region ID."
    )
  end
  if error_text:find("invalid_region_reference:", 1, true) then
    return error_payload(
      request_id,
      "invalid_region_reference",
      "The region identity no longer matches the project.",
      { command = envelope.command, error = error_text },
      true,
      "Refresh regions and retry with current region details."
    )
  end
  if error_text:find("invalid_tempo_request:", 1, true) then
    return error_payload(
      request_id,
      "invalid_tempo_request",
      "The tempo or time signature request is invalid.",
      { command = envelope.command, error = error_text },
      true,
      "Check BPM, numerator, and denominator values."
    )
  end
  if error_text:find("workflow_creation_failed:", 1, true) then
    return error_payload(
      request_id,
      "workflow_creation_failed",
      "REAPER could not create the complete song starter, so partial work was removed.",
      { command = envelope.command, error = error_text },
      true,
      "Inspect the project state and retry in a 4/4 project."
    )
  end
  if error_text:find("midi_insert_failed:", 1, true) then
    return error_payload(
      request_id,
      "midi_insert_failed",
      "REAPER rejected one MIDI note insert.",
      { command = envelope.command, error = error_text },
      true,
      "Check note timing and retry after refreshing the MIDI take."
    )
  end
  if error_text:find("midi_note_conflict:", 1, true) then
    return error_payload(
      request_id,
      "midi_note_conflict",
      "The MIDI note identity no longer matches the take contents.",
      { command = envelope.command, error = error_text },
      true,
      "Refresh MIDI notes and retry with the current note index and fingerprint."
    )
  end
  return error_payload(
    request_id,
    "reaper_not_available",
    "The Lua bridge mutating command failed while calling REAPER.",
    { command = envelope.command, error = error_text },
    true,
    "Undo the REAPER action if needed, then retry after checking project state."
  )
end

local function execute_command(envelope)
  local command_definition = COMMANDS[envelope.command]
  if not command_definition then
    return error_payload(
      envelope.id,
      "unsupported_command",
      "The Lua bridge does not support this command.",
      { command = envelope.command },
      false,
      "Use a command supported by the current bridge version."
    )
  end

  if envelope.options.mutates_project ~= command_definition.mutates_project then
    return error_payload(
      envelope.id,
      "invalid_command_envelope",
      "Envelope mutation metadata does not match bridge command classification.",
      {
        command = envelope.command,
        expected_mutates_project = command_definition.mutates_project,
        received_mutates_project = envelope.options.mutates_project,
      },
      false,
      "Use the command envelope mutation flag defined by the bridge."
    )
  end

  if command_definition.mutates_project then
    return execute_mutating_command(envelope.id, command_definition, envelope)
  end
  return execute_read_command(envelope.id, command_definition, envelope)
end

return execute_command
