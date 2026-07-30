-- Start both deferred acceptance loops from one REAPER command-line script.

local function path_join(left, right)
  local separator = package.config:sub(1, 1)
  if left:sub(-1) == separator then
    return left .. right
  end
  return left .. separator .. right
end

local repository_dir = os.getenv("REAPER_MCP_REPO_DIR")
if not repository_dir or repository_dir == "" then
  error("REAPER_MCP_REPO_DIR is required for the acceptance startup script")
end

local bridge_dir = os.getenv("REAPER_MCP_BRIDGE_DIR")
if not bridge_dir or bridge_dir == "" then
  error("REAPER_MCP_BRIDGE_DIR is required for the acceptance startup script")
end

local status_path = path_join(bridge_dir, "acceptance-startup-status.txt")
local function write_status(value)
  local status_file = io.open(status_path, "wb")
  if status_file then
    status_file:write(value)
    status_file:close()
  end
end

local function run(relative_path)
  local script_path = path_join(repository_dir, relative_path)
  local script, load_error = loadfile(script_path)
  if not script then
    error("Could not load " .. script_path .. ": " .. tostring(load_error))
  end
  script()
end

write_status("loading bridge")
local ok, startup_error = pcall(function()
  run(path_join("lua", "reaper_mcp_bridge.lua"))
  write_status("loading probe")
  run(path_join("tests", path_join("integration", "reaper_acceptance_probe.lua")))
end)
if not ok then
  write_status("error: " .. tostring(startup_error))
  error(startup_error)
end
write_status("ready")
