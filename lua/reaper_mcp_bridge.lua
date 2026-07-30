-- File bridge for REAPER MCP.
-- Run this script inside REAPER as a deferred ReaScript.

local BRIDGE_VERSION = "0.1.0"
local SEP = package.config:sub(1, 1)
local START_TIME = os.time()

local function path_join(left, right)
  if left:sub(-1) == SEP then
    return left .. right
  end
  return left .. SEP .. right
end

local function default_temp_dir()
  return os.getenv("TMPDIR") or os.getenv("TEMP") or os.getenv("TMP") or "/tmp"
end

local function current_script_dir()
  local source = debug.getinfo(1, "S").source
  if source:sub(1, 1) == "@" then
    source = source:sub(2)
  end
  return source:match("^(.*)[/\\][^/\\]+$") or "."
end

local MODULE_DIR = path_join(
  current_script_dir(),
  "reaper_mcp_bridge_modules"
)

local function load_bridge_module(filename, environment)
  local module_path = path_join(MODULE_DIR, filename)
  local module_environment = setmetatable(environment, { __index = _G })
  local chunk, load_error = loadfile(module_path, "t", module_environment)
  if not chunk then
    error(
      "bridge_module_load_failed: "
        .. module_path
        .. ": "
        .. tostring(load_error)
    )
  end
  local ok, module_result = pcall(chunk)
  if not ok then
    error(
      "bridge_module_load_failed: "
        .. module_path
        .. ": "
        .. tostring(module_result)
    )
  end
  return module_result
end

local BRIDGE_DIR = os.getenv("REAPER_MCP_BRIDGE_DIR")
  or path_join(default_temp_dir(), "reaper-mcp-bridge")
local REQUESTS_DIR = path_join(BRIDGE_DIR, "requests")
local RESPONSES_DIR = path_join(BRIDGE_DIR, "responses")
local JOBS_DIR = path_join(BRIDGE_DIR, "jobs")
local HEARTBEAT_PATH = path_join(BRIDGE_DIR, "bridge.heartbeat")
local RENDER_RUNTIME = nil
local IDEMPOTENCY_STARTS = {}
local RENDER_STABLE_POLLS = 3
local RENDER_DEADLINE_SECONDS = tonumber(
  os.getenv("REAPER_MCP_RENDER_INTERNAL_DEADLINE_SECONDS") or "55"
) or 55

local function ensure_dir(path)
  if reaper and reaper.RecursiveCreateDirectory then
    reaper.RecursiveCreateDirectory(path, 0)
    return
  end
  os.execute('mkdir -p "' .. path .. '"')
end

local function read_file(path)
  local file = io.open(path, "rb")
  if not file then
    return nil
  end
  local content = file:read("*a")
  file:close()
  return content
end

local function write_file(path, content)
  local file = io.open(path, "wb")
  if not file then
    return false
  end
  file:write(content)
  file:close()
  return true
end

local function write_file_atomic(path, content)
  local temp_path = path .. ".tmp"
  if not write_file(temp_path, content) then
    return false
  end
  local ok = os.rename(temp_path, path)
  if not ok then
    os.remove(temp_path)
  end
  return ok
end

local function write_bridge_heartbeat()
  ensure_dir(BRIDGE_DIR)
  write_file_atomic(HEARTBEAT_PATH, tostring(os.time()))
end

local function bridge_clock()
  if reaper and reaper.time_precise then
    return reaper.time_precise()
  end
  return os.clock()
end

local function json_escape(value)
  value = tostring(value)
  value = value:gsub("\\", "\\\\")
  value = value:gsub('"', '\\"')
  value = value:gsub("\n", "\\n")
  value = value:gsub("\r", "\\r")
  value = value:gsub("\t", "\\t")
  return value
end

local function is_array(value)
  local count = 0
  for key, _ in pairs(value) do
    if type(key) ~= "number" then
      return false
    end
    count = count + 1
  end
  return count == #value
end

local function json_encode(value)
  local value_type = type(value)
  if value_type == "nil" then
    return "null"
  end
  if value_type == "boolean" then
    return value and "true" or "false"
  end
  if value_type == "number" then
    return tostring(value)
  end
  if value_type == "string" then
    return '"' .. json_escape(value) .. '"'
  end
  if value_type == "table" then
    local parts = {}
    if is_array(value) then
      for index = 1, #value do
        parts[#parts + 1] = json_encode(value[index])
      end
      return "[" .. table.concat(parts, ",") .. "]"
    end
    for key, item in pairs(value) do
      parts[#parts + 1] = '"' .. json_escape(key) .. '":' .. json_encode(item)
    end
    return "{" .. table.concat(parts, ",") .. "}"
  end
  return '"' .. json_escape(value) .. '"'
end

local JsonDecoder = {}
JsonDecoder.__index = JsonDecoder

local function new_json_decoder(text)
  return setmetatable({ text = text, index = 1, length = #text }, JsonDecoder)
end

function JsonDecoder:error(message)
  error(message .. " at byte " .. tostring(self.index), 0)
end

function JsonDecoder:peek()
  return self.text:sub(self.index, self.index)
end

function JsonDecoder:consume(expected)
  local current = self:peek()
  if current ~= expected then
    self:error("Expected '" .. expected .. "'")
  end
  self.index = self.index + 1
end

function JsonDecoder:skip_whitespace()
  while self.index <= self.length do
    local current = self:peek()
    if current ~= " " and current ~= "\n" and current ~= "\r" and current ~= "\t" then
      return
    end
    self.index = self.index + 1
  end
end

function JsonDecoder:parse_literal(literal, value)
  if self.text:sub(self.index, self.index + #literal - 1) ~= literal then
    self:error("Invalid JSON literal")
  end
  self.index = self.index + #literal
  return value
end

function JsonDecoder:parse_string()
  self:consume('"')
  local parts = {}
  while self.index <= self.length do
    local current = self:peek()
    if current == '"' then
      self.index = self.index + 1
      return table.concat(parts)
    end
    if current == "\\" then
      self.index = self.index + 1
      local escaped = self:peek()
      if escaped == '"' or escaped == "\\" or escaped == "/" then
        parts[#parts + 1] = escaped
      elseif escaped == "b" then
        parts[#parts + 1] = "\b"
      elseif escaped == "f" then
        parts[#parts + 1] = "\f"
      elseif escaped == "n" then
        parts[#parts + 1] = "\n"
      elseif escaped == "r" then
        parts[#parts + 1] = "\r"
      elseif escaped == "t" then
        parts[#parts + 1] = "\t"
      elseif escaped == "u" then
        self:error("Unicode escape sequences are not supported")
      else
        self:error("Invalid string escape")
      end
      self.index = self.index + 1
    else
      parts[#parts + 1] = current
      self.index = self.index + 1
    end
  end
  self:error("Unterminated string")
end

function JsonDecoder:parse_number()
  local start_index = self.index
  if self:peek() == "-" then
    self.index = self.index + 1
  end
  while self:peek():match("%d") do
    self.index = self.index + 1
  end
  if self:peek() == "." then
    self.index = self.index + 1
    while self:peek():match("%d") do
      self.index = self.index + 1
    end
  end
  local current = self:peek()
  if current == "e" or current == "E" then
    self.index = self.index + 1
    current = self:peek()
    if current == "+" or current == "-" then
      self.index = self.index + 1
    end
    while self:peek():match("%d") do
      self.index = self.index + 1
    end
  end
  local number_text = self.text:sub(start_index, self.index - 1)
  local value = tonumber(number_text)
  if value == nil then
    self:error("Invalid number")
  end
  return value
end

function JsonDecoder:parse_array()
  self:consume("[")
  self:skip_whitespace()
  local value = {}
  if self:peek() == "]" then
    self.index = self.index + 1
    return value
  end
  while true do
    value[#value + 1] = self:parse_value()
    self:skip_whitespace()
    local current = self:peek()
    if current == "]" then
      self.index = self.index + 1
      return value
    end
    self:consume(",")
    self:skip_whitespace()
  end
end

function JsonDecoder:parse_object()
  self:consume("{")
  self:skip_whitespace()
  local value = {}
  if self:peek() == "}" then
    self.index = self.index + 1
    return value
  end
  while true do
    if self:peek() ~= '"' then
      self:error("Expected object key")
    end
    local key = self:parse_string()
    self:skip_whitespace()
    self:consume(":")
    self:skip_whitespace()
    value[key] = self:parse_value()
    self:skip_whitespace()
    local current = self:peek()
    if current == "}" then
      self.index = self.index + 1
      return value
    end
    self:consume(",")
    self:skip_whitespace()
  end
end

function JsonDecoder:parse_value()
  self:skip_whitespace()
  local current = self:peek()
  if current == '"' then
    return self:parse_string()
  end
  if current == "{" then
    return self:parse_object()
  end
  if current == "[" then
    return self:parse_array()
  end
  if current == "t" then
    return self:parse_literal("true", true)
  end
  if current == "f" then
    return self:parse_literal("false", false)
  end
  if current == "n" then
    return self:parse_literal("null", nil)
  end
  if current == "-" or current:match("%d") then
    return self:parse_number()
  end
  self:error("Invalid JSON value")
end

local function json_decode(text)
  local decoder = new_json_decoder(text)
  local value = decoder:parse_value()
  decoder:skip_whitespace()
  if decoder.index <= decoder.length then
    decoder:error("Unexpected trailing content")
  end
  return value
end

local function response_payload(request_id, ok, result, error_response)
  local payload = {
    id = request_id,
    ok = ok,
    warnings = {},
  }
  if ok then
    payload.result = result or {}
  else
    payload.error = error_response or {
      code = "unsupported_command",
      message = "The Lua bridge could not execute the command.",
      details = {},
      recoverable = true,
      suggested_action = "Check the bridge command name.",
    }
  end
  return json_encode(payload)
end

local function write_render_job_progress(job_id, result)
  if not job_id then
    return
  end
  ensure_dir(JOBS_DIR)
  local payload = response_payload(job_id, true, result)
  local path = path_join(JOBS_DIR, job_id .. ".json")
  local temp_path = path .. ".tmp"
  if write_file(temp_path, payload) then
    os.rename(temp_path, path)
  end
end

local function write_render_job_response(job_id, payload)
  if not job_id then
    return
  end
  ensure_dir(JOBS_DIR)
  local path = path_join(JOBS_DIR, job_id .. ".json")
  write_file_atomic(path, payload)
end

local function error_payload(request_id, code, message, details, recoverable, suggested_action)
  return response_payload(request_id, false, nil, {
    code = code,
    message = message,
    details = details or {},
    recoverable = recoverable,
    suggested_action = suggested_action,
  })
end

local function reaper_version()
  if reaper and reaper.GetAppVersion then
    return reaper.GetAppVersion()
  end
  return "unknown"
end

local function count_request_files(active_request_id)
  local count = 0
  local index = 0
  while true do
    local filename = reaper.EnumerateFiles(REQUESTS_DIR, index)
    if not filename then
      break
    end
    if filename:match("%.json$") and filename ~= active_request_id .. ".json" then
      count = count + 1
    end
    index = index + 1
  end
  return count
end

local function current_project()
  if reaper and reaper.EnumProjects then
    local project, path = reaper.EnumProjects(-1, "")
    return project or 0, path or ""
  end
  return 0, ""
end

local function project_name(project, path)
  if reaper and reaper.GetProjectName then
    local ok, first, second = pcall(reaper.GetProjectName, project, "")
    if ok then
      if type(second) == "string" and second ~= "" then
        return second
      end
      if type(first) == "string" and first ~= "" then
        return first
      end
    end
  end
  return path:match("[^/\\]+$") or ""
end

local function project_time_signature(project)
  if reaper and reaper.GetProjectTimeSignature2 then
    local ok, bpm, beats_per_measure = pcall(reaper.GetProjectTimeSignature2, project)
    if ok then
      return bpm or 0, beats_per_measure or 0
    end
  end
  return 0, 0
end

local function safe_number_call(fn, fallback, ...)
  if not fn then
    return fallback
  end
  local ok, value = pcall(fn, ...)
  if ok and type(value) == "number" then
    return value
  end
  return fallback
end

local function safe_string_call(fn, fallback, ...)
  if not fn then
    return fallback
  end
  local ok, first, second = pcall(fn, ...)
  if ok then
    if type(second) == "string" then
      return second
    end
    if type(first) == "string" then
      return first
    end
  end
  return fallback
end

local function safe_bool_call(fn, fallback, ...)
  if not fn then
    return fallback
  end
  local ok, value = pcall(fn, ...)
  if ok and type(value) == "boolean" then
    return value
  end
  return fallback
end

local function validate_envelope(envelope)
  if type(envelope) ~= "table" then
    return nil, "Envelope must be a JSON object."
  end
  if type(envelope.id) ~= "string" or envelope.id == "" then
    return nil, "Envelope id must be a non-empty string."
  end
  if type(envelope.command) ~= "string" or envelope.command == "" then
    return nil, "Envelope command must be a non-empty string."
  end
  if envelope.args == nil then
    envelope.args = {}
  end
  if type(envelope.args) ~= "table" then
    return nil, "Envelope args must be an object."
  end
  if envelope.options == nil then
    envelope.options = {}
  end
  if type(envelope.options) ~= "table" then
    return nil, "Envelope options must be an object."
  end
  if envelope.options.mutates_project == nil then
    envelope.options.mutates_project = false
  end
  if envelope.options.dry_run == nil then
    envelope.options.dry_run = false
  end
  if type(envelope.options.mutates_project) ~= "boolean" then
    return nil, "Envelope options.mutates_project must be a boolean."
  end
  if type(envelope.options.dry_run) ~= "boolean" then
    return nil, "Envelope options.dry_run must be a boolean."
  end
  if envelope.options.undo_label ~= nil and type(envelope.options.undo_label) ~= "string" then
    return nil, "Envelope options.undo_label must be a string when provided."
  end
  if envelope.options.idempotency_key ~= nil then
    if type(envelope.options.idempotency_key) ~= "string"
      or envelope.options.idempotency_key == "" then
      return nil, "Envelope options.idempotency_key must be a non-empty string."
    end
  end
  return envelope, nil
end

local COMMANDS = {}

local function command_classification()
  local result = {}
  for command, definition in pairs(COMMANDS) do
    result[command] = {
      mutates_project = definition.mutates_project,
    }
  end
  return result
end

local function supported_commands()
  local result = {}
  for command, _ in pairs(COMMANDS) do
    result[#result + 1] = command
  end
  table.sort(result)
  return result
end

COMMANDS.health_check = {
  mutates_project = false,
  handler = function()
    return {
      status = "ok",
      bridge_version = BRIDGE_VERSION,
      reaper_version = reaper_version(),
      bridge_dir = BRIDGE_DIR,
    }
  end,
}

COMMANDS.get_reaper_version = {
  mutates_project = false,
  handler = function()
    return {
      reaper_version = reaper_version(),
    }
  end,
}

COMMANDS.get_project_info = {
  mutates_project = false,
  handler = function()
    local project, path = current_project()
    local bpm, beats_per_measure = project_time_signature(project)
    return {
      project_path = path,
      project_name = project_name(project, path),
      track_count = safe_number_call(reaper.CountTracks, 0, project),
      state_change_count = safe_number_call(
        reaper.GetProjectStateChangeCount,
        0,
        project
      ),
      is_dirty = safe_number_call(reaper.IsProjectDirty, 0, project) ~= 0,
      tempo_bpm = bpm,
      beats_per_measure = beats_per_measure,
      play_state = safe_number_call(reaper.GetPlayState, 0),
    }
  end,
}

COMMANDS.get_bridge_status = {
  mutates_project = false,
  handler = function(envelope)
    local active_render_job = RENDER_RUNTIME and RENDER_RUNTIME.active_job() or nil
    return {
      status = "ok",
      bridge_version = BRIDGE_VERSION,
      bridge_dir = BRIDGE_DIR,
      requests_dir = REQUESTS_DIR,
      responses_dir = RESPONSES_DIR,
      jobs_dir = JOBS_DIR,
      heartbeat_path = HEARTBEAT_PATH,
      active_render_job_id = active_render_job and active_render_job.id or nil,
      active_render_status = active_render_job and active_render_job.status or "idle",
      pending_request_count = count_request_files(envelope.id),
      uptime_seconds = os.time() - START_TIME,
      supported_commands = supported_commands(),
      command_classification = command_classification(),
    }
  end,
}

local function track_snapshot(track)
  local guid = safe_string_call(reaper.GetTrackGUID, "", track)
  local _, name = reaper.GetTrackName(track, "")
  return {
    guid = guid,
    name = name or "",
    index = math.floor(
      safe_number_call(reaper.GetMediaTrackInfo_Value, 0, track, "IP_TRACKNUMBER")
    ),
    color = safe_number_call(reaper.GetTrackColor, 0, track),
    volume = safe_number_call(reaper.GetMediaTrackInfo_Value, 1, track, "D_VOL"),
    pan = safe_number_call(reaper.GetMediaTrackInfo_Value, 0, track, "D_PAN"),
    mute = safe_number_call(reaper.GetMediaTrackInfo_Value, 0, track, "B_MUTE") ~= 0,
    solo = safe_number_call(reaper.GetMediaTrackInfo_Value, 0, track, "I_SOLO") ~= 0,
    armed = safe_number_call(reaper.GetMediaTrackInfo_Value, 0, track, "I_RECARM") ~= 0,
    folder_depth = math.floor(safe_number_call(reaper.GetMediaTrackInfo_Value, 0, track, "I_FOLDERDEPTH")),
    recording_input = math.floor(safe_number_call(reaper.GetMediaTrackInfo_Value, 0, track, "I_RECINPUT")),
    input_monitoring = safe_number_call(reaper.GetMediaTrackInfo_Value, 0, track, "I_RECMON") ~= 0,
    selected = safe_bool_call(reaper.IsTrackSelected, false, track),
    media_item_count = safe_number_call(reaper.CountTrackMediaItems, 0, track),
  }
end

local function postcondition_values_match(actual, expected)
  if type(actual) == "number" and type(expected) == "number" then
    return math.abs(actual - expected) <= 0.000000001
  end
  return actual == expected
end

local function require_postconditions(subject, actual, expected)
  for field, expected_value in pairs(expected or {}) do
    if not postcondition_values_match(actual[field], expected_value) then
      error(
        "postcondition_failed: "
          .. subject
          .. " "
          .. field
          .. " did not match the requested value"
      )
    end
  end
end

local function track_expected_fields(change)
  return {
    name = change.name,
    color = change.color,
    mute = change.muted,
    solo = change.soloed,
    armed = change.armed,
    volume = change.volume,
    pan = change.pan,
    recording_input = change.recording_input,
    input_monitoring = change.input_monitoring,
    folder_depth = change.folder_depth,
  }
end

local function project_tracks(project)
  local tracks = {}
  local selected_track_guids = {}
  local track_count = safe_number_call(reaper.CountTracks, 0, project)
  for index = 0, track_count - 1 do
    local track = reaper.GetTrack(project, index)
    if track then
      local snapshot = track_snapshot(track)
      tracks[#tracks + 1] = snapshot
      if snapshot.selected and snapshot.guid ~= "" then
        selected_track_guids[#selected_track_guids + 1] = snapshot.guid
      end
    end
  end
  return tracks, selected_track_guids
end

local function find_track_by_guid(project, track_guid)
  local track_count = safe_number_call(reaper.CountTracks, 0, project)
  for index = 0, track_count - 1 do
    local track = reaper.GetTrack(project, index)
    if track and safe_string_call(reaper.GetTrackGUID, "", track) == track_guid then
      return track
    end
  end
  return nil
end

local function require_track_by_guid(project, track_guid)
  if type(track_guid) ~= "string" or track_guid == "" then
    error("invalid_track_reference: track_guid must be a non-empty string")
  end
  local track = find_track_by_guid(project, track_guid)
  if not track then
    error("invalid_track_reference: track_guid was not found")
  end
  return track
end

local function require_fx_track_by_guid(project, track_guid)
  if type(track_guid) ~= "string" or track_guid == "" then
    error("invalid_track_reference: track_guid must be a non-empty string")
  end
  local master_track = reaper.GetMasterTrack(project)
  if master_track
      and safe_string_call(reaper.GetTrackGUID, "", master_track) == track_guid then
    return master_track
  end
  return require_track_by_guid(project, track_guid)
end

local function track_mutation_result(project, track, expected)
  reaper.TrackList_AdjustWindows(false)
  reaper.UpdateArrange()
  local snapshot = track_snapshot(track)
  require_postconditions("track", snapshot, expected)
  return {
    track = snapshot,
    track_count = safe_number_call(reaper.CountTracks, 0, project),
    changes_applied = true,
  }
end

local function master_track_snapshot(project)
  local master_track = reaper.GetMasterTrack(project)
  if not master_track then
    error("reaper_not_available: REAPER did not return the master track")
  end
  return {
    guid = safe_string_call(reaper.GetTrackGUID, "", master_track),
    volume = safe_number_call(
      reaper.GetMediaTrackInfo_Value,
      1,
      master_track,
      "D_VOL"
    ),
    pan = safe_number_call(
      reaper.GetMediaTrackInfo_Value,
      0,
      master_track,
      "D_PAN"
    ),
    mute = safe_number_call(
      reaper.GetMediaTrackInfo_Value,
      0,
      master_track,
      "B_MUTE"
    ) ~= 0,
  }
end

local function master_track_mutation_result(project, expected)
  reaper.TrackList_AdjustWindows(false)
  reaper.UpdateArrange()
  local snapshot = master_track_snapshot(project)
  require_postconditions("master track", snapshot, expected)
  return {
    master_track = snapshot,
    changes_applied = true,
  }
end

local function track_send_snapshot(source_track, source_track_guid, send_index)
  local destination_track = reaper.GetTrackSendInfo_Value(
    source_track,
    0,
    send_index,
    "P_DESTTRACK"
  )
  if not destination_track or destination_track == 0 then
    error("invalid_send_reference: send destination track was not found")
  end
  local destination_track_guid = safe_string_call(
    reaper.GetTrackGUID,
    "",
    destination_track
  )
  local _, destination_track_name = reaper.GetTrackName(destination_track, "")
  return {
    identity = table.concat({
      source_track_guid,
      tostring(send_index),
      destination_track_guid,
    }, ":"),
    source_track_guid = source_track_guid,
    destination_track_guid = destination_track_guid,
    destination_track_name = destination_track_name or "",
    index = send_index,
    volume = safe_number_call(
      reaper.GetTrackSendInfo_Value,
      1,
      source_track,
      0,
      send_index,
      "D_VOL"
    ),
    pan = safe_number_call(
      reaper.GetTrackSendInfo_Value,
      0,
      source_track,
      0,
      send_index,
      "D_PAN"
    ),
    muted = safe_number_call(
      reaper.GetTrackSendInfo_Value,
      0,
      source_track,
      0,
      send_index,
      "B_MUTE"
    ) ~= 0,
  }
end

local function track_send_list(source_track, source_track_guid)
  local sends = {}
  local send_count = safe_number_call(reaper.GetTrackNumSends, 0, source_track, 0)
  for send_index = 0, send_count - 1 do
    sends[#sends + 1] = track_send_snapshot(
      source_track,
      source_track_guid,
      send_index
    )
  end
  return sends
end

local function require_track_send(project, identity)
  if type(identity) ~= "table" then
    error("invalid_send_reference: send_identity must be an object")
  end
  if type(identity.index) ~= "number" or identity.index < 0 then
    error("invalid_send_reference: send index must be >= 0")
  end
  local source_track = require_track_by_guid(project, identity.source_track_guid)
  local send_count = safe_number_call(reaper.GetTrackNumSends, 0, source_track, 0)
  if identity.index >= send_count then
    error("invalid_send_reference: send index was not found")
  end
  local send = track_send_snapshot(
    source_track,
    identity.source_track_guid,
    identity.index
  )
  if send.destination_track_guid ~= identity.expected_destination_track_guid then
    error("invalid_send_reference: send destination GUID did not match")
  end
  return source_track, send
end

local function hardware_output_snapshot(
  source_track,
  source_track_guid,
  send_index
)
  local destination_channel = math.floor(safe_number_call(
    reaper.GetTrackSendInfo_Value,
    0,
    source_track,
    1,
    send_index,
    "I_DSTCHAN"
  ))
  local output_pair = math.floor(destination_channel / 2) + 1
  local left_channel = (output_pair - 1) * 2 + 1
  return {
    identity = table.concat({
      source_track_guid,
      "hardware",
      tostring(send_index),
      tostring(destination_channel),
    }, ":"),
    source_track_guid = source_track_guid,
    index = send_index,
    hardware_output_pair = output_pair,
    destination_channels = table.concat({
      tostring(left_channel),
      tostring(left_channel + 1),
    }, "/"),
    volume = safe_number_call(
      reaper.GetTrackSendInfo_Value,
      1,
      source_track,
      1,
      send_index,
      "D_VOL"
    ),
    pan = safe_number_call(
      reaper.GetTrackSendInfo_Value,
      0,
      source_track,
      1,
      send_index,
      "D_PAN"
    ),
    muted = safe_number_call(
      reaper.GetTrackSendInfo_Value,
      0,
      source_track,
      1,
      send_index,
      "B_MUTE"
    ) ~= 0,
    send_mode = math.floor(safe_number_call(
      reaper.GetTrackSendInfo_Value,
      0,
      source_track,
      1,
      send_index,
      "I_SENDMODE"
    )),
  }
end

local function find_hardware_output_send(source_track, destination_channel)
  local send_count = safe_number_call(
    reaper.GetTrackNumSends,
    0,
    source_track,
    1
  )
  local matching_index = nil
  for send_index = 0, send_count - 1 do
    local current_channel = math.floor(safe_number_call(
      reaper.GetTrackSendInfo_Value,
      -1,
      source_track,
      1,
      send_index,
      "I_DSTCHAN"
    ))
    if current_channel == destination_channel then
      if matching_index ~= nil then
        error(
          "invalid_send_reference: duplicate direct hardware sends target the requested output pair"
        )
      end
      matching_index = send_index
    end
  end
  return matching_index
end

local function track_fx_named_config(track, fx_index, key)
  if not reaper.TrackFX_GetNamedConfigParm then
    return nil
  end
  local ok, value = reaper.TrackFX_GetNamedConfigParm(
    track,
    fx_index,
    key
  )
  if not ok or value == nil or value == "" then
    return nil
  end
  return value
end

local function track_fx_snapshot(track, track_guid_value, fx_index)
  local _, name = reaper.TrackFX_GetFXName(track, fx_index, "")
  local guid = nil
  if reaper.TrackFX_GetFXGUID then
    guid = reaper.TrackFX_GetFXGUID(track, fx_index)
    if guid == "" then
      guid = nil
    end
  end
  local normalized_name = (name and name ~= "" and name) or ("FX " .. tostring(fx_index + 1))
  local identity = table.concat({
    track_guid_value,
    tostring(fx_index),
    guid or normalized_name,
  }, ":")
  return {
    identity = identity,
    track_guid = track_guid_value,
    index = fx_index,
    name = normalized_name,
    enabled = reaper.TrackFX_GetEnabled(track, fx_index),
    offline = reaper.TrackFX_GetOffline(track, fx_index),
    guid = guid,
    identifier = track_fx_named_config(track, fx_index, "fx_ident"),
    latency_samples = tonumber(
      track_fx_named_config(track, fx_index, "pdc")
    ),
    gain_reduction_db = tonumber(
      track_fx_named_config(track, fx_index, "GainReduction_dB")
    ),
  }
end

local function track_fx_list(track, track_guid_value)
  local fx = {}
  local fx_count = safe_number_call(reaper.TrackFX_GetCount, 0, track)
  for fx_index = 0, fx_count - 1 do
    fx[#fx + 1] = track_fx_snapshot(track, track_guid_value, fx_index)
  end
  return fx
end

local function available_fx_list()
  local fx = {}
  if not reaper.EnumInstalledFX then
    return fx
  end
  local index = 0
  while true do
    local ok, name, identifier = reaper.EnumInstalledFX(index)
    if not ok then
      break
    end
    local normalized_name = (name and name ~= "" and name) or ("FX " .. tostring(index + 1))
    local normalized_identifier = (identifier and identifier ~= "" and identifier) or normalized_name
    fx[#fx + 1] = {
      index = index,
      name = normalized_name,
      identifier = normalized_identifier,
    }
    index = index + 1
  end
  return fx
end

local function installed_fx_matches(identifier)
  local fx = available_fx_list()
  if #fx == 0 then
    return true
  end
  for _, available_fx in ipairs(fx) do
    if available_fx.identifier == identifier or available_fx.name == identifier then
      return true
    end
  end
  return false
end

local function require_fx_identity(project, identity)
  if type(identity) ~= "table" then
    error("invalid_fx_reference: fx_identity must be an object")
  end
  if type(identity.track_guid) ~= "string" or identity.track_guid == "" then
    error("invalid_fx_reference: track_guid must be a non-empty string")
  end
  if type(identity.index) ~= "number" or identity.index < 0 then
    error("invalid_fx_reference: FX index must be >= 0")
  end
  if type(identity.expected_identity) ~= "string" or identity.expected_identity == "" then
    error("invalid_fx_reference: expected_identity must be a non-empty string")
  end
  if type(identity.expected_name) ~= "string" or identity.expected_name == "" then
    error("invalid_fx_reference: expected_name must be a non-empty string")
  end
  if identity.expected_guid ~= nil and type(identity.expected_guid) ~= "string" then
    error("invalid_fx_reference: expected_guid must be a string when provided")
  end

  local track = require_fx_track_by_guid(project, identity.track_guid)
  local fx_count = safe_number_call(reaper.TrackFX_GetCount, 0, track)
  if identity.index >= fx_count then
    error("fx_not_found: FX index was not found")
  end

  local fx = track_fx_snapshot(track, identity.track_guid, identity.index)
  if fx.identity ~= identity.expected_identity then
    error("invalid_fx_reference: FX identity did not match")
  end
  if fx.name ~= identity.expected_name then
    error("invalid_fx_reference: FX name did not match")
  end
  if identity.expected_guid ~= nil and fx.guid ~= identity.expected_guid then
    error("invalid_fx_reference: FX GUID did not match")
  end

  return track, fx
end

local function fx_parameter_snapshot(track, fx_index, parameter_index)
  local parameter_count = safe_number_call(reaper.TrackFX_GetNumParams, 0, track, fx_index)
  if parameter_index < 0 or parameter_index >= parameter_count then
    return nil
  end

  local _, name = reaper.TrackFX_GetParamName(track, fx_index, parameter_index)
  local _, formatted_value = reaper.TrackFX_GetFormattedParamValue(track, fx_index, parameter_index)
  local minimum_value = nil
  local maximum_value = nil
  local midpoint_value = nil
  if reaper.TrackFX_GetParamEx then
    local _, minimum, maximum, midpoint = reaper.TrackFX_GetParamEx(
      track,
      fx_index,
      parameter_index
    )
    minimum_value = minimum
    maximum_value = maximum
    midpoint_value = midpoint
  end
  local normalized_name = (name and name ~= "") and name or ("Parameter " .. tostring(parameter_index + 1))
  return {
    index = parameter_index,
    name = normalized_name,
    normalized_value = reaper.TrackFX_GetParamNormalized(track, fx_index, parameter_index),
    formatted_value = formatted_value or "",
    minimum_value = minimum_value,
    maximum_value = maximum_value,
    midpoint_value = midpoint_value,
  }
end

local function fx_parameter_list(track, fx_index)
  local parameters = {}
  local parameter_count = safe_number_call(reaper.TrackFX_GetNumParams, 0, track, fx_index)
  for parameter_index = 0, parameter_count - 1 do
    local parameter = fx_parameter_snapshot(track, fx_index, parameter_index)
    if parameter then
      parameters[#parameters + 1] = parameter
    end
  end
  return parameters
end

local function require_fx_parameter(track, fx_index, parameter_index)
  if type(parameter_index) ~= "number" or parameter_index < 0 then
    error("invalid_fx_parameter: parameter_index must be >= 0")
  end

  local parameter = fx_parameter_snapshot(track, fx_index, parameter_index)
  if not parameter then
    error("fx_parameter_not_found: FX parameter index was not found")
  end
  return parameter
end

local function require_normalized_fx_parameter_value(normalized_value)
  if type(normalized_value) ~= "number" or normalized_value < 0.0 or normalized_value > 1.0 then
    error("invalid_fx_parameter: normalized_value must be between 0.0 and 1.0")
  end
end

local function take_guid(take)
  return safe_string_call(reaper.GetSetMediaItemTakeInfo_String, "", take, "GUID", "", false)
end

local function item_guid(item)
  return safe_string_call(reaper.GetSetMediaItemInfo_String, "", item, "GUID", "", false)
end

local function active_take_snapshot(take)
  if not take then
    return nil
  end
  local _, name = reaper.GetSetMediaItemTakeInfo_String(take, "P_NAME", "", false)
  return {
    guid = take_guid(take),
    name = name or "",
    is_midi = reaper.TakeIsMIDI(take),
  }
end

local function media_item_snapshot(project, item)
  local track = reaper.GetMediaItemTrack(item)
  local track_guid = track and safe_string_call(reaper.GetTrackGUID, "", track) or ""
  local position = safe_number_call(reaper.GetMediaItemInfo_Value, 0, item, "D_POSITION")
  local length = safe_number_call(reaper.GetMediaItemInfo_Value, 0, item, "D_LENGTH")
  local take = reaper.GetActiveTake(item)
  return {
    guid = item_guid(item),
    track_guid = track_guid,
    name = take and active_take_snapshot(take).name or "",
    position_seconds = position,
    length_seconds = length,
    start_qn = reaper.TimeMap2_timeToQN(project, position),
    end_qn = reaper.TimeMap2_timeToQN(project, position + length),
    selected = safe_number_call(reaper.GetMediaItemInfo_Value, 0, item, "B_UISEL") ~= 0,
    muted = safe_number_call(reaper.GetMediaItemInfo_Value, 0, item, "B_MUTE") ~= 0,
    gain = safe_number_call(reaper.GetMediaItemInfo_Value, 1, item, "D_VOL"),
    fade_in_seconds = safe_number_call(reaper.GetMediaItemInfo_Value, 0, item, "D_FADEINLEN"),
    fade_out_seconds = safe_number_call(reaper.GetMediaItemInfo_Value, 0, item, "D_FADEOUTLEN"),
    take_count = safe_number_call(reaper.CountTakes, 0, item),
    active_take = active_take_snapshot(take),
  }
end

local function project_media_items(project)
  local items = {}
  local item_count = safe_number_call(reaper.CountMediaItems, 0, project)
  for index = 0, item_count - 1 do
    local item = reaper.GetMediaItem(project, index)
    if item then
      items[#items + 1] = media_item_snapshot(project, item)
    end
  end
  return items
end

local function find_media_item_by_guid(project, requested_item_guid)
  local item_count = safe_number_call(reaper.CountMediaItems, 0, project)
  for item_index = 0, item_count - 1 do
    local item = reaper.GetMediaItem(project, item_index)
    if item and item_guid(item) == requested_item_guid then
      return item
    end
  end
  return nil
end

local function require_media_item_by_guid(project, requested_item_guid)
  if type(requested_item_guid) ~= "string" or requested_item_guid == "" then
    error("invalid_media_item_request: item_guid must be a non-empty string")
  end
  local item = find_media_item_by_guid(project, requested_item_guid)
  if not item then
    error("invalid_media_item_request: item_guid was not found")
  end
  return item
end

local function media_item_mutation_result(project, item)
  reaper.UpdateItemInProject(item)
  reaper.UpdateArrange()
  return {
    item = media_item_snapshot(project, item),
    changes_applied = true,
  }
end

local function find_take_by_guid(project, requested_take_guid)
  local item_count = safe_number_call(reaper.CountMediaItems, 0, project)
  for item_index = 0, item_count - 1 do
    local item = reaper.GetMediaItem(project, item_index)
    if item then
      local take_count = safe_number_call(reaper.CountTakes, 0, item)
      for take_index = 0, take_count - 1 do
        local take = reaper.GetTake(item, take_index)
        if take and take_guid(take) == requested_take_guid then
          return take, item, take_index
        end
      end
    end
  end
  return nil
end

local function require_take_by_guid(project, requested_take_guid)
  if type(requested_take_guid) ~= "string" or requested_take_guid == "" then
    error("invalid_take_reference: take_guid must be a non-empty string")
  end
  local take, item, take_index = find_take_by_guid(project, requested_take_guid)
  if not take then
    error("invalid_take_reference: take_guid was not found")
  end
  return take, item, take_index
end

local function take_fx_snapshot(take, take_guid_value, fx_index)
  local _, name = reaper.TakeFX_GetFXName(take, fx_index, "")
  local guid = nil
  if reaper.TakeFX_GetFXGUID then
    guid = reaper.TakeFX_GetFXGUID(take, fx_index)
    if guid == "" then
      guid = nil
    end
  end
  local normalized_name = (name and name ~= "" and name) or ("FX " .. tostring(fx_index + 1))
  return {
    identity = table.concat({ take_guid_value, tostring(fx_index), guid or normalized_name }, ":"),
    take_guid = take_guid_value,
    index = fx_index,
    name = normalized_name,
    enabled = reaper.TakeFX_GetEnabled(take, fx_index),
    offline = reaper.TakeFX_GetOffline(take, fx_index),
    guid = guid,
  }
end

local function take_fx_list(take, take_guid_value)
  local fx = {}
  local fx_count = safe_number_call(reaper.TakeFX_GetCount, 0, take)
  for fx_index = 0, fx_count - 1 do
    fx[#fx + 1] = take_fx_snapshot(take, take_guid_value, fx_index)
  end
  return fx
end

local function require_take_fx_identity(project, identity)
  if type(identity) ~= "table" then
    error("invalid_fx_reference: take fx_identity must be an object")
  end
  if type(identity.take_guid) ~= "string" or identity.take_guid == "" then
    error("invalid_fx_reference: take_guid must be a non-empty string")
  end
  if type(identity.index) ~= "number" or identity.index < 0 then
    error("invalid_fx_reference: take FX index must be >= 0")
  end
  if type(identity.expected_name) ~= "string" or identity.expected_name == "" then
    error("invalid_fx_reference: expected_name must be a non-empty string")
  end
  local take = require_take_by_guid(project, identity.take_guid)
  local fx_count = safe_number_call(reaper.TakeFX_GetCount, 0, take)
  if identity.index >= fx_count then
    error("fx_not_found: take FX index was not found")
  end
  local fx = take_fx_snapshot(take, identity.take_guid, identity.index)
  if fx.name ~= identity.expected_name then
    error("invalid_fx_reference: take FX name did not match")
  end
  if identity.expected_guid ~= nil and fx.guid ~= identity.expected_guid then
    error("invalid_fx_reference: take FX GUID did not match")
  end
  return take, fx
end

local function require_midi_take_by_guid(project, requested_take_guid)
  local take = require_take_by_guid(project, requested_take_guid)
  if not reaper.TakeIsMIDI(take) then
    error("invalid_take_reference: take is not MIDI")
  end
  return take
end

local function position_to_qn(position, beats_per_measure)
  return ((position.measure - 1) * beats_per_measure) + (position.beat - 1)
end

local function validate_musical_position(position)
  if type(position) ~= "table" then
    error("invalid_time_position: start must be an object")
  end
  if type(position.measure) ~= "number" or position.measure < 1 then
    error("invalid_time_position: start.measure must be >= 1")
  end
  if type(position.beat) ~= "number" or position.beat < 1 then
    error("invalid_time_position: start.beat must be >= 1")
  end
end

local function musical_position(project, start)
  local _, beats_per_measure = project_time_signature(project)
  local start_qn = position_to_qn(start, beats_per_measure)
  return {
    start = start,
    start_qn = start_qn,
    start_seconds = reaper.TimeMap2_QNToTime(project, start_qn),
  }
end

local function media_item_position(project, item, start)
  local position = safe_number_call(reaper.GetMediaItemInfo_Value, 0, item, "D_POSITION")
  local length = safe_number_call(reaper.GetMediaItemInfo_Value, 0, item, "D_LENGTH")
  local start_qn = reaper.TimeMap2_timeToQN(project, position)
  local end_qn = reaper.TimeMap2_timeToQN(project, position + length)
  return {
    start = start,
    length = { beats = end_qn - start_qn },
    start_qn = start_qn,
    end_qn = end_qn,
    start_seconds = position,
    end_seconds = position + length,
  }
end

local function musical_range(project, start, length)
  local _, beats_per_measure = project_time_signature(project)
  local start_qn = position_to_qn(start, beats_per_measure)
  local end_qn = start_qn + length.beats
  return {
    start = start,
    length = length,
    start_qn = start_qn,
    end_qn = end_qn,
    start_seconds = reaper.TimeMap2_QNToTime(project, start_qn),
    end_seconds = reaper.TimeMap2_QNToTime(project, end_qn),
  }
end

local function validate_musical_range(args)
  validate_musical_position(args.start)
  if type(args.length) ~= "table" then
    error("invalid_time_position: length must be an object")
  end
  if type(args.length.beats) ~= "number" or args.length.beats <= 0 then
    error("invalid_time_position: length.beats must be > 0")
  end
end

local function validate_audio_source_path(source_path)
  if type(source_path) ~= "string" or source_path == "" then
    error("invalid_media_item_request: source_path must be a non-empty string")
  end
  local file = io.open(source_path, "rb")
  if not file then
    error("invalid_media_item_request: source_path was not found")
  end
  file:close()
end

local function snapshot_selected_tracks(project)
  local selected_tracks = {}
  local track_count = safe_number_call(reaper.CountTracks, 0, project)
  for index = 0, track_count - 1 do
    local track = reaper.GetTrack(project, index)
    if track and safe_number_call(reaper.GetMediaTrackInfo_Value, 0, track, "I_SELECTED") ~= 0 then
      selected_tracks[#selected_tracks + 1] = track
    end
  end
  return selected_tracks
end

local function restore_selected_tracks(project, selected_tracks)
  local track_count = safe_number_call(reaper.CountTracks, 0, project)
  for index = 0, track_count - 1 do
    local track = reaper.GetTrack(project, index)
    if track then
      reaper.SetTrackSelected(track, false)
    end
  end
  for _, track in ipairs(selected_tracks) do
    reaper.SetTrackSelected(track, true)
  end
end

local function snapshot_selected_media_items(project)
  local selected_items = {}
  local item_count = safe_number_call(reaper.CountMediaItems, 0, project)
  for index = 0, item_count - 1 do
    local item = reaper.GetMediaItem(project, index)
    if item and safe_number_call(reaper.GetMediaItemInfo_Value, 0, item, "B_UISEL") ~= 0 then
      selected_items[#selected_items + 1] = item
    end
  end
  return selected_items
end

local function restore_selected_media_items(project, selected_items)
  reaper.SelectAllMediaItems(project, false)
  for _, item in ipairs(selected_items) do
    reaper.SetMediaItemSelected(item, true)
  end
end

local function media_item_selection_matches(project, selected_items)
  local expected = {}
  for _, item in ipairs(selected_items) do
    expected[item] = true
  end
  local item_count = safe_number_call(reaper.CountMediaItems, 0, project)
  for index = 0, item_count - 1 do
    local item = reaper.GetMediaItem(project, index)
    if item then
      local selected = safe_number_call(
        reaper.GetMediaItemInfo_Value,
        0,
        item,
        "B_UISEL"
      ) ~= 0
      if selected ~= (expected[item] == true) then
        return false
      end
    end
  end
  return true
end

local function track_selection_matches(project, selected_tracks)
  local expected = {}
  for _, track in ipairs(selected_tracks) do
    expected[track] = true
  end
  local track_count = safe_number_call(reaper.CountTracks, 0, project)
  for index = 0, track_count - 1 do
    local track = reaper.GetTrack(project, index)
    if track then
      local selected = safe_number_call(
        reaper.GetMediaTrackInfo_Value,
        0,
        track,
        "I_SELECTED"
      ) ~= 0
      if selected ~= (expected[track] == true) then
        return false
      end
    end
  end
  return true
end

local function track_freeze_state(project, track)
  local freeze_count = math.floor(safe_number_call(
    reaper.GetMediaTrackInfo_Value,
    0,
    track,
    "I_FREEZECOUNT"
  ))
  return {
    track_guid = safe_string_call(reaper.GetTrackGUID, "", track),
    frozen = freeze_count > 0,
    freeze_count = freeze_count,
    track = track_snapshot(track),
  }
end

local function find_inserted_media_item(project, before_count, track, start_seconds)
  local after_count = safe_number_call(reaper.CountMediaItems, 0, project)
  for index = before_count, after_count - 1 do
    local item = reaper.GetMediaItem(project, index)
    if item then
      return item
    end
  end
  for index = 0, after_count - 1 do
    local item = reaper.GetMediaItem(project, index)
    if item then
      local item_track = reaper.GetMediaItemTrack(item)
      local position = safe_number_call(reaper.GetMediaItemInfo_Value, 0, item, "D_POSITION")
      if item_track == track and math.abs(position - start_seconds) < 0.001 then
        return item
      end
    end
  end
  return nil
end

local function validate_midi_note(note)
  validate_musical_range(note)
  if type(note.pitch) ~= "number" or note.pitch < 0 or note.pitch > 127 then
    error("invalid_midi_note_request: pitch must be between 0 and 127")
  end
  if type(note.velocity) ~= "number" or note.velocity < 1 or note.velocity > 127 then
    error("invalid_midi_note_request: velocity must be between 1 and 127")
  end
  if type(note.channel) ~= "number" or note.channel < 0 or note.channel > 15 then
    error("invalid_midi_note_request: channel must be between 0 and 15")
  end
end

local function midi_note_fingerprint(selected, muted, start_ppq, end_ppq, channel, pitch, velocity)
  return table.concat({
    tostring(selected and 1 or 0),
    tostring(muted and 1 or 0),
    tostring(math.floor(start_ppq + 0.5)),
    tostring(math.floor(end_ppq + 0.5)),
    tostring(channel),
    tostring(pitch),
    tostring(velocity),
  }, ":")
end

local function midi_note_snapshot(project, take, index)
  local ok, selected, muted, start_ppq, end_ppq, channel, pitch, velocity =
    reaper.MIDI_GetNote(take, index)
  if not ok then
    return nil
  end
  local start_qn = reaper.MIDI_GetProjQNFromPPQPos(take, start_ppq)
  local end_qn = reaper.MIDI_GetProjQNFromPPQPos(take, end_ppq)
  return {
    index = index,
    fingerprint = midi_note_fingerprint(
      selected,
      muted,
      start_ppq,
      end_ppq,
      channel,
      pitch,
      velocity
    ),
    selected = selected,
    muted = muted,
    start_ppq = start_ppq,
    end_ppq = end_ppq,
    start_qn = start_qn,
    end_qn = end_qn,
    channel = channel,
    pitch = pitch,
    velocity = velocity,
  }
end

local function midi_notes(project, take)
  local notes = {}
  local _, note_count = reaper.MIDI_CountEvts(take)
  for index = 0, (note_count or 0) - 1 do
    local note = midi_note_snapshot(project, take, index)
    if note then
      notes[#notes + 1] = note
    end
  end
  return notes
end

local MIDI_CONTROLLER = {
  event_types = {
    [176] = "cc",
    [192] = "program_change",
    [208] = "channel_pressure",
    [224] = "pitch_bend",
  },
}

function MIDI_CONTROLLER.event_fingerprint(
  selected,
  muted,
  position_ppq,
  chanmsg,
  channel,
  msg2,
  msg3
)
  return table.concat({
    tostring(selected and 1 or 0),
    tostring(muted and 1 or 0),
    tostring(math.floor(position_ppq + 0.5)),
    tostring(chanmsg),
    tostring(channel),
    tostring(msg2),
    tostring(msg3),
  }, ":")
end

function MIDI_CONTROLLER.event_snapshot(project, take, index)
  local ok, selected, muted, position_ppq, chanmsg, channel, msg2, msg3 =
    reaper.MIDI_GetCC(take, index)
  if not ok or not MIDI_CONTROLLER.event_types[chanmsg] then
    return nil
  end
  local event_type = MIDI_CONTROLLER.event_types[chanmsg]
  local value = msg3
  local controller = nil
  if event_type == "cc" then
    controller = msg2
  elseif event_type == "pitch_bend" then
    value = msg2 + (msg3 * 128)
  else
    value = msg2
  end
  return {
    index = index,
    fingerprint = MIDI_CONTROLLER.event_fingerprint(
      selected,
      muted,
      position_ppq,
      chanmsg,
      channel,
      msg2,
      msg3
    ),
    position_ppq = position_ppq,
    position_qn = reaper.MIDI_GetProjQNFromPPQPos(take, position_ppq),
    event_type = event_type,
    controller = controller,
    value = value,
    channel = channel,
    selected = selected,
    muted = muted,
  }
end

function MIDI_CONTROLLER.events(project, take)
  local events = {}
  local _, _, cc_count = reaper.MIDI_CountEvts(take)
  for index = 0, (cc_count or 0) - 1 do
    local event = MIDI_CONTROLLER.event_snapshot(project, take, index)
    if event then
      events[#events + 1] = event
    end
  end
  return events
end

function MIDI_CONTROLLER.validate_event(event)
  if type(event) ~= "table" or type(event.position) ~= "table" then
    error("invalid_midi_controller_request: position must be a musical position")
  end
  validate_musical_position(event.position)
  local event_type = event.event_type or "cc"
  if not MIDI_CONTROLLER.event_types[176] then
    error("invalid_midi_controller_request: controller event map is unavailable")
  end
  if event_type ~= "cc" and event_type ~= "pitch_bend"
      and event_type ~= "channel_pressure" and event_type ~= "program_change" then
    error("invalid_midi_controller_request: unsupported event_type")
  end
  if type(event.channel) ~= "number" or event.channel < 0 or event.channel > 15 then
    error("invalid_midi_controller_request: channel must be between 0 and 15")
  end
  if type(event.value) ~= "number" or event.value < 0 or event.value > 16383 then
    error("invalid_midi_controller_request: value must be between 0 and 16383")
  end
  if event_type == "cc" then
    if type(event.controller) ~= "number" or event.controller < 0 or event.controller > 127 then
      error("invalid_midi_controller_request: controller must be between 0 and 127")
    end
    if event.value > 127 then
      error("invalid_midi_controller_request: cc value must be between 0 and 127")
    end
  elseif event_type ~= "pitch_bend" and event.value > 127 then
    error("invalid_midi_controller_request: event value must be between 0 and 127")
  elseif event.controller ~= nil then
    error("invalid_midi_controller_request: controller is only valid for cc events")
  end
end

function MIDI_CONTROLLER.event_spec(event)
  local event_type = event.event_type or "cc"
  if event_type == "cc" then
    return 176, event.controller, event.value
  elseif event_type == "pitch_bend" then
    return 224, event.value % 128, math.floor(event.value / 128)
  elseif event_type == "channel_pressure" then
    return 208, event.value, 0
  end
  return 192, event.value, 0
end

function MIDI_CONTROLLER.event_key(event, position_ppq)
  local chanmsg, msg2, msg3 = MIDI_CONTROLLER.event_spec(event)
  return table.concat({
    tostring(math.floor(position_ppq + 0.5)),
    tostring(chanmsg),
    tostring(event.channel or 0),
    tostring(msg2),
    tostring(msg3),
  }, ":")
end

function MIDI_CONTROLLER.snapshot_key(event)
  local chanmsg = ({
    cc = 176,
    pitch_bend = 224,
    channel_pressure = 208,
    program_change = 192,
  })[event.event_type]
  local msg2 = event.controller or event.value
  local msg3 = 0
  if event.event_type == "cc" then
    msg3 = event.value
  elseif event.event_type == "pitch_bend" then
    msg2 = event.value % 128
    msg3 = math.floor(event.value / 128)
  end
  return table.concat({
    tostring(math.floor(event.position_ppq + 0.5)),
    tostring(chanmsg),
    tostring(event.channel),
    tostring(msg2),
    tostring(msg3),
  }, ":")
end

function MIDI_CONTROLLER.require_distinct_insertions(project, take, requested_events)
  local keys = {}
  for _, event in ipairs(MIDI_CONTROLLER.events(project, take)) do
    keys[MIDI_CONTROLLER.snapshot_key(event)] = true
  end
  for _, event in ipairs(requested_events) do
    local position_qn = musical_position(project, event.position).start_qn
    local position_ppq = reaper.MIDI_GetPPQPosFromProjQN(take, position_qn)
    local key = MIDI_CONTROLLER.event_key(event, position_ppq)
    if keys[key] then
      error("invalid_midi_controller_request: duplicate controller event identity")
    end
    keys[key] = true
  end
end

function MIDI_CONTROLLER.require_identity(take, identity)
  if type(identity) ~= "table" or type(identity.index) ~= "number"
      or type(identity.expected_fingerprint) ~= "string" then
    error("invalid_midi_controller_request: invalid event identity")
  end
  local event = MIDI_CONTROLLER.event_snapshot(current_project(), take, identity.index)
  if not event then
    error("midi_controller_conflict: controller event was not found")
  end
  if event.fingerprint ~= identity.expected_fingerprint then
    error("midi_controller_conflict: controller event fingerprint changed")
  end
  return event
end

function MIDI_CONTROLLER.result(project, take, take_guid)
  local events = MIDI_CONTROLLER.events(project, take)
  return {
    take_guid = take_guid,
    events = events,
    event_count = #events,
  }
end

local function midi_note_insertion_key(selected, muted, start_ppq, channel, pitch, velocity)
  return table.concat({
    tostring(selected and 1 or 0),
    tostring(muted and 1 or 0),
    tostring(math.floor(start_ppq + 0.5)),
    tostring(channel),
    tostring(pitch),
    tostring(velocity),
  }, ":")
end

local function requested_midi_note_insertion_key(project, take, note)
  local resolved = musical_range(project, note.start, note.length)
  local start_ppq = reaper.MIDI_GetPPQPosFromProjQN(take, resolved.start_qn)
  return midi_note_insertion_key(
    note.selected or false,
    note.muted or false,
    start_ppq,
    note.channel or 0,
    note.pitch,
    note.velocity or 96
  )
end

local function midi_note_snapshot_insertion_key(note)
  return midi_note_insertion_key(
    note.selected,
    note.muted,
    note.start_ppq,
    note.channel,
    note.pitch,
    note.velocity
  )
end

local function require_distinct_midi_note_insertions(project, take, requested_notes)
  local insertion_keys = {}
  for _, note in ipairs(midi_notes(project, take)) do
    insertion_keys[midi_note_snapshot_insertion_key(note)] = true
  end
  for _, note in ipairs(requested_notes) do
    local insertion_key = requested_midi_note_insertion_key(project, take, note)
    if insertion_keys[insertion_key] then
      error(
        "invalid_midi_note_request: MIDI notes with the same start, channel, pitch, and velocity are not supported because their identities are ambiguous"
      )
    end
    insertion_keys[insertion_key] = true
  end
end

local function find_requested_midi_notes(project, take, requested_notes, notes)
  local available = {}
  for _, note in ipairs(notes) do
    local insertion_key = midi_note_snapshot_insertion_key(note)
    local matching = available[insertion_key] or {}
    matching[#matching + 1] = note
    available[insertion_key] = matching
  end

  local inserted_notes = {}
  for _, requested_note in ipairs(requested_notes) do
    local insertion_key = requested_midi_note_insertion_key(project, take, requested_note)
    local matching = available[insertion_key]
    if not matching or #matching == 0 then
      error("midi_insert_failed: REAPER did not return the requested MIDI note")
    end
    inserted_notes[#inserted_notes + 1] = table.remove(matching, 1)
  end
  return inserted_notes
end

local function require_midi_note_identity(take, identity)
  if type(identity) ~= "table" then
    error("midi_note_conflict: note_identity must be an object")
  end
  if type(identity.index) ~= "number" or identity.index < 0 then
    error("midi_note_conflict: note index must be >= 0")
  end
  if type(identity.expected_fingerprint) ~= "string" or identity.expected_fingerprint == "" then
    error("midi_note_conflict: expected_fingerprint must be a non-empty string")
  end
  local note = midi_note_snapshot(current_project(), take, identity.index)
  if not note then
    error("midi_note_conflict: note index was not found")
  end
  if note.fingerprint ~= identity.expected_fingerprint then
    error("midi_note_conflict: note fingerprint did not match")
  end
  return note
end

local function validate_midi_note_identities(take, identities)
  if type(identities) ~= "table" or #identities == 0 then
    error("invalid_midi_note_request: notes must be a non-empty array")
  end
  local seen_indexes = {}
  for _, identity in ipairs(identities) do
    require_midi_note_identity(take, identity)
    if seen_indexes[identity.index] then
      error("invalid_midi_note_request: notes must not contain duplicate indexes")
    end
    seen_indexes[identity.index] = true
  end
end

local function transport_state()
  local play_state = safe_number_call(reaper.GetPlayState, 0)
  return {
    play_state = play_state,
    playing = (play_state & 1) ~= 0,
    paused = (play_state & 2) ~= 0,
    recording = (play_state & 4) ~= 0,
  }
end

local function transport_result(action)
  return {
    action = action,
    transport = transport_state(),
    may_create_media_items = action == "record" or action == "stop_recording",
  }
end

local function armed_track_count(project)
  local count = 0
  local track_count = safe_number_call(reaper.CountTracks, 0, project)
  for index = 0, track_count - 1 do
    local track = reaper.GetTrack(project, index)
    if track and safe_number_call(reaper.GetMediaTrackInfo_Value, 0, track, "I_RECARM") ~= 0 then
      count = count + 1
    end
  end
  return count
end

local function project_markers_and_regions(project)
  local markers = {}
  local regions = {}
  local _, marker_count, region_count = reaper.CountProjectMarkers(project)
  local total_count = (marker_count or 0) + (region_count or 0)
  for index = 0, total_count - 1 do
    local ok, is_region, position, region_end, name, marker_id, color =
      reaper.EnumProjectMarkers3(project, index)
    if ok then
      local marker = {
        id = marker_id,
        name = name or "",
        start_seconds = position or 0,
        color = color or 0,
      }
      if is_region then
        marker.end_seconds = region_end or 0
        regions[#regions + 1] = marker
      else
        markers[#markers + 1] = marker
      end
    end
  end
  return markers, regions
end

local function require_non_negative_seconds(value, field_name, error_code)
  if type(value) ~= "number" or value < 0 then
    error(error_code .. ": " .. field_name .. " must be >= 0")
  end
end

local function positions_match(expected, actual)
  return math.abs(expected - actual) <= 0.000001
end

local function find_marker_or_region(project, marker_id, is_region)
  local _, marker_count, region_count = reaper.CountProjectMarkers(project)
  local total_count = (marker_count or 0) + (region_count or 0)
  for index = 0, total_count - 1 do
    local ok, found_is_region, position, region_end, name, found_id, color =
      reaper.EnumProjectMarkers3(project, index)
    if ok and found_is_region == is_region and found_id == marker_id then
      return {
        index = index,
        id = found_id,
        name = name or "",
        start_seconds = position or 0,
        end_seconds = region_end or 0,
        color = color or 0,
      }
    end
  end
  return nil
end

local function require_marker_identity(project, identity)
  if type(identity) ~= "table" then
    error("invalid_marker_reference: marker_identity must be an object")
  end
  if type(identity.id) ~= "number" or identity.id < 0 then
    error("invalid_marker_reference: marker ID must be >= 0")
  end

  local marker = find_marker_or_region(project, identity.id, false)
  if not marker then
    error("marker_not_found: marker ID was not found")
  end
  if identity.expected_name ~= nil and marker.name ~= identity.expected_name then
    error("invalid_marker_reference: marker name did not match")
  end
  if identity.expected_start_seconds ~= nil and not positions_match(identity.expected_start_seconds, marker.start_seconds) then
    error("invalid_marker_reference: marker start_seconds did not match")
  end
  return marker
end

local function require_region_identity(project, identity)
  if type(identity) ~= "table" then
    error("invalid_region_reference: region_identity must be an object")
  end
  if type(identity.id) ~= "number" or identity.id < 0 then
    error("invalid_region_reference: region ID must be >= 0")
  end

  local region = find_marker_or_region(project, identity.id, true)
  if not region then
    error("region_not_found: region ID was not found")
  end
  if identity.expected_name ~= nil and region.name ~= identity.expected_name then
    error("invalid_region_reference: region name did not match")
  end
  if identity.expected_start_seconds ~= nil and not positions_match(identity.expected_start_seconds, region.start_seconds) then
    error("invalid_region_reference: region start_seconds did not match")
  end
  if identity.expected_end_seconds ~= nil and not positions_match(identity.expected_end_seconds, region.end_seconds) then
    error("invalid_region_reference: region end_seconds did not match")
  end
  return region
end

local function marker_payload(marker)
  return {
    id = marker.id,
    name = marker.name,
    start_seconds = marker.start_seconds,
    color = marker.color,
  }
end

local function region_payload(region)
  return {
    id = region.id,
    name = region.name,
    start_seconds = region.start_seconds,
    end_seconds = region.end_seconds,
    color = region.color,
  }
end

local function tempo_state(project)
  local numerator, denominator, bpm = reaper.TimeMap_GetTimeSigAtTime(project, 0)
  return {
    tempo = {
      bpm = bpm,
    },
    time_signature = {
      numerator = numerator,
      denominator = denominator,
    },
  }
end

local function tempo_marker_index_at_project_start(project)
  local count = safe_number_call(reaper.CountTempoTimeSigMarkers, 0, project)
  for index = 0, count - 1 do
    local ok, time_position = reaper.GetTempoTimeSigMarker(project, index)
    if ok and positions_match(time_position, 0) then
      return index
    end
  end
  return -1
end

local function is_supported_time_signature_denominator(denominator)
  return denominator == 1
    or denominator == 2
    or denominator == 4
    or denominator == 8
    or denominator == 16
    or denominator == 32
    or denominator == 64
end

load_bridge_module("project_routing_transport.lua", {
  COMMANDS = COMMANDS,
  armed_track_count = armed_track_count,
  current_project = current_project,
  find_hardware_output_send = find_hardware_output_send,
  find_track_by_guid = find_track_by_guid,
  hardware_output_snapshot = hardware_output_snapshot,
  master_track_mutation_result = master_track_mutation_result,
  master_track_snapshot = master_track_snapshot,
  project_markers_and_regions = project_markers_and_regions,
  project_name = project_name,
  project_time_signature = project_time_signature,
  project_tracks = project_tracks,
  require_postconditions = require_postconditions,
  require_track_by_guid = require_track_by_guid,
  require_track_send = require_track_send,
  restore_selected_tracks = restore_selected_tracks,
  safe_number_call = safe_number_call,
  snapshot_selected_tracks = snapshot_selected_tracks,
  track_expected_fields = track_expected_fields,
  track_freeze_state = track_freeze_state,
  track_mutation_result = track_mutation_result,
  track_selection_matches = track_selection_matches,
  track_send_list = track_send_list,
  track_send_snapshot = track_send_snapshot,
  track_snapshot = track_snapshot,
  transport_result = transport_result,
  transport_state = transport_state,
})

load_bridge_module("fx_arrangement_tempo.lua", {
  COMMANDS = COMMANDS,
  available_fx_list = available_fx_list,
  current_project = current_project,
  fx_parameter_list = fx_parameter_list,
  installed_fx_matches = installed_fx_matches,
  is_supported_time_signature_denominator =
    is_supported_time_signature_denominator,
  marker_payload = marker_payload,
  project_markers_and_regions = project_markers_and_regions,
  region_payload = region_payload,
  require_fx_identity = require_fx_identity,
  require_fx_parameter = require_fx_parameter,
  require_fx_track_by_guid = require_fx_track_by_guid,
  require_marker_identity = require_marker_identity,
  require_non_negative_seconds = require_non_negative_seconds,
  require_normalized_fx_parameter_value =
    require_normalized_fx_parameter_value,
  require_region_identity = require_region_identity,
  require_take_by_guid = require_take_by_guid,
  require_take_fx_identity = require_take_fx_identity,
  safe_number_call = safe_number_call,
  safe_string_call = safe_string_call,
  take_fx_list = take_fx_list,
  take_fx_snapshot = take_fx_snapshot,
  tempo_marker_index_at_project_start = tempo_marker_index_at_project_start,
  tempo_state = tempo_state,
  track_fx_list = track_fx_list,
  track_fx_snapshot = track_fx_snapshot,
})

RENDER_RUNTIME = load_bridge_module("render.lua", {
  COMMANDS = COMMANDS,
  RENDER_DEADLINE_SECONDS = RENDER_DEADLINE_SECONDS,
  RENDER_STABLE_POLLS = RENDER_STABLE_POLLS,
  bridge_clock = bridge_clock,
  current_project = current_project,
  path_join = path_join,
  response_payload = response_payload,
  safe_number_call = safe_number_call,
  safe_string_call = safe_string_call,
  write_render_job_progress = write_render_job_progress,
  write_render_job_response = write_render_job_response,
})

load_bridge_module("media_midi.lua", {
  COMMANDS = COMMANDS,
  MIDI_CONTROLLER = MIDI_CONTROLLER,
  current_project = current_project,
  find_inserted_media_item = find_inserted_media_item,
  find_requested_midi_notes = find_requested_midi_notes,
  item_guid = item_guid,
  media_item_mutation_result = media_item_mutation_result,
  media_item_position = media_item_position,
  media_item_selection_matches = media_item_selection_matches,
  media_item_snapshot = media_item_snapshot,
  midi_note_snapshot = midi_note_snapshot,
  midi_notes = midi_notes,
  musical_position = musical_position,
  musical_range = musical_range,
  postcondition_values_match = postcondition_values_match,
  project_media_items = project_media_items,
  region_payload = region_payload,
  require_distinct_midi_note_insertions =
    require_distinct_midi_note_insertions,
  require_media_item_by_guid = require_media_item_by_guid,
  require_midi_note_identity = require_midi_note_identity,
  require_midi_take_by_guid = require_midi_take_by_guid,
  require_region_identity = require_region_identity,
  require_take_by_guid = require_take_by_guid,
  require_track_by_guid = require_track_by_guid,
  restore_selected_media_items = restore_selected_media_items,
  restore_selected_tracks = restore_selected_tracks,
  safe_number_call = safe_number_call,
  safe_string_call = safe_string_call,
  snapshot_selected_media_items = snapshot_selected_media_items,
  snapshot_selected_tracks = snapshot_selected_tracks,
  take_guid = take_guid,
  track_selection_matches = track_selection_matches,
  track_snapshot = track_snapshot,
  validate_audio_source_path = validate_audio_source_path,
  validate_midi_note = validate_midi_note,
  validate_midi_note_identities = validate_midi_note_identities,
  validate_musical_position = validate_musical_position,
  validate_musical_range = validate_musical_range,
})

-- Load cohesive command families in separate Lua chunks. This avoids REAPER's
-- per-chunk local-variable ceiling while keeping one shared command contract.
load_bridge_module("automation_navigation.lua", {
  COMMANDS = COMMANDS,
  current_project = current_project,
  find_take_by_guid = find_take_by_guid,
  item_guid = item_guid,
  require_media_item_by_guid = require_media_item_by_guid,
  require_take_by_guid = require_take_by_guid,
  require_track_by_guid = require_track_by_guid,
  safe_number_call = safe_number_call,
  safe_string_call = safe_string_call,
  take_guid = take_guid,
})

load_bridge_module("vocal_tuning.lua", {
  COMMANDS = COMMANDS,
  current_project = current_project,
  fx_parameter_snapshot = fx_parameter_snapshot,
  installed_fx_matches = installed_fx_matches,
  item_guid = item_guid,
  require_fx_identity = require_fx_identity,
  require_fx_track_by_guid = require_fx_track_by_guid,
  require_media_item_by_guid = require_media_item_by_guid,
  safe_number_call = safe_number_call,
  safe_string_call = safe_string_call,
  take_guid = take_guid,
  track_fx_snapshot = track_fx_snapshot,
})

local function render_error_details(envelope, error_text)
  local details = { command = envelope.command, error = error_text }
  local current_trace = RENDER_RUNTIME and RENDER_RUNTIME.current_trace() or nil
  if current_trace ~= nil then
    details.trace = current_trace
  end
  return details
end

local execute_command = load_bridge_module("command_execution.lua", {
  COMMANDS = COMMANDS,
  current_project = current_project,
  error_payload = error_payload,
  render_error_details = render_error_details,
  response_payload = response_payload,
})

local function decode_envelope(payload, fallback_id)
  local ok, decoded = pcall(json_decode, payload)
  if not ok then
    return nil, fallback_id, tostring(decoded)
  end

  local request_id = fallback_id
  if type(decoded) == "table" and type(decoded.id) == "string" and decoded.id ~= "" then
    request_id = decoded.id
  end

  local envelope, validation_error = validate_envelope(decoded)
  if not envelope then
    return nil, request_id, validation_error
  end
  return envelope, request_id, nil
end

local function request_id_from_filename(filename)
  return filename:gsub("%.json$", "")
end

local function write_payload(directory, request_id, payload)
  ensure_dir(directory)
  local response_path = path_join(directory, request_id .. ".json")
  local temp_response_path = response_path .. ".tmp"
  if write_file(temp_response_path, payload) then
    os.rename(temp_response_path, response_path)
    return true
  end
  return false
end

local function process_request_file(filename)
  local request_path = path_join(REQUESTS_DIR, filename)
  local payload = read_file(request_path)
  if not payload then
    return
  end

  local fallback_id = request_id_from_filename(filename)
  local envelope, request_id, decode_error = decode_envelope(payload, fallback_id)
  local response
  if envelope then
    if envelope.command == "render_project" then
      if envelope.options.mutates_project ~= false or envelope.options.dry_run then
        write_payload(
          RESPONSES_DIR,
          request_id,
          error_payload(
            request_id,
            "invalid_command_envelope",
            "Render commands must be read-classified and cannot use dry_run.",
            { command = envelope.command },
            false,
            "Use mutates_project=false and dry_run=false for render commands."
          )
        )
        os.remove(request_path)
        return
      end
      local idempotency_key = envelope.options.idempotency_key
      local existing_start = idempotency_key and IDEMPOTENCY_STARTS[idempotency_key]
      if existing_start then
        write_payload(RESPONSES_DIR, request_id, response_payload(request_id, true, existing_start))
        os.remove(request_path)
        return
      end
      local ok, started_or_error = pcall(RENDER_RUNTIME.start, envelope)
      if ok then
        if idempotency_key then
          IDEMPOTENCY_STARTS[idempotency_key] = started_or_error
        end
        write_payload(RESPONSES_DIR, request_id, response_payload(request_id, true, started_or_error))
      else
        write_payload(
          RESPONSES_DIR,
          request_id,
          RENDER_RUNTIME.error_response(
            request_id,
            tostring(started_or_error),
            RENDER_RUNTIME.current_trace()
          )
        )
        RENDER_RUNTIME.reset_request_state()
      end
      os.remove(request_path)
      return
    end
    response = execute_command(envelope)
  else
    response = error_payload(
      request_id,
      "invalid_command_envelope",
      "The request file did not contain a valid command envelope.",
      { error = decode_error },
      false,
      "Send a full command envelope with id, command, args, and options."
    )
  end

  write_payload(RESPONSES_DIR, request_id, response)
  RENDER_RUNTIME.reset_request_state()
  os.remove(request_path)
end

local function poll_requests()
  ensure_dir(BRIDGE_DIR)
  ensure_dir(REQUESTS_DIR)
  ensure_dir(RESPONSES_DIR)
  ensure_dir(JOBS_DIR)
  write_bridge_heartbeat()
  RENDER_RUNTIME.tick()
  if RENDER_RUNTIME.active_job() then
    reaper.defer(poll_requests)
    return
  end

  local pending_requests = {}
  local index = 0
  while true do
    local filename = reaper.EnumerateFiles(REQUESTS_DIR, index)
    if not filename then
      break
    end
    if filename:match("%.json$") then
      pending_requests[#pending_requests + 1] = filename
    end
    index = index + 1
  end

  for _, filename in ipairs(pending_requests) do
    process_request_file(filename)
    if RENDER_RUNTIME.active_job() then
      break
    end
  end

  reaper.defer(poll_requests)
end

poll_requests()
