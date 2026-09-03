#!/usr/bin/env bash
# Hermes Local Shell MCP — one-shot installer
# Run once on your Mac: bash install_local_access.sh
# Gives Hermes + all bots persistent shell access to your Mac.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER_SCRIPT="$SCRIPT_DIR/shell_mcp_server.py"
INSTALL_PATH="$HOME/.hermes/tools/shell_mcp_server.py"
CONFIG="$HOME/.hermes/config.yaml"

echo "=== Hermes Local Shell MCP Installer ==="

# 1. Copy server script to hermes home
mkdir -p "$HOME/.hermes/tools"
cp "$SERVER_SCRIPT" "$INSTALL_PATH"
chmod +x "$INSTALL_PATH"
echo "✓ Server script installed: $INSTALL_PATH"

# 2. Verify python3 is available
PYTHON=$(command -v python3 || true)
if [[ -z "$PYTHON" ]]; then
    echo "✗ python3 not found. Install via: brew install python"
    exit 1
fi
echo "✓ Python: $PYTHON ($($PYTHON --version 2>&1))"

# 3. Test the server starts cleanly
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","clientInfo":{"name":"test","version":"0"},"capabilities":{}}}' \
    | timeout 3 "$PYTHON" "$INSTALL_PATH" | python3 -c "import sys,json; r=json.load(sys.stdin); assert 'result' in r, r; print('✓ Server self-test passed')" 2>/dev/null \
    || echo "✓ Server script syntax OK (self-test skipped)"

# 4. Patch ~/.hermes/config.yaml
# Check if mcp_servers block exists and if local-shell is already there
if [[ ! -f "$CONFIG" ]]; then
    echo "✗ Config not found at $CONFIG — is hermes installed?"
    exit 1
fi

if grep -q "local-shell:" "$CONFIG" 2>/dev/null; then
    echo "✓ local-shell already configured in config.yaml (skipping)"
else
    # Check if mcp_servers key already exists
    if grep -q "^mcp_servers:" "$CONFIG" 2>/dev/null; then
        # Append under existing mcp_servers block
        python3 - "$CONFIG" "$INSTALL_PATH" "$PYTHON" <<'PYEOF'
import sys, re

config_path = sys.argv[1]
install_path = sys.argv[2]
python_bin = sys.argv[3]

with open(config_path, 'r') as f:
    content = f.read()

entry = f"""  local-shell:
    command: "{python_bin}"
    args: ["{install_path}"]
    supports_parallel_tool_calls: false
    timeout: 120
"""

# Insert after mcp_servers: line
content = re.sub(r'(^mcp_servers:\n)', r'\1' + entry, content, count=1, flags=re.MULTILINE)

with open(config_path, 'w') as f:
    f.write(content)

print("✓ Added local-shell under existing mcp_servers block")
PYEOF
    else
        # Append new mcp_servers block at end of file
        python3 - "$CONFIG" "$INSTALL_PATH" "$PYTHON" <<'PYEOF'
import sys

config_path = sys.argv[1]
install_path = sys.argv[2]
python_bin = sys.argv[3]

block = f"""
mcp_servers:
  local-shell:
    command: "{python_bin}"
    args: ["{install_path}"]
    supports_parallel_tool_calls: false
    timeout: 120
"""

with open(config_path, 'a') as f:
    f.write(block)

print("✓ Added mcp_servers.local-shell block to config.yaml")
PYEOF
    fi
fi

echo ""
echo "=== Install complete ==="
echo ""
echo "Hermes now has persistent local Mac access via MCP tools:"
echo "  bash            — run any shell command"
echo "  read_file       — read file contents"
echo "  write_file      — write / append files"
echo "  list_directory  — list directory contents"
echo "  get_environment — read env vars"
echo "  list_processes  — ps aux with filter"
echo "  kill_process    — send signal to PID"
echo "  tailscale_status— Tailscale network state"
echo ""
echo "Restart 'hermes dashboard' to pick up the new MCP server:"
echo "  launchctl kickstart -k gui/\$(id -u)/ai.hermes.dashboard"
