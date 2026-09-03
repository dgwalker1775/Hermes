# Hermes Local Shell MCP

Gives Hermes and every bot/agent in the desktop app full local Mac access.

## What it provides

| Tool | Description |
|------|-------------|
| `bash` | Run any shell command (brew, git, launchctl, ollama, etc.) |
| `read_file` | Read file contents (up to 10MB, `~` supported) |
| `write_file` | Write or append to any file |
| `list_directory` | List directory with file sizes |
| `get_environment` | Read env vars (secrets auto-redacted) |
| `list_processes` | `ps aux` with optional name filter |
| `kill_process` | Send TERM/KILL/HUP/INT to a PID |
| `tailscale_status` | Live Tailscale peer/IP status |

## Install (one command)

```bash
cd ~/AI-Desktop/agents/hermes   # or wherever you cloned the repo
bash tools/local_access/install_local_access.sh
```

Then restart the dashboard:
```bash
launchctl kickstart -k gui/$(id -u)/ai.hermes.dashboard
```

## How it works

- Pure Python stdlib — no pip installs required
- Runs as a **stdio MCP server** managed by Hermes itself
- Hermes starts the process on demand and keeps it alive per session
- All bots in the desktop app inherit it automatically via `mcp_servers` config

## Manual config (if installer fails)

Add to `~/.hermes/config.yaml`:

```yaml
mcp_servers:
  local-shell:
    command: "python3"
    args: ["/Users/dillonwalker/.hermes/tools/shell_mcp_server.py"]
    supports_parallel_tool_calls: false
    timeout: 120
```

Then restart the dashboard.
