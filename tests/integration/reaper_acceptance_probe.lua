-- Read and change REAPER undo state for opt-in live acceptance tests.

local function path_join(left, right)
  local separator = package.config:sub(1, 1)
  if left:sub(-1) == separator then
    return left .. right
  end
  return left .. separator .. right
end

local function read_file(path)
  local file = io.open(path, "rb")
  if not file then
    return ""
  end
  local value = file:read("*a")
  file:close()
  return value
end

local function json_escape(value)
  return tostring(value)
    :gsub("\\", "\\\\")
    :gsub('"', '\\"')
    :gsub("\n", "\\n")
    :gsub("\r", "\\r")
end

local bridge_dir = os.getenv("REAPER_MCP_BRIDGE_DIR")
if not bridge_dir or bridge_dir == "" then
  error("REAPER_MCP_BRIDGE_DIR is required for the acceptance probe")
end

local command_path = path_join(bridge_dir, "acceptance-probe-command.txt")
local output_path = path_join(bridge_dir, "acceptance-probe.json")
local last_request_id = nil
local last_action_name = ""
local last_track_guid = ""

local function execute_command(command)
  last_action_name = ""
  if command == "undo" then
    reaper.Undo_DoUndo2(0)
  elseif command == "redo" then
    reaper.Undo_DoRedo2(0)
  elseif command == "save_project" then
    reaper.Main_SaveProjectEx(
      0,
      path_join(bridge_dir, "freeze-acceptance.rpp"),
      0
    )
  elseif command:sub(1, 13) == "select_track:" then
    local requested_guid = command:sub(14)
    local found = false
    for index = 0, reaper.CountTracks(0) - 1 do
      local track = reaper.GetTrack(0, index)
      local selected = reaper.GetTrackGUID(track) == requested_guid
      reaper.SetTrackSelected(track, selected)
      found = found or selected
    end
    if not found then
      error("Track GUID was not found: " .. requested_guid)
    end
  elseif command:sub(1, 12) == "action_name:" then
    local command_id = tonumber(command:sub(13))
    if not command_id then
      error("Action command ID must be numeric")
    end
    last_action_name = reaper.kbd_getTextFromCmd(command_id, 0) or ""
  elseif command == "create_fixed_lane_fixture" then
    reaper.Undo_BeginBlock2(0)
    reaper.InsertTrackAtIndex(reaper.CountTracks(0), true)
    local track = reaper.GetTrack(0, reaper.CountTracks(0) - 1)
    if not track then
      error("REAPER did not create the fixed-lane fixture track")
    end
    reaper.GetSetMediaTrackInfo_String(
      track,
      "P_NAME",
      "Fixed Lane Acceptance",
      true
    )
    reaper.SetMediaTrackInfo_Value(track, "I_FREEMODE", 2)
    reaper.SetMediaTrackInfo_Value(track, "I_NUMFIXEDLANES", 2)
    local first = reaper.CreateNewMIDIItemInProj(track, 0, 1, false)
    local second = reaper.CreateNewMIDIItemInProj(track, 1, 2, false)
    if not first or not second then
      error("REAPER did not create the fixed-lane fixture items")
    end
    reaper.SetMediaItemInfo_Value(first, "I_FIXEDLANE", 0)
    reaper.SetMediaItemInfo_Value(second, "I_FIXEDLANE", 1)
    reaper.GetSetMediaTrackInfo_String(track, "P_LANENAME:0", "Lead A", true)
    reaper.GetSetMediaTrackInfo_String(track, "P_LANENAME:1", "Lead B", true)
    reaper.SetMediaTrackInfo_Value(track, "C_LANEPLAYS:0", 1)
    reaper.TrackList_AdjustWindows(false)
    reaper.UpdateTimeline()
    reaper.UpdateArrange()
    last_track_guid = reaper.GetTrackGUID(track) or ""
    reaper.Undo_EndBlock2(0, "Create fixed lane fixture", -1)
  elseif command ~= "status" then
    error("Unsupported acceptance probe command: " .. tostring(command))
  end
end

local function write_output(request_id, command, command_error)
  local output = io.open(output_path, "wb")
  if not output then
    return
  end
  output:write(string.format(
    '{"request_id":"%s","command":"%s","error":"%s","action_name":"%s",'
      .. '"dirty":%s,"play_state":%d,"redo_label":"%s",'
      .. '"state_change_count":%d,"track_count":%d,"track_guid":"%s",'
      .. '"undo_label":"%s"}',
    json_escape(request_id),
    json_escape(command),
    json_escape(command_error or ""),
    json_escape(last_action_name),
    reaper.IsProjectDirty(0) ~= 0 and "true" or "false",
    reaper.GetPlayState(),
    json_escape(reaper.Undo_CanRedo2(0) or ""),
    reaper.GetProjectStateChangeCount(0),
    reaper.CountTracks(0),
    json_escape(last_track_guid),
    json_escape(reaper.Undo_CanUndo2(0) or "")
  ))
  output:close()
end

local function poll()
  local request = read_file(command_path):match("^%s*(.-)%s*$")
  local request_id, command = request:match("^([^|]+)|(.*)$")
  if request_id and request_id ~= last_request_id then
    last_request_id = request_id
    local ok, command_error = pcall(execute_command, command)
    write_output(request_id, command, ok and nil or command_error)
  end
  reaper.defer(poll)
end

poll()
