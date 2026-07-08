"""Agent sessions (AGENT_CONTRACTS AC-1.0 §5) — headless Claude Code, daemon-spawned.

Invocation:  claude --bare -p <task>
               --append-system-prompt-file roles/<role>.md
               --allowedTools <role grant> --permission-mode dontAsk
               --output-format stream-json --verbose --include-partial-messages
               [--mcp-config mcp/matlab.json   (OPERATOR ONLY)]

--bare: the session inherits NOTHING ambient (no hooks/skills/CLAUDE.md discovery) — the
registry's explicit-everything doctrine enforced by the CLI itself. Auth comes from
ANTHROPIC_API_KEY in the daemon's environment.

Decision 7(a) — observer-produced evidence: the DAEMON reads the stream-json pipe (tool calls
+ token usage arrive on OUR side); the agent-writable transcript dir is never trusted. The
capture bundle is hashed and registered as artifact.register(role: session_capture) —
scheduler-mechanical (REG-INV-25). The nightly audit scans bundles against the versioned
audit-rule constants (R15: boundary + shadow).
"""
from __future__ import annotations

import json
import subprocess
import threading
import time
from pathlib import Path

from .. import config
from ..canon import sha256_file
from ..schemas.envelope import ACTOR_SCHEDULER, EventDraft, make_event_id

ROLES_DIR = Path(__file__).resolve().parent.parent.parent / "roles"
MCP_DIR = Path(__file__).resolve().parent.parent.parent / "mcp"

ROLE_TOOLS = {
    # boundary/shadow: Read + the reg CLI + local GETs — NO engine tools, NO MCP (R14)
    "boundary": "Read,Bash(reg *),Bash(curl -s http://127.0.0.1:8377/*)",
    "shadow":   "Read,Bash(reg *),Bash(curl -s http://127.0.0.1:8377/*)",
    # operator: ops bash + the MATLAB MCP (diagnostics only — never the production job path)
    "operator": "Read,Bash(reg *),Bash(systemctl status *),Bash(journalctl *),mcp__matlab__*",
}

ROLE_TASKS = {
    "boundary": ("Read the latest cards (GET /state, /cards) and the ledger queries you need; "
                 "propose the next registrations/blocks as event drafts written to the inbox. "
                 "Cite the kill-check. Respect diagnostic mode."),
    "shadow":   ("Read the same cards the scorer consumed for the current handoff queue and "
                 "emit exactly one shadow_ranking event draft to the inbox. Rank, hypothesize "
                 "divergences, change nothing."),
    "operator": ("Diagnose the incident named in the reason line: read engine diaries via the "
                 "MATLAB MCP, check license/health, rerun ONE named config if needed, then file "
                 "a note.record incident event draft to the inbox."),
}


class AgentRunner:
    """Spawns one session per fire(); serializes per-role (no two boundary sessions overlap)."""

    def __init__(self, claude_bin: str = "claude", model: str | None = None,
                 prompt_version: str = "agent_prompt_v0", model_version: str | None = None,
                 session_timeout: float = 1800.0):
        self.claude_bin = claude_bin
        self.session_timeout = session_timeout
        self.model = model
        self.prompt_version = prompt_version      # stamped on agent events (R13)
        self.model_version = model_version or (model or "session-default")
        self._locks = {r: threading.Lock() for r in ROLE_TASKS}

    def fire(self, role: str, reason: str, writer) -> None:
        if role not in ROLE_TASKS:
            return
        t = threading.Thread(target=self._run, args=(role, reason, writer),
                             name=f"agent-{role}", daemon=True)
        t.start()

    # ---- one session lifecycle -----------------------------------------------------------
    def _run(self, role: str, reason: str, writer) -> None:
        lock = self._locks[role]
        if not lock.acquire(blocking=False):
            return                                 # a session of this role is already live
        try:
            session_id = f"{role}_{int(time.time())}"
            sdir = config.sessions_dir() / session_id
            sdir.mkdir(parents=True, exist_ok=True)
            cmd = [
                self.claude_bin, "--bare", "-p",
                f"[{role} session — reason: {reason}]\n{ROLE_TASKS[role]}",
                "--append-system-prompt-file", str(ROLES_DIR / f"{role}.md"),
                "--allowedTools", ROLE_TOOLS[role],
                "--permission-mode", "dontAsk",
                "--output-format", "stream-json", "--verbose", "--include-partial-messages",
            ]
            if role == "operator":
                cmd += ["--mcp-config", str(MCP_DIR / "matlab.json")]
            if self.model:
                cmd += ["--model", self.model]

            capture = sdir / "stream.jsonl"
            usage = {"tool_calls": 0, "cost_usd": None}
            with open(capture, "w") as out:
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, text=True)
                # hard watchdog: a hung claude process is killed so the role is never starved
                watchdog = threading.Timer(self.session_timeout, proc.kill)
                watchdog.start()
                try:
                    for line in proc.stdout:                 # OUR side of the pipe (7a)
                        out.write(line)
                        self._meter(line, usage)
                    proc.wait(timeout=30)
                finally:
                    watchdog.cancel()

            (sdir / "meta.json").write_text(json.dumps({
                "role": role, "reason": reason, "returncode": proc.returncode,
                "usage": usage, "prompt_version": self.prompt_version,
                "model_version": self.model_version}))
            self._register_capture(writer, session_id, capture, role)
        except Exception:
            pass                                            # a dead session must not kill the daemon
        finally:
            lock.release()

    def _meter(self, line: str, usage: dict) -> None:
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            return
        if d.get("type") == "assistant":
            for blk in (d.get("message", {}).get("content") or []):
                if isinstance(blk, dict) and blk.get("type") == "tool_use":
                    usage["tool_calls"] += 1
        if d.get("type") == "result":
            usage["cost_usd"] = d.get("total_cost_usd")     # the api_token_budget meter

    def _register_capture(self, writer, session_id: str, capture: Path, role: str) -> None:
        """artifact.register(role: session_capture) — scheduler-mechanical (REG-INV-25)."""
        digest = sha256_file(capture)
        payload = {
            "artifact_id": f"art_{digest[:12]}",
            "role": "session_capture",
            "path": str(capture),
            "declared_sha256": digest,
            "provenance": {"session_id": session_id, "agent_role": role,
                           "prompt_version": self.prompt_version,
                           "model_version": self.model_version},
        }
        draft = EventDraft(
            event_id=make_event_id("artifact.register", ACTOR_SCHEDULER, payload,
                                   intent=session_id),
            type="artifact.register", actor=ACTOR_SCHEDULER, provenance="scheduled",
            payload=payload,
            agent_prompt_version=self.prompt_version,
            agent_model_version=self.model_version)
        writer.submit(draft)
