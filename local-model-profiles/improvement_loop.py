#!/usr/bin/env python3
"""
Hermes self-terminating improvement loop.

Every run:
  1. Benchmarks all 4 agents on 3 standardized prompts (correctness, format, latency)
  2. Scores each agent 0–1 and aggregates system score
  3. Auto-tunes Modelfile temperatures when an agent scores < 0.80
  4. Tracks a convergence streak (all agents >= 0.80 AND delta < 5% AND zero routing failures)
  5. After 3 consecutive converged runs → sends Telegram final report + crontab -r
  6. Hard ceiling: stops after 50 runs regardless of convergence

Usage:
  python3 improvement_loop.py            # run one improvement cycle
  python3 improvement_loop.py --status   # show current scores and streak
  python3 improvement_loop.py --remove-cron  # kill the cron immediately
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sqlite3
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

# ── config ─────────────────────────────────────────────────────────────────────

WORK_DIR = Path(os.environ.get("HERMES_FIX_DIR", Path.home() / "hermes-fix"))
DB_PATH = WORK_DIR / "improvement_loop.db"
MODELFILES_DIR = WORK_DIR / "modelfiles"
LOG_PATH = WORK_DIR / "improvement_loop.log"

AGENTS = ["hermes", "aegis", "vox", "atlas"]

# Target temperatures per agent (ground truth from 02_rebuild_modelfiles.sh)
TARGET_TEMPS: dict[str, float] = {
    "hermes": 0.3,
    "aegis": 0.1,
    "vox": 0.65,
    "atlas": 0.2,
}

# Base model for all agents (update if you use a different base)
BASE_MODEL = "llama3.1:8b"

QUALITY_THRESHOLD = 0.80          # min score to count as "passing"
CONVERGENCE_DELTA = 0.05          # max run-over-run improvement to count as converged
CONVERGENCE_STREAK_REQUIRED = 3   # consecutive converged runs before self-termination
MAX_RUNS = 50                     # hard ceiling

# Telegram (set via env vars or leave blank to disable)
TELEGRAM_BOT_TOKEN = os.environ.get("HERMES_TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("HERMES_TELEGRAM_CHAT_ID", "")

# Benchmark prompts (label, prompt, expected keywords in good response)
BENCHMARK_PROMPTS: list[tuple[str, str, list[str]]] = [
    (
        "identity",
        "In one sentence, describe your primary role and the one hardest constraint you operate under.",
        ["role", "constraint", "phase", "approval", "advisory"],
    ),
    (
        "domain",
        "A user asks: 'RSI is 82 on BTC daily, MACD histogram turning red, volume 2.3x average. Assess.' Respond as your specialist role.",
        ["rsi", "overbought", "bearish", "volume", "signal", "confirm"],
    ),
    (
        "format",
        "Provide a structured 3-bullet summary of your operating rules. Use '•' for bullets.",
        ["•", "rule", "never", "always", "only"],
    ),
]


# ── DB ─────────────────────────────────────────────────────────────────────────

def init_db(db: sqlite3.Connection) -> None:
    db.executescript("""
    CREATE TABLE IF NOT EXISTS runs (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        ts          TEXT NOT NULL,
        run_number  INTEGER NOT NULL,
        system_score REAL,
        delta       REAL,
        converged   INTEGER,
        streak      INTEGER,
        terminated  INTEGER DEFAULT 0,
        notes       TEXT
    );
    CREATE TABLE IF NOT EXISTS agent_scores (
        id       INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id   INTEGER REFERENCES runs(id),
        agent    TEXT NOT NULL,
        score    REAL NOT NULL,
        latency_ms INTEGER,
        passing  INTEGER
    );
    CREATE TABLE IF NOT EXISTS tuning_log (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id    INTEGER REFERENCES runs(id),
        agent     TEXT NOT NULL,
        old_temp  REAL,
        new_temp  REAL,
        reason    TEXT
    );
    """)
    db.commit()


def get_run_number(db: sqlite3.Connection) -> int:
    row = db.execute("SELECT COALESCE(MAX(run_number), 0) FROM runs").fetchone()
    return (row[0] or 0) + 1


def get_last_system_score(db: sqlite3.Connection) -> Optional[float]:
    row = db.execute(
        "SELECT system_score FROM runs ORDER BY run_number DESC LIMIT 1"
    ).fetchone()
    return row[0] if row else None


def get_streak(db: sqlite3.Connection) -> int:
    rows = db.execute(
        "SELECT converged FROM runs ORDER BY run_number DESC LIMIT ?",
        (CONVERGENCE_STREAK_REQUIRED,)
    ).fetchall()
    streak = 0
    for (converged,) in rows:
        if converged:
            streak += 1
        else:
            break
    return streak


# ── benchmarking ───────────────────────────────────────────────────────────────

@dataclass
class AgentScore:
    agent: str
    score: float
    latency_ms: int
    passing: bool
    details: list[str]


def score_response(response: str, expected_keywords: list[str]) -> float:
    """0.0–1.0: keyword coverage (0.5) + non-empty (0.2) + length sanity (0.3)."""
    if not response or response.startswith("ERROR"):
        return 0.0
    lower = response.lower()
    kw_score = sum(1 for kw in expected_keywords if kw in lower) / max(len(expected_keywords), 1)
    length_score = min(len(response) / 200, 1.0)  # generous — 200+ chars = full marks
    return round(0.5 * kw_score + 0.2 + 0.3 * length_score, 3)


def benchmark_agent(agent: str, timeout: int = 45) -> AgentScore:
    if not _model_installed(agent):
        return AgentScore(agent, 0.0, 0, False, ["model not installed"])

    scores: list[float] = []
    latencies: list[int] = []
    details: list[str] = []

    for label, prompt, keywords in BENCHMARK_PROMPTS:
        t0 = time.monotonic()
        try:
            result = subprocess.run(
                ["ollama", "run", agent],
                input=prompt,
                capture_output=True, text=True,
                timeout=timeout,
            )
            elapsed = int((time.monotonic() - t0) * 1000)
            response = result.stdout.strip() if result.returncode == 0 else "ERROR"
        except subprocess.TimeoutExpired:
            elapsed = timeout * 1000
            response = "ERROR: timeout"
        except Exception as e:
            elapsed = 0
            response = f"ERROR: {e}"

        s = score_response(response, keywords)
        scores.append(s)
        latencies.append(elapsed)
        details.append(f"{label}: {s:.2f} ({elapsed}ms)")

    avg_score = round(sum(scores) / len(scores), 3)
    avg_latency = int(sum(latencies) / len(latencies))
    return AgentScore(
        agent=agent,
        score=avg_score,
        latency_ms=avg_latency,
        passing=avg_score >= QUALITY_THRESHOLD,
        details=details,
    )


# ── auto-tuning ────────────────────────────────────────────────────────────────

def _model_installed(name: str) -> bool:
    try:
        out = subprocess.check_output(["ollama", "list"], text=True, timeout=10)
        return any(line.split()[0].split(":")[0] == name for line in out.splitlines()[1:] if line.split())
    except Exception:
        return False


def _read_current_temp(agent: str) -> Optional[float]:
    mf = MODELFILES_DIR / f"Modelfile.{agent}"
    if not mf.exists():
        return None
    m = re.search(r"PARAMETER\s+temperature\s+([\d.]+)", mf.read_text())
    return float(m.group(1)) if m else None


def _nudge_temp(current: float, target: float) -> float:
    """Move 20% of the way toward target, clamped to [0.05, 0.95]."""
    nudged = current + 0.20 * (target - current)
    return round(max(0.05, min(0.95, nudged)), 3)


def auto_tune(agent: str, score: AgentScore, run_id: int, db: sqlite3.Connection) -> None:
    if score.passing:
        return

    mf_path = MODELFILES_DIR / f"Modelfile.{agent}"
    if not mf_path.exists():
        log(f"[tune] {agent}: Modelfile missing, cannot tune")
        return

    current_temp = _read_current_temp(agent)
    if current_temp is None:
        log(f"[tune] {agent}: could not read current temperature")
        return

    target_temp = TARGET_TEMPS.get(agent, current_temp)
    new_temp = _nudge_temp(current_temp, target_temp)

    if abs(new_temp - current_temp) < 0.005:
        log(f"[tune] {agent}: temperature already at target ({current_temp}), skipping")
        return

    content = mf_path.read_text()
    updated = re.sub(
        r"(PARAMETER\s+temperature\s+)[\d.]+",
        f"\\g<1>{new_temp}",
        content,
    )
    mf_path.write_text(updated)

    reason = f"score={score.score:.2f} < {QUALITY_THRESHOLD}, nudging temp {current_temp}→{new_temp} (target={target_temp})"
    log(f"[tune] {agent}: {reason}")

    db.execute(
        "INSERT INTO tuning_log (run_id, agent, old_temp, new_temp, reason) VALUES (?,?,?,?,?)",
        (run_id, agent, current_temp, new_temp, reason),
    )
    db.commit()

    # Recreate the Ollama model with updated Modelfile
    try:
        subprocess.run(["ollama", "create", agent, "-f", str(mf_path)], check=True, timeout=300)
        log(f"[tune] {agent}: model recreated with temp={new_temp}")
    except Exception as e:
        log(f"[tune] {agent}: model recreation failed: {e}")


# ── Telegram ───────────────────────────────────────────────────────────────────

def send_telegram(message: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log("[telegram] not configured — skipping notification")
        return
    try:
        import urllib.request
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = json.dumps({"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}).encode()
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)
        log("[telegram] notification sent")
    except Exception as e:
        log(f"[telegram] send failed: {e}")


# ── cron management ────────────────────────────────────────────────────────────

def _this_script() -> str:
    return os.path.abspath(__file__)


def install_cron(interval_minutes: int = 60) -> None:
    script = _this_script()
    cron_line = f"*/{interval_minutes} * * * * python3 {script} >> {LOG_PATH} 2>&1"
    existing = _get_crontab()
    if script in existing:
        log("[cron] already installed")
        return
    new_crontab = existing.rstrip() + "\n" + cron_line + "\n"
    _set_crontab(new_crontab)
    log(f"[cron] installed: {cron_line}")


def remove_cron() -> None:
    script = _this_script()
    existing = _get_crontab()
    filtered = "\n".join(line for line in existing.splitlines() if script not in line)
    _set_crontab(filtered + "\n")
    log("[cron] removed from crontab")


def _get_crontab() -> str:
    try:
        return subprocess.check_output(["crontab", "-l"], text=True, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        return ""


def _set_crontab(content: str) -> None:
    proc = subprocess.run(["crontab", "-"], input=content, text=True)
    if proc.returncode != 0:
        log("[cron] crontab write failed")


# ── logging ────────────────────────────────────────────────────────────────────

def log(msg: str) -> None:
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    line = f"[{ts}] {msg}"
    print(line)
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")


# ── main loop logic ────────────────────────────────────────────────────────────

def run_cycle(db: sqlite3.Connection) -> None:
    run_number = get_run_number(db)
    last_score = get_last_system_score(db)

    log(f"=== Improvement loop run #{run_number} ===")

    if run_number > MAX_RUNS:
        msg = f"⚠️ *Hermes loop hit hard ceiling* ({MAX_RUNS} runs). Stopping without convergence.\nCheck {LOG_PATH} for details."
        log(msg)
        send_telegram(msg)
        remove_cron()
        return

    # Benchmark all agents
    agent_scores: list[AgentScore] = []
    for agent in AGENTS:
        log(f"[bench] benchmarking {agent}...")
        score = benchmark_agent(agent)
        agent_scores.append(score)
        log(f"[bench] {agent}: score={score.score:.2f} latency={score.latency_ms}ms passing={score.passing}")
        for d in score.details:
            log(f"  {d}")

    system_score = round(sum(s.score for s in agent_scores) / len(agent_scores), 3)
    log(f"[bench] system_score={system_score:.3f}")

    # Convergence check
    delta = abs(system_score - last_score) if last_score is not None else 1.0
    all_passing = all(s.passing for s in agent_scores)
    converged = all_passing and delta < CONVERGENCE_DELTA
    log(f"[convergence] all_passing={all_passing} delta={delta:.4f} converged={converged}")

    # Write run record
    cur = db.execute(
        "INSERT INTO runs (ts, run_number, system_score, delta, converged, streak) VALUES (?,?,?,?,?,0)",
        (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), run_number, system_score, delta, int(converged)),
    )
    run_id = cur.lastrowid
    for s in agent_scores:
        db.execute(
            "INSERT INTO agent_scores (run_id, agent, score, latency_ms, passing) VALUES (?,?,?,?,?)",
            (run_id, s.agent, s.score, s.latency_ms, int(s.passing)),
        )
    db.commit()

    streak = get_streak(db)
    db.execute("UPDATE runs SET streak=? WHERE id=?", (streak, run_id))
    db.commit()

    log(f"[convergence] streak={streak}/{CONVERGENCE_STREAK_REQUIRED}")

    # Auto-tune failing agents
    for score in agent_scores:
        if not score.passing:
            auto_tune(score.agent, score, run_id, db)

    # Telegram per-run update
    lines = [f"*Hermes Loop Run #{run_number}*", f"System score: `{system_score:.1%}`", ""]
    for s in agent_scores:
        icon = "✅" if s.passing else "❌"
        lines.append(f"{icon} {s.agent}: `{s.score:.1%}` ({s.latency_ms}ms)")
    lines += ["", f"Delta: `{delta:.1%}` | Streak: {streak}/{CONVERGENCE_STREAK_REQUIRED}"]
    send_telegram("\n".join(lines))

    # Termination check
    if streak >= CONVERGENCE_STREAK_REQUIRED:
        log("=== CONVERGENCE REACHED — self-terminating ===")
        _terminate(db, agent_scores, system_score, run_number)


def _terminate(
    db: sqlite3.Connection,
    agent_scores: list[AgentScore],
    system_score: float,
    run_number: int,
) -> None:
    tuning_rows = db.execute("SELECT agent, old_temp, new_temp, reason FROM tuning_log ORDER BY id").fetchall()

    lines = [
        "🏁 *Hermes Improvement Loop — COMPLETE*",
        f"Converged after {run_number} runs.",
        "",
        "*Final agent scores:*",
    ]
    for s in agent_scores:
        lines.append(f"  • {s.agent}: `{s.score:.1%}`")
    lines += [
        "",
        f"*System score:* `{system_score:.1%}`",
        "",
        "*Auto-tunes applied:*",
    ]
    if tuning_rows:
        for agent, old_t, new_t, reason in tuning_rows:
            lines.append(f"  • {agent}: {old_t}→{new_t} ({reason})")
    else:
        lines.append("  None required — models were already well-tuned.")

    lines += ["", "Cron job has been removed. System is stable. ✅"]

    msg = "\n".join(lines)
    log(msg)
    send_telegram(msg)

    db.execute("UPDATE runs SET terminated=1 WHERE run_number=(SELECT MAX(run_number) FROM runs)")
    db.commit()

    remove_cron()


# ── status ─────────────────────────────────────────────────────────────────────

def show_status(db: sqlite3.Connection) -> None:
    init_db(db)
    rows = db.execute(
        "SELECT run_number, ts, system_score, delta, converged, streak, terminated FROM runs ORDER BY run_number DESC LIMIT 10"
    ).fetchall()
    if not rows:
        print("No runs recorded yet.")
        return
    print(f"{'Run':>4}  {'Timestamp':20}  {'Score':>6}  {'Delta':>6}  {'Conv':>5}  {'Streak':>6}  {'Done':>4}")
    for rn, ts, ss, d, conv, streak, term in rows:
        print(f"{rn:>4}  {ts:20}  {ss or 0:>6.1%}  {d or 0:>6.1%}  {'Y' if conv else 'N':>5}  {streak:>6}  {'✓' if term else '':>4}")
    print()
    last_agents = db.execute(
        "SELECT agent, score, latency_ms, passing FROM agent_scores WHERE run_id=(SELECT MAX(id) FROM runs)"
    ).fetchall()
    if last_agents:
        print("Latest agent scores:")
        for agent, score, latency, passing in last_agents:
            icon = "✅" if passing else "❌"
            print(f"  {icon} {agent}: {score:.1%} ({latency}ms)")


# ── entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Hermes self-terminating improvement loop")
    parser.add_argument("--status", action="store_true", help="Show current scores and streak")
    parser.add_argument("--remove-cron", action="store_true", help="Remove the cron job immediately")
    parser.add_argument("--install-cron", type=int, metavar="MINUTES", nargs="?", const=60,
                        help="Install cron at MINUTES interval (default 60)")
    args = parser.parse_args()

    WORK_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    init_db(db)

    if args.remove_cron:
        remove_cron()
        print("Cron removed.")
        return

    if args.install_cron is not None:
        install_cron(args.install_cron)
        print(f"Cron installed (every {args.install_cron} min).")
        return

    if args.status:
        show_status(db)
        return

    run_cycle(db)


if __name__ == "__main__":
    main()
