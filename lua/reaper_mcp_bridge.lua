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

local BRIDGE_DIR = os.getenv("REAPER_MCP_BRIDGE_DIR")
  or path_join(default_temp_dir(), "reaper-mcp-bridge")
local REQUESTS_DIR = path_join(BRIDGE_DIR, "requests")
local RESPONSES_DIR = path_join(BRIDGE_DIR, "responses")
local JOBS_DIR = path_join(BRIDGE_DIR, "jobs")
local HEARTBEAT_PATH = path_join(BRIDGE_DIR, "bridge.heartbeat")
local CURRENT_RENDER_TRACE = nil
local CURRENT_RENDER_TRACE_STARTED_AT = nil
local CURRENT_RENDER_JOB_ID = nil
local ACTIVE_RENDER_JOB = nil
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
    return {
      status = "ok",
      bridge_version = BRIDGE_VERSION,
      bridge_dir = BRIDGE_DIR,
      requests_dir = REQUESTS_DIR,
      responses_dir = RESPONSES_DIR,
      jobs_dir = JOBS_DIR,
      heartbeat_path = HEARTBEAT_PATH,
      active_render_job_id = ACTIVE_RENDER_JOB and ACTIVE_RENDER_JOB.id or nil,
      active_render_status = ACTIVE_RENDER_JOB and ACTIVE_RENDER_JOB.status or "idle",
      pending_request_count = count_request_files(envelope.id),
      uptime_seconds = os.time() - START_TIME,
      supported_commands = {
        "health_check",
        "get_reaper_version",
        "get_project_info",
        "get_bridge_status",
        "get_project_snapshot",
        "list_tracks",
        "create_track",
        "rename_track",
        "set_track_color",
        "set_track_mute",
        "set_track_solo",
        "set_track_arm",
        "set_track_volume",
        "set_track_pan",
        "delete_track",
        "list_track_envelopes",
        "ensure_track_envelope",
        "get_envelope_points",
        "add_envelope_points",
        "update_envelope_point",
        "delete_envelope_points",
        "delete_envelope_points_in_range",
        "get_track_automation_mode",
        "set_track_automation_mode",
        "get_master_track",
        "set_master_volume",
        "set_master_pan",
        "set_master_mute",
        "list_track_sends",
        "create_track_send",
        "set_track_send",
        "remove_track_send",
        "get_track_freeze_state",
        "freeze_track",
        "unfreeze_track",
        "create_song_starter",
        "play",
        "stop",
        "stop_recording",
        "pause",
        "record",
        "list_available_fx",
        "list_track_fx",
        "add_fx",
        "remove_fx",
        "set_fx_enabled",
        "get_fx_parameters",
        "set_fx_parameter",
        "list_markers",
        "create_marker",
        "delete_marker",
        "list_regions",
        "create_region",
        "delete_region",
        "get_tempo",
        "set_tempo",
        "get_time_signature",
        "set_time_signature",
        "render_project",
        "list_media_items",
        "create_midi_item",
        "insert_audio_item",
        "move_media_item",
        "resize_media_item",
        "duplicate_media_item",
        "split_media_item",
        "set_media_item_mute",
        "set_media_item_gain",
        "set_media_item_fade_in",
        "set_media_item_fade_out",
        "delete_media_item",
        "list_item_takes",
        "add_empty_take",
        "set_active_take",
        "rename_take",
        "set_take_property",
        "crop_to_active_take",
        "get_midi_notes",
        "add_midi_notes",
        "update_midi_note",
        "delete_midi_notes",
        "transpose_midi_notes",
        "nudge_midi_notes",
        "quantize_midi_notes",
        "humanize_midi_notes",
        "snap_midi_notes_to_scale",
        "shape_midi_note_velocities",
        "remove_midi_note_overlaps",
        "get_project_navigation",
        "set_edit_cursor",
        "set_time_selection",
        "clear_time_selection",
        "set_loop_points",
        "set_loop_enabled",
        "save_project",
        "save_project_as",
      },
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
    selected = safe_bool_call(reaper.IsTrackSelected, false, track),
    media_item_count = safe_number_call(reaper.CountTrackMediaItems, 0, track),
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

local function track_mutation_result(project, track)
  reaper.TrackList_AdjustWindows(false)
  reaper.UpdateArrange()
  return {
    track = track_snapshot(track),
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

local function master_track_mutation_result(project)
  reaper.TrackList_AdjustWindows(false)
  reaper.UpdateArrange()
  return {
    master_track = master_track_snapshot(project),
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

  local track = require_track_by_guid(project, identity.track_guid)
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
  local normalized_name = (name and name ~= "") and name or ("Parameter " .. tostring(parameter_index + 1))
  return {
    index = parameter_index,
    name = normalized_name,
    normalized_value = reaper.TrackFX_GetParamNormalized(track, fx_index, parameter_index),
    formatted_value = formatted_value or "",
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

    return {
      track = track_snapshot(track),
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
    return track_mutation_result(project, track)
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
    return track_mutation_result(project, track)
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
    return track_mutation_result(project, track)
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
    return track_mutation_result(project, track)
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
    return track_mutation_result(project, track)
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
    return track_mutation_result(project, track)
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
    return track_mutation_result(project, track)
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
    return {
      deleted_track_guid = args.track_guid,
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
    return master_track_mutation_result(project)
  end,
}

COMMANDS.set_master_pan = {
  mutates_project = true,
  handler = function(envelope)
    local project = current_project()
    local master_track = reaper.GetMasterTrack(project)
    reaper.SetMediaTrackInfo_Value(master_track, "D_PAN", envelope.args.pan)
    return master_track_mutation_result(project)
  end,
}

COMMANDS.set_master_mute = {
  mutates_project = true,
  handler = function(envelope)
    local project = current_project()
    local master_track = reaper.GetMasterTrack(project)
    local muted = envelope.args.muted and 1 or 0
    reaper.SetMediaTrackInfo_Value(master_track, "B_MUTE", muted)
    return master_track_mutation_result(project)
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
    local track = require_track_by_guid(project, envelope.args.track_guid)
    local fx = track_fx_list(track, envelope.args.track_guid)
    return {
      track_guid = envelope.args.track_guid,
      fx = fx,
      fx_count = #fx,
    }
  end,
}

COMMANDS.add_fx = {
  mutates_project = true,
  preflight_handler = function(envelope)
    local project = current_project()
    require_track_by_guid(project, envelope.args.track_guid)
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
    local track = require_track_by_guid(project, args.track_guid)
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

register_expansion_commands()

local function render_error_details(envelope, error_text)
  local details = { command = envelope.command, error = error_text }
  if CURRENT_RENDER_TRACE ~= nil then
    details.trace = CURRENT_RENDER_TRACE
  end
  return details
end

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
      local ok, started_or_error = pcall(start_render_job, envelope)
      if ok then
        if idempotency_key then
          IDEMPOTENCY_STARTS[idempotency_key] = started_or_error
        end
        write_payload(RESPONSES_DIR, request_id, response_payload(request_id, true, started_or_error))
      else
        write_payload(
          RESPONSES_DIR,
          request_id,
          render_error_response(request_id, tostring(started_or_error), CURRENT_RENDER_TRACE)
        )
        CURRENT_RENDER_TRACE = nil
        CURRENT_RENDER_TRACE_STARTED_AT = nil
        CURRENT_RENDER_JOB_ID = nil
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
  CURRENT_RENDER_TRACE = nil
  CURRENT_RENDER_TRACE_STARTED_AT = nil
  CURRENT_RENDER_JOB_ID = nil
  os.remove(request_path)
end

local function poll_requests()
  ensure_dir(BRIDGE_DIR)
  ensure_dir(REQUESTS_DIR)
  ensure_dir(RESPONSES_DIR)
  ensure_dir(JOBS_DIR)
  write_bridge_heartbeat()
  tick_render_job()
  if ACTIVE_RENDER_JOB then
    reaper.defer(poll_requests)
    return
  end

  local index = 0
  while true do
    local filename = reaper.EnumerateFiles(REQUESTS_DIR, index)
    if not filename then
      break
    end
    if filename:match("%.json$") then
      process_request_file(filename)
      if ACTIVE_RENDER_JOB then
        break
      end
    end
    index = index + 1
  end

  reaper.defer(poll_requests)
end

poll_requests()
