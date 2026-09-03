#!/usr/bin/env python3
"""
Hermes Local Shell MCP Server

Gives Hermes and all sub-agents full local Mac access:
  - Run shell commands (bash)
  - Read / write files
  - List directories
  - Read environment variables
  - List / kill processes
  - Tailscale status

Transport: stdio (managed by Hermes; no separate service needed)
Install:   configure mcp_servers in ~/.hermes/config.yaml (see README below)
"""

import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Minimal MCP stdio server — no external deps beyond stdlib
# Uses the JSON-RPC 2.0 / MCP protocol manually so we don't need the
# `mcp` package pinned to a specific version.
# ---------------------------------------------------------------------------

def _send(obj: dict):
    line = json.dumps(obj)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def _result(req_id, result_val):
    _send({"jsonrpc": "2.0", "id": req_id, "result": result_val})


def _error(req_id, code: int, message: str):
    _send({"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}})


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def _run_shell(command: str, cwd: str | None = None, timeout: int = 60, env_extra: dict | None = None) -> dict:
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            cwd=cwd or os.path.expanduser("~"),
            timeout=timeout,
            env=env,
        )
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
            "success": result.returncode == 0,
        }
    except subprocess.TimeoutExpired:
        return {"stdout": "", "stderr": f"Command timed out after {timeout}s", "returncode": -1, "success": False}
    except Exception as exc:
        return {"stdout": "", "stderr": str(exc), "returncode": -1, "success": False}


def _read_file(path: str, encoding: str = "utf-8") -> dict:
    p = Path(path).expanduser()
    try:
        if not p.exists():
            return {"error": f"File not found: {path}"}
        if p.stat().st_size > 10 * 1024 * 1024:
            return {"error": "File too large (>10MB); use shell cat with head/tail"}
        text = p.read_text(encoding=encoding, errors="replace")
        return {"content": text, "path": str(p), "size": p.stat().st_size}
    except Exception as exc:
        return {"error": str(exc)}


def _write_file(path: str, content: str, append: bool = False) -> dict:
    p = Path(path).expanduser()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if append else "w"
        if not append:
            p.write_text(content, encoding="utf-8")
        else:
            with p.open(mode, encoding="utf-8") as f:
                f.write(content)
        return {"success": True, "path": str(p), "bytes": len(content.encode())}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def _list_dir(path: str, show_hidden: bool = False) -> dict:
    p = Path(path).expanduser()
    try:
        if not p.exists():
            return {"error": f"Path not found: {path}"}
        entries = []
        for item in sorted(p.iterdir()):
            if not show_hidden and item.name.startswith("."):
                continue
            st = item.stat()
            entries.append({
                "name": item.name,
                "type": "dir" if item.is_dir() else "file",
                "size": st.st_size,
            })
        return {"path": str(p), "entries": entries, "count": len(entries)}
    except Exception as exc:
        return {"error": str(exc)}


def _get_env(keys: list[str] | None = None) -> dict:
    if keys:
        return {k: os.environ.get(k, "") for k in keys}
    # Return non-secret env vars by default
    safe = {}
    secret_patterns = {"TOKEN", "SECRET", "PASSWORD", "KEY", "PASS", "CREDENTIAL"}
    for k, v in os.environ.items():
        if any(p in k.upper() for p in secret_patterns):
            safe[k] = "***REDACTED***"
        else:
            safe[k] = v
    return safe


def _process_list(name_filter: str | None = None) -> dict:
    result = subprocess.run(
        ["ps", "aux"],
        capture_output=True, text=True
    )
    lines = result.stdout.strip().split("\n")
    header = lines[0] if lines else ""
    procs = []
    for line in lines[1:]:
        if name_filter and name_filter.lower() not in line.lower():
            continue
        parts = line.split(None, 10)
        if len(parts) >= 11:
            procs.append({"pid": parts[1], "cpu": parts[2], "mem": parts[3], "command": parts[10]})
    return {"header": header, "processes": procs, "count": len(procs)}


def _kill_process(pid: int, signal: str = "TERM") -> dict:
    sig_map = {"TERM": 15, "KILL": 9, "HUP": 1, "INT": 2}
    sig_num = sig_map.get(signal.upper(), 15)
    result = subprocess.run(["kill", f"-{sig_num}", str(pid)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    return {"success": result.returncode == 0, "stderr": result.stderr}


def _tailscale_status() -> dict:
    r = _run_shell("tailscale status --json", timeout=10)
    if r["success"]:
        try:
            return json.loads(r["stdout"])
        except Exception:
            return {"raw": r["stdout"]}
    return {"error": r["stderr"]}


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "bash",
        "description": (
            "Run a shell command on the local Mac. Returns stdout, stderr, and return code. "
            "Runs in bash with the user's full environment. "
            "Use for any system operation: file ops, brew, launchctl, git, ollama, etc."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to execute"},
                "cwd": {"type": "string", "description": "Working directory (default: ~)"},
                "timeout": {"type": "integer", "description": "Timeout in seconds (default: 60)"},
            },
            "required": ["command"],
        },
    },
    {
        "name": "read_file",
        "description": "Read a local file's content. Supports ~ expansion. Max 10MB.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path (~ supported)"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write or append content to a local file. Creates parent dirs automatically.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path (~ supported)"},
                "content": {"type": "string", "description": "Content to write"},
                "append": {"type": "boolean", "description": "Append instead of overwrite (default: false)"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "list_directory",
        "description": "List files and directories at a path.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path (~ supported)"},
                "show_hidden": {"type": "boolean", "description": "Include dotfiles (default: false)"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "get_environment",
        "description": "Get environment variables. Secrets are redacted unless you name specific keys.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "keys": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Specific keys to fetch (unredacted). Omit for full env (secrets redacted).",
                },
            },
        },
    },
    {
        "name": "list_processes",
        "description": "List running processes on the Mac (ps aux). Optional name filter.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name_filter": {"type": "string", "description": "Filter by process name substring"},
            },
        },
    },
    {
        "name": "kill_process",
        "description": "Send a signal to a process by PID.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "pid": {"type": "integer", "description": "Process ID"},
                "signal": {"type": "string", "description": "Signal name: TERM (default), KILL, HUP, INT"},
            },
            "required": ["pid"],
        },
    },
    {
        "name": "tailscale_status",
        "description": "Get current Tailscale network status including peers, IPs, and connectivity.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def _call_tool(name: str, args: dict) -> Any:
    if name == "bash":
        return _run_shell(args["command"], cwd=args.get("cwd"), timeout=args.get("timeout", 60))
    elif name == "read_file":
        return _read_file(args["path"])
    elif name == "write_file":
        return _write_file(args["path"], args["content"], append=args.get("append", False))
    elif name == "list_directory":
        return _list_dir(args["path"], show_hidden=args.get("show_hidden", False))
    elif name == "get_environment":
        return _get_env(args.get("keys"))
    elif name == "list_processes":
        return _process_list(args.get("name_filter"))
    elif name == "kill_process":
        return _kill_process(args["pid"], args.get("signal", "TERM"))
    elif name == "tailscale_status":
        return _tailscale_status()
    else:
        return {"error": f"Unknown tool: {name}"}


# ---------------------------------------------------------------------------
# MCP protocol main loop
# ---------------------------------------------------------------------------

SERVER_INFO = {
    "name": "hermes-local-shell",
    "version": "1.0.0",
}

CAPABILITIES = {
    "tools": {"listChanged": False},
}


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue

        req_id = req.get("id")
        method = req.get("method", "")
        params = req.get("params", {})

        if method == "initialize":
            _result(req_id, {
                "protocolVersion": "2024-11-05",
                "serverInfo": SERVER_INFO,
                "capabilities": CAPABILITIES,
            })

        elif method == "notifications/initialized":
            pass  # no response needed for notifications

        elif method == "tools/list":
            _result(req_id, {"tools": TOOLS})

        elif method == "tools/call":
            tool_name = params.get("name", "")
            tool_args = params.get("arguments", {})
            try:
                result_val = _call_tool(tool_name, tool_args)
                _result(req_id, {
                    "content": [{"type": "text", "text": json.dumps(result_val, indent=2)}],
                    "isError": False,
                })
            except Exception as exc:
                _result(req_id, {
                    "content": [{"type": "text", "text": json.dumps({"error": str(exc)})}],
                    "isError": True,
                })

        elif method == "ping":
            _result(req_id, {})

        else:
            if req_id is not None:
                _error(req_id, -32601, f"Method not found: {method}")


if __name__ == "__main__":
    main()
