local function file_size(path)
  local file = io.open(path, "rb")
  if not file then
    return nil
  end
  local size = file:seek("end")
  file:close()
  return size
end

local function file_exists(path)
  return file_size(path) ~= nil
end

local function require_render_output(args)
  if type(args.render_output) ~= "table" then
    error("invalid_render_request: render_output must be an object")
  end
  local render_output = args.render_output
  if type(render_output.output_path) ~= "string" or render_output.output_path == "" then
    error("invalid_render_request: output_path must be a non-empty string")
  end
  if type(render_output.output_directory) ~= "string" or render_output.output_directory == "" then
    error("invalid_render_request: output_directory must be a non-empty string")
  end
  if type(render_output.filename) ~= "string" or render_output.filename == "" then
    error("invalid_render_request: filename must be a non-empty string")
  end
  if render_output.format ~= "wav" then
    error("invalid_render_request: only WAV render output is supported")
  end
  if render_output.overwrite ~= true and file_exists(render_output.output_path) then
    error("render_output_exists: output file already exists")
  end
  return render_output
end

local function render_pattern_from_filename(filename)
  return filename:gsub("%.wav$", ""):gsub("%.WAV$", "")
end

local RENDER_STRING_SETTINGS = {
  "RENDER_FILE",
  "RENDER_PATTERN",
  "RENDER_FORMAT",
  "RENDER_FORMAT2",
  "RENDER_EXTRAFILEDIR",
}

local RENDER_NUMBER_SETTINGS = {
  "RENDER_BOUNDSFLAG",
  "RENDER_SETTINGS",
  "RENDER_CHANNELS",
  "RENDER_SRATE",
  "RENDER_STARTPOS",
  "RENDER_ENDPOS",
  "RENDER_TAILFLAG",
  "RENDER_TAILMS",
  "RENDER_ADDTOPROJ",
  "RENDER_DITHER",
  "RENDER_NORMALIZE",
  "RENDER_NORMALIZE_TARGET",
  "RENDER_BRICKWALL",
  "RENDER_FADEIN",
  "RENDER_FADEOUT",
  "RENDER_FADEINSHAPE",
  "RENDER_FADEOUTSHAPE",
  "RENDER_FADELPF",
  "RENDER_PADSTART",
  "RENDER_PADEND",
  "RENDER_TRIMSTART",
  "RENDER_TRIMEND",
  "RENDER_DELAY",
}

local function trace_render(trace, stage, detail)
  trace[#trace + 1] = {
    stage = stage,
    elapsed_ms = math.floor((bridge_clock() - CURRENT_RENDER_TRACE_STARTED_AT) * 1000),
    detail = detail or "",
  }
end

local function snapshot_render_settings(project)
  local snapshot = { strings = {}, numbers = {} }
  for _, name in ipairs(RENDER_STRING_SETTINGS) do
    snapshot.strings[name] = safe_string_call(
      reaper.GetSetProjectInfo_String,
      "",
      project,
      name,
      "",
      false
    )
  end
  for _, name in ipairs(RENDER_NUMBER_SETTINGS) do
    snapshot.numbers[name] = safe_number_call(
      reaper.GetSetProjectInfo,
      0,
      project,
      name,
      0,
      false
    )
  end
  return snapshot
end

local function apply_render_setting(project, name, value)
  local ok
  if type(value) == "string" then
    ok = reaper.GetSetProjectInfo_String(project, name, value, true)
  else
    ok = reaper.GetSetProjectInfo(project, name, value, true)
  end
  if ok == false then
    error("render_failed: REAPER rejected render setting " .. name)
  end
end

local function restore_render_settings(project, snapshot)
  for _, name in ipairs(RENDER_STRING_SETTINGS) do
    apply_render_setting(project, name, snapshot.strings[name] or "")
  end
  for _, name in ipairs(RENDER_NUMBER_SETTINGS) do
    apply_render_setting(project, name, snapshot.numbers[name] or 0)
  end
end

local function render_settings_match(project, snapshot)
  for _, name in ipairs(RENDER_STRING_SETTINGS) do
    local current = safe_string_call(
      reaper.GetSetProjectInfo_String,
      "",
      project,
      name,
      "",
      false
    )
    if current ~= (snapshot.strings[name] or "") then
      return false, name
    end
  end
  for _, name in ipairs(RENDER_NUMBER_SETTINGS) do
    local current = safe_number_call(
      reaper.GetSetProjectInfo,
      0,
      project,
      name,
      0,
      false
    )
    if math.abs(current - (snapshot.numbers[name] or 0)) > 0.000001 then
      return false, name
    end
  end
  return true, nil
end

local function render_temp_path(render_output, job_id)
  local filename = render_output.filename
  local stem = filename:gsub("%.wav$", ""):gsub("%.WAV$", "")
  local safe_id = tostring(job_id):gsub("[^%w%-_]", "_")
  return path_join(
    render_output.output_directory,
    stem .. ".reaper-mcp-" .. safe_id .. ".wav"
  )
end

local function require_render_sidecars(path)
  for _, suffix in ipairs({ ".RPP", ".RPP-bak" }) do
    if file_exists(path .. suffix) then
      error("render_output_exists: render sidecar already exists at " .. path .. suffix)
    end
  end
end

local function render_error_response(job_id, error_text, trace)
  local code = "render_failed"
  local message = "REAPER failed to render the project."
  local recoverable = true
  local suggested_action = "Inspect the render trace and retry."
  local mappings = {
    { "render_output_exists:", "render_output_exists", "The render output or sidecar already exists.", "Set overwrite to true or choose a different output path." },
    { "render_output_not_stable:", "render_output_not_stable", "The render output did not stabilize before the deadline.", "Inspect the output file and retry with a longer timeout." },
    { "render_output_replace_failed:", "render_output_replace_failed", "The verified render could not replace the requested output.", "Check file permissions and retry with a different output path." },
    { "render_state_not_restored:", "render_state_not_restored", "The render transaction could not restore project state.", "Inspect the trace, verify REAPER state, and restart the bridge before retrying." },
    { "render_busy:", "render_busy", "Another render job is already active.", "Wait for the active render job to finish before starting another render." },
    { "render_timeout:", "render_timeout", "The render job exceeded its bridge deadline.", "Inspect the output and poll the render job again before retrying." },
    { "invalid_render_request:", "invalid_render_request", "The render request is invalid.", "Check the output path, format, and overwrite values." },
  }
  for _, mapping in ipairs(mappings) do
    if error_text:find(mapping[1], 1, true) then
      code = mapping[2]
      message = mapping[3]
      suggested_action = mapping[4]
      break
    end
  end
  if error_text:find("render_state_not_restored:", 1, true) then
    recoverable = false
  end
  return response_payload(job_id, false, nil, {
    code = code,
    message = message,
    details = {
      command = "render_project",
      error = error_text,
      trace = trace or {},
    },
    recoverable = recoverable,
    suggested_action = suggested_action,
  })
end

local function restore_render_job(job)
  if job.restored then
    return
  end
  job.restored = true
  trace_render(job.trace, "settings_restore_started")
  local ok, restore_error = pcall(function()
    restore_render_settings(job.project, job.snapshot)
  end)
  if not ok then
    error("render_state_not_restored: " .. tostring(restore_error))
  end
  trace_render(job.trace, "settings_restored")
end

local function verify_render_transaction(job)
  local settings_match, mismatched_setting = render_settings_match(
    job.project,
    job.snapshot
  )
  if not settings_match then
    error("render_state_not_restored: setting mismatch for " .. tostring(mismatched_setting))
  end
  local dirty_after = safe_number_call(reaper.IsProjectDirty, 0, job.project) ~= 0
  if job.dirty_before ~= dirty_after then
    error("render_state_not_restored: project dirty state changed")
  end
  trace_render(job.trace, "transaction_verified")
  return dirty_after
end

local function replace_render_output(job)
  if not job.uses_temp_path then
    return false
  end
  local final_path = job.final_output_path
  local temp_path = job.render_output_path
  local backup_path = final_path .. ".reaper-mcp-backup-" .. job.id
  local had_existing_output = file_exists(final_path)
  if had_existing_output then
    if file_exists(backup_path) then
      error("render_output_replace_failed: render backup path already exists")
    end
    local moved = os.rename(final_path, backup_path)
    if not moved then
      error("render_output_replace_failed: could not stage the existing output")
    end
  end
  local replaced = os.rename(temp_path, final_path)
  if not replaced then
    if had_existing_output then
      os.rename(backup_path, final_path)
    end
    error("render_output_replace_failed: could not promote the verified output")
  end
  if had_existing_output then
    local removed_backup = os.remove(backup_path)
    if not removed_backup and file_exists(backup_path) then
      error("render_output_replace_failed: could not remove the output backup")
    end
  end
  return had_existing_output
end

local function cleanup_render_sidecars(path)
  for _, suffix in ipairs({ ".RPP", ".RPP-bak" }) do
    local sidecar = path .. suffix
    if file_exists(sidecar) then
      local removed = os.remove(sidecar)
      if not removed and file_exists(sidecar) then
        error("render_failed: could not remove render sidecar " .. sidecar)
      end
    end
  end
end

local function start_render_job(envelope)
  if ACTIVE_RENDER_JOB ~= nil then
    error("render_busy: another render job is already active")
  end
  local project = current_project()
  local render_output = require_render_output(envelope.args)
  local uses_temp_path = render_output.overwrite == true
  local render_output_path = uses_temp_path
    and render_temp_path(render_output, envelope.id)
    or render_output.output_path
  if uses_temp_path and file_exists(render_output_path) then
    error("render_output_exists: temporary render output already exists")
  end
  require_render_sidecars(render_output.output_path)
  require_render_sidecars(render_output_path)

  local trace = {}
  CURRENT_RENDER_TRACE = trace
  CURRENT_RENDER_TRACE_STARTED_AT = bridge_clock()
  CURRENT_RENDER_JOB_ID = envelope.id
  trace_render(trace, "snapshot_started")
  local job = {
    id = envelope.id,
    project = project,
    final_output_path = render_output.output_path,
    render_output_path = render_output_path,
    output_directory = render_output.output_directory,
    overwrite = render_output.overwrite == true,
    uses_temp_path = uses_temp_path,
    dirty_before = safe_number_call(reaper.IsProjectDirty, 0, project) ~= 0,
    snapshot = snapshot_render_settings(project),
    trace = trace,
    status = "running",
    started_at = bridge_clock(),
    deadline = bridge_clock() + RENDER_DEADLINE_SECONDS,
    last_size = nil,
    stable_polls = 0,
    restored = false,
    output_overwritten = false,
    idempotency_key = envelope.options.idempotency_key,
  }
  trace_render(trace, "snapshot_captured")
  local ok, start_error = xpcall(function()
    trace_render(trace, "settings_apply_started")
    apply_render_setting(project, "RENDER_FILE", render_output.output_directory)
    local render_filename = render_output.filename
    if uses_temp_path then
      render_filename = render_output_path:match("[^/\\]+$")
    end
    apply_render_setting(project, "RENDER_PATTERN", render_pattern_from_filename(render_filename))
    apply_render_setting(project, "RENDER_FORMAT", "evaw")
    apply_render_setting(project, "RENDER_FORMAT2", "")
    apply_render_setting(project, "RENDER_BOUNDSFLAG", 1)
    apply_render_setting(project, "RENDER_SETTINGS", 0)
    apply_render_setting(project, "RENDER_ADDTOPROJ", 0)
    trace_render(trace, "settings_applied", "master_wav_only")
    trace_render(trace, "render_42230_started")
    _, job.render_stats = reaper.GetSetProjectInfo_String(
      project,
      "RENDER_STATS",
      "42230",
      false
    )
    trace_render(trace, "render_42230_returned")
  end, function(err)
    return tostring(err)
  end)
  if not ok then
    local restore_ok, restore_error = pcall(function()
      restore_render_job(job)
    end)
    if not restore_ok then
      start_error = tostring(start_error) .. "; " .. tostring(restore_error)
    end
    error(tostring(start_error))
  end
  ACTIVE_RENDER_JOB = job
  write_render_job_progress(envelope.id, {
    job_id = envelope.id,
    scope = "project",
    status = "running",
    output_path = render_output.output_path,
    overwrite = render_output.overwrite == true,
    trace = trace,
  })
  return {
    job_id = envelope.id,
    scope = "project",
    status = "started",
    output_path = render_output.output_path,
    overwrite = render_output.overwrite == true,
  }
end

local function complete_render_job(job)
  local size = file_size(job.render_output_path)
  if not size or size <= 0 then
    error("render_output_not_stable: render output is missing or empty")
  end
  cleanup_render_sidecars(job.render_output_path)
  job.output_overwritten = replace_render_output(job)
  local final_size = file_size(job.final_output_path)
  if not final_size or final_size <= 0 then
    error("render_output_not_stable: final render output is missing or empty")
  end
  local _, render_stats_summary = reaper.GetSetProjectInfo_String(
    job.project,
    "RENDER_STATS_SUMMARY",
    "",
    false
  )
  restore_render_job(job)
  local dirty_after = verify_render_transaction(job)
  job.status = "completed"
  local result = {
    scope = "project",
    status = "completed",
    primary_output_path = job.final_output_path,
    output_files = {
      {
        path = job.final_output_path,
        size_bytes = final_size,
        exists = true,
      },
    },
    output_file_count = 1,
    render_stats = job.render_stats or "",
    render_stats_summary = render_stats_summary or "",
    transaction = {
      settings_restored = true,
      dirty_state_before = job.dirty_before,
      dirty_state_after = dirty_after,
      dirty_state_preserved = job.dirty_before == dirty_after,
      output_overwritten = job.output_overwritten,
      trace = job.trace,
    },
  }
  write_render_job_response(job.id, response_payload(job.id, true, result))
  return result
end

local function fail_render_job(job, error_text)
  local restore_ok, restore_error = pcall(function()
    restore_render_job(job)
  end)
  if not restore_ok then
    error_text = tostring(error_text) .. "; " .. tostring(restore_error)
  end
  job.status = "failed"
  write_render_job_response(job.id, render_error_response(job.id, tostring(error_text), job.trace))
end

local function tick_render_job()
  local job = ACTIVE_RENDER_JOB
  if not job then
    return
  end
  local size = file_size(job.render_output_path)
  if size and size > 0 then
    if size == job.last_size then
      job.stable_polls = job.stable_polls + 1
    else
      job.last_size = size
      job.stable_polls = 1
    end
  else
    job.last_size = nil
    job.stable_polls = 0
  end
  trace_render(job.trace, "output_polled", tostring(size or 0))
  if job.stable_polls >= RENDER_STABLE_POLLS then
    local ok, result_or_error = xpcall(function()
      return complete_render_job(job)
    end, function(err)
      return tostring(err)
    end)
    if not ok then
      fail_render_job(job, result_or_error)
    end
    ACTIVE_RENDER_JOB = nil
    CURRENT_RENDER_TRACE = nil
    CURRENT_RENDER_TRACE_STARTED_AT = nil
    CURRENT_RENDER_JOB_ID = nil
    return
  end
  if bridge_clock() >= job.deadline then
    local ok, timeout_error = xpcall(function()
      error("render_timeout: render output did not stabilize before the deadline")
    end, function(err)
      return tostring(err)
    end)
    fail_render_job(job, ok and timeout_error or tostring(timeout_error))
    ACTIVE_RENDER_JOB = nil
    CURRENT_RENDER_TRACE = nil
    CURRENT_RENDER_TRACE_STARTED_AT = nil
    CURRENT_RENDER_JOB_ID = nil
    return
  end
  write_render_job_progress(job.id, {
    job_id = job.id,
    scope = "project",
    status = "running",
    output_path = job.final_output_path,
    overwrite = job.overwrite,
    trace = job.trace,
  })
end

COMMANDS.render_project = {
  mutates_project = false,
  handler = function(envelope)
    return start_render_job(envelope)
  end,
}

COMMANDS.prepare_render_snapshot = {
  mutates_project = false,
  handler = function(envelope)
    local project = current_project()
    local render_output = require_render_output(envelope.args)
    local snapshot_path = envelope.args.snapshot_path
    if type(snapshot_path) ~= "string" or snapshot_path == "" then
      error("invalid_render_request: snapshot_path must be a non-empty string")
    end
    if file_exists(snapshot_path) then
      error("render_snapshot_failed: snapshot path already exists")
    end
    local trace = {}
    local started_at = bridge_clock()
    local dirty_before = safe_number_call(reaper.IsProjectDirty, 0, project) ~= 0
    local settings = snapshot_render_settings(project)
    local function trace_snapshot(stage, detail)
      trace[#trace + 1] = {
        stage = stage,
        elapsed_ms = math.floor((bridge_clock() - started_at) * 1000),
        detail = detail or "",
      }
    end

    trace_snapshot("snapshot_captured")
    local ok, snapshot_error = xpcall(function()
      apply_render_setting(project, "RENDER_FILE", render_output.output_directory)
      apply_render_setting(project, "RENDER_PATTERN", render_pattern_from_filename(render_output.filename))
      apply_render_setting(project, "RENDER_FORMAT", "evaw")
      apply_render_setting(project, "RENDER_FORMAT2", "")
      apply_render_setting(project, "RENDER_BOUNDSFLAG", 1)
      apply_render_setting(project, "RENDER_SETTINGS", 0)
      apply_render_setting(project, "RENDER_ADDTOPROJ", 0)
      reaper.Main_SaveProjectEx(project, snapshot_path, 0)
      if not file_exists(snapshot_path) then
        error("render_snapshot_failed: REAPER did not write the snapshot")
      end
      trace_snapshot("snapshot_saved", snapshot_path)
    end, function(err)
      return tostring(err)
    end)

    local restore_ok, restore_error = pcall(function()
      restore_render_settings(project, settings)
    end)
    if not restore_ok then
      error("render_state_not_restored: " .. tostring(restore_error))
    end
    local dirty_after = safe_number_call(reaper.IsProjectDirty, 0, project) ~= 0
    if dirty_before ~= dirty_after then
      error("render_state_not_restored: project dirty state changed")
    end
    trace_snapshot("transaction_verified")
    if not ok then
      error(tostring(snapshot_error))
    end
    return {
      status = "prepared",
      snapshot_path = snapshot_path,
      transaction = {
        settings_restored = true,
        dirty_state_before = dirty_before,
        dirty_state_after = dirty_after,
        dirty_state_preserved = dirty_before == dirty_after,
        output_overwritten = false,
        trace = trace,
      },
      trace = trace,
    }
  end,
}

local SONG_STARTER_PARTS = {
  { role = "drums", name = "Drums" },
  { role = "bass", name = "Bass" },
  { role = "chords", name = "Chords" },
  { role = "lead", name = "Lead" },
}

local SONG_STARTER_PROGRESSIONS = {
  major = {
    { degree = 0, intervals = { 0, 4, 7 } },
    { degree = 7, intervals = { 0, 4, 7 } },
    { degree = 9, intervals = { 0, 3, 7 } },
    { degree = 5, intervals = { 0, 4, 7 } },
  },
  minor = {
    { degree = 0, intervals = { 0, 3, 7 } },
    { degree = 8, intervals = { 0, 4, 7 } },
    { degree = 3, intervals = { 0, 4, 7 } },
    { degree = 10, intervals = { 0, 4, 7 } },
  },
}

return {
  active_job = function()
    return ACTIVE_RENDER_JOB
  end,
  current_trace = function()
    return CURRENT_RENDER_TRACE
  end,
  error_response = render_error_response,
  reset_request_state = function()
    CURRENT_RENDER_TRACE = nil
    CURRENT_RENDER_TRACE_STARTED_AT = nil
    CURRENT_RENDER_JOB_ID = nil
  end,
  start = start_render_job,
  tick = tick_render_job,
}
