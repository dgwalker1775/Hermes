#!/usr/bin/env python3
"""
Hermes local model router.

Task type → agent → tier → Ollama model, with memory pressure override
and Phase Zero approval gates.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ── enums ─────────────────────────────────────────────────────────────────────

class Agent(str, Enum):
    HERMES = "hermes"
    AEGIS = "aegis"
    VOX = "vox"
    ATLAS = "atlas"


class TaskType(str, Enum):
    TRADING = "trading"
    FINANCE = "finance"
    CONTENT = "content"
    COMMUNICATION = "communication"
    RESEARCH = "research"
    KNOWLEDGE = "knowledge"
    ADMIN = "admin"
    UNKNOWN = "unknown"


class ApprovalGate(str, Enum):
    NONE = "none"
    SOFT = "soft"       # warn user, proceed after acknowledgement
    HARD = "hard"       # block until explicit human approval
    BLOCKED = "blocked" # never execute


# ── config ────────────────────────────────────────────────────────────────────

AGENT_MODELS: dict[Agent, str] = {
    Agent.HERMES: "hermes",
    Agent.AEGIS: "aegis",
    Agent.VOX: "vox",
    Agent.ATLAS: "atlas",
}

# Fallback models when memory pressure is high or custom model missing
FALLBACK_MODELS: dict[Agent, str] = {
    Agent.HERMES: "llama3.1:8b",
    Agent.AEGIS: "llama3.1:8b",
    Agent.VOX: "llama3.1:8b",
    Agent.ATLAS: "llama3.1:8b",
}

TASK_ROUTING: dict[TaskType, Agent] = {
    TaskType.TRADING: Agent.AEGIS,
    TaskType.FINANCE: Agent.AEGIS,
    TaskType.CONTENT: Agent.VOX,
    TaskType.COMMUNICATION: Agent.VOX,
    TaskType.RESEARCH: Agent.ATLAS,
    TaskType.KNOWLEDGE: Agent.ATLAS,
    TaskType.ADMIN: Agent.HERMES,
    TaskType.UNKNOWN: Agent.HERMES,
}

# Keywords that classify a task (checked in order, first match wins)
TASK_KEYWORDS: list[tuple[list[str], TaskType]] = [
    (["trade", "signal", "rsi", "macd", "ticker", "stock", "crypto", "position", "portfolio", "order", "entry", "exit", "stop loss"], TaskType.TRADING),
    (["earnings", "revenue", "margin", "valuation", "p/e", "balance sheet", "cash flow", "financial model"], TaskType.FINANCE),
    (["email", "draft", "write", "compose", "message", "slack", "memo", "letter", "communicate"], TaskType.COMMUNICATION),
    (["blog", "post", "article", "script", "caption", "copy", "content", "summary", "summarize", "rewrite", "edit"], TaskType.CONTENT),
    (["research", "find", "look up", "explain", "what is", "how does", "why does", "compare", "analyze"], TaskType.RESEARCH),
    (["define", "describe", "history of", "background on", "knowledge", "learn"], TaskType.KNOWLEDGE),
    (["schedule", "remind", "task", "todo", "admin", "organize", "manage"], TaskType.ADMIN),
]

# Phase Zero: patterns that require approval gates
APPROVAL_PATTERNS: list[tuple[str, ApprovalGate, str]] = [
    ("place.*order|execute.*trade|buy.*shares|sell.*shares", ApprovalGate.BLOCKED, "Live trading is disabled in Phase Zero"),
    ("send.*email|send.*message|post.*to", ApprovalGate.HARD, "External communications require human approval"),
    ("connect.*api|api.*key|brokerage|broker", ApprovalGate.HARD, "External API connections require human approval"),
    ("delete|drop table|rm -rf", ApprovalGate.HARD, "Destructive operations require human approval"),
    ("web.*search|browse|scrape", ApprovalGate.SOFT, "External data access — verify before proceeding"),
]


# ── data classes ──────────────────────────────────────────────────────────────

@dataclass
class RoutingDecision:
    task_type: TaskType
    agent: Agent
    model: str
    approval_gate: ApprovalGate
    gate_reason: str
    fallback_used: bool
    latency_ms: Optional[int] = None
    response: Optional[str] = None
    error: Optional[str] = None
    audit_log: list[str] = field(default_factory=list)


# ── core router ───────────────────────────────────────────────────────────────

class HermesRouter:
    def __init__(
        self,
        memory_pressure_threshold: float = 0.85,
        timeout_seconds: int = 60,
        audit_log_path: Optional[str] = None,
    ):
        self.memory_pressure_threshold = memory_pressure_threshold
        self.timeout_seconds = timeout_seconds
        self.audit_log_path = audit_log_path or os.path.expanduser("~/hermes-fix/router_audit.jsonl")
        os.makedirs(os.path.dirname(self.audit_log_path), exist_ok=True)

    # ── classification ────────────────────────────────────────────────────────

    def classify(self, prompt: str) -> TaskType:
        lower = prompt.lower()
        for keywords, task_type in TASK_KEYWORDS:
            if any(kw in lower for kw in keywords):
                return task_type
        return TaskType.UNKNOWN

    def check_approval_gate(self, prompt: str) -> tuple[ApprovalGate, str]:
        import re
        lower = prompt.lower()
        worst_gate = ApprovalGate.NONE
        worst_reason = ""
        gate_order = [ApprovalGate.NONE, ApprovalGate.SOFT, ApprovalGate.HARD, ApprovalGate.BLOCKED]
        for pattern, gate, reason in APPROVAL_PATTERNS:
            if re.search(pattern, lower):
                if gate_order.index(gate) > gate_order.index(worst_gate):
                    worst_gate = gate
                    worst_reason = reason
        return worst_gate, worst_reason

    # ── model selection ───────────────────────────────────────────────────────

    def _available_models(self) -> set[str]:
        try:
            result = subprocess.run(
                ["ollama", "list"],
                capture_output=True, text=True, timeout=10
            )
            models = set()
            for line in result.stdout.splitlines()[1:]:  # skip header
                parts = line.split()
                if parts:
                    models.add(parts[0].split(":")[0])
            return models
        except Exception:
            return set()

    def _memory_pressure(self) -> float:
        """Return fraction of RAM in use (0.0–1.0). Returns 0.0 on error."""
        try:
            if sys.platform == "darwin":
                out = subprocess.check_output(["vm_stat"], text=True)
                pages: dict[str, int] = {}
                for line in out.splitlines():
                    for key in ("Pages free", "Pages active", "Pages inactive", "Pages wired down", "Pages speculative"):
                        if line.startswith(key):
                            pages[key] = int(line.split()[-1].rstrip("."))
                total = sum(pages.values())
                used = total - pages.get("Pages free", 0) - pages.get("Pages speculative", 0)
                return used / total if total else 0.0
            else:
                with open("/proc/meminfo", encoding="utf-8") as f:
                    info = {}
                    for line in f:
                        k, v = line.split(":")
                        info[k.strip()] = int(v.strip().split()[0])
                total = info.get("MemTotal", 1)
                available = info.get("MemAvailable", total)
                return 1.0 - (available / total)
        except Exception:
            return 0.0

    def select_model(self, agent: Agent) -> tuple[str, bool]:
        """Return (model_name, fallback_used)."""
        available = self._available_models()
        primary = AGENT_MODELS[agent]
        pressure = self._memory_pressure()
        high_pressure = pressure > self.memory_pressure_threshold

        if not high_pressure and primary in available:
            return primary, False

        fallback = FALLBACK_MODELS[agent]
        reason = "memory pressure" if high_pressure else f"model '{primary}' not installed"
        print(f"  ⚠ Using fallback '{fallback}' for {agent.value} ({reason})", file=sys.stderr)
        return fallback, True

    # ── execution ─────────────────────────────────────────────────────────────

    def run(self, prompt: str, agent: Agent, model: str) -> tuple[Optional[str], Optional[str]]:
        try:
            t0 = time.monotonic()
            result = subprocess.run(
                ["ollama", "run", model],
                input=prompt,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            if result.returncode != 0:
                return None, result.stderr.strip() or "non-zero exit"
            return result.stdout.strip(), None
        except subprocess.TimeoutExpired:
            return None, f"timeout after {self.timeout_seconds}s"
        except FileNotFoundError:
            return None, "ollama binary not found — is Ollama installed?"
        except Exception as e:
            return None, str(e)

    # ── main entry point ───────────────────────────────────────────────────────

    def route(self, prompt: str, dry_run: bool = False) -> RoutingDecision:
        task_type = self.classify(prompt)
        agent = TASK_ROUTING[task_type]
        model, fallback_used = self.select_model(agent)
        gate, gate_reason = self.check_approval_gate(prompt)

        decision = RoutingDecision(
            task_type=task_type,
            agent=agent,
            model=model,
            approval_gate=gate,
            gate_reason=gate_reason,
            fallback_used=fallback_used,
        )
        decision.audit_log.append(f"classify → {task_type.value}")
        decision.audit_log.append(f"route → {agent.value} ({model})")

        if gate == ApprovalGate.BLOCKED:
            decision.error = f"BLOCKED: {gate_reason}"
            decision.audit_log.append(f"blocked: {gate_reason}")
        elif gate == ApprovalGate.HARD:
            decision.error = f"REQUIRES APPROVAL: {gate_reason}"
            decision.audit_log.append(f"hard gate: {gate_reason}")
        elif not dry_run:
            if gate == ApprovalGate.SOFT:
                print(f"  ⚠ SOFT GATE: {gate_reason}", file=sys.stderr)
            response, error = self.run(prompt, agent, model)
            decision.response = response
            decision.error = error

        self._write_audit(decision, prompt)
        return decision

    def _write_audit(self, decision: RoutingDecision, prompt: str) -> None:
        record = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "task_type": decision.task_type.value,
            "agent": decision.agent.value,
            "model": decision.model,
            "gate": decision.approval_gate.value,
            "fallback": decision.fallback_used,
            "prompt_preview": prompt[:120],
            "error": decision.error,
        }
        try:
            with open(self.audit_log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
        except OSError:
            pass


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Hermes local model router")
    parser.add_argument("prompt", nargs="?", help="Prompt to route (reads stdin if omitted)")
    parser.add_argument("--dry-run", action="store_true", help="Classify and select model without running Ollama")
    parser.add_argument("--json", action="store_true", help="Output routing decision as JSON")
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()

    prompt = args.prompt or sys.stdin.read().strip()
    if not prompt:
        parser.error("No prompt provided")

    router = HermesRouter(timeout_seconds=args.timeout)
    decision = router.route(prompt, dry_run=args.dry_run)

    if args.json:
        print(json.dumps({
            "task_type": decision.task_type.value,
            "agent": decision.agent.value,
            "model": decision.model,
            "gate": decision.approval_gate.value,
            "gate_reason": decision.gate_reason,
            "fallback_used": decision.fallback_used,
            "response": decision.response,
            "error": decision.error,
            "audit_log": decision.audit_log,
        }, indent=2))
    else:
        print(f"\n{'='*60}")
        print(f"Task type : {decision.task_type.value}")
        print(f"Agent     : {decision.agent.value}")
        print(f"Model     : {decision.model}" + (" (fallback)" if decision.fallback_used else ""))
        print(f"Gate      : {decision.approval_gate.value}" + (f" — {decision.gate_reason}" if decision.gate_reason else ""))
        if decision.error:
            print(f"Error     : {decision.error}")
        if decision.response:
            print(f"\n--- Response ---\n{decision.response}")
        print(f"{'='*60}\n")

    sys.exit(1 if decision.error else 0)


if __name__ == "__main__":
    main()
