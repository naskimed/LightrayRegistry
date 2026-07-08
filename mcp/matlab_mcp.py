#!/usr/bin/env python3
"""MATLAB MCP server (AGENT_CONTRACTS §6) — thin stdio wrapper around `matlab -batch`.

OPERATOR-ONLY (granted via --allowedTools "mcp__matlab__*" in the operator session; the
boundary/shadow never receive this config). Diagnostics only — NEVER the production job path.

Scope locks:
- run_named_function executes REGISTERED function names only (the allowlist below), never
  arbitrary code;
- file reads are scoped to the BelkaSGL tree ($BELKASGL_TREE).

Protocol: MCP over stdio (JSON-RPC 2.0, newline-delimited) — initialize, tools/list,
tools/call. Dependency-free on purpose.

Env: MATLAB_BIN (default "matlab"), BELKASGL_TREE (required), MCP_TIMEOUT handled by the
client; matlab -batch cold start is slow — the daemon pre-warms or raises the client timeout.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

MATLAB_BIN = os.environ.get("MATLAB_BIN", "matlab")
_tree_env = os.environ.get("BELKASGL_TREE", "").strip()
if not _tree_env or not Path(_tree_env).is_dir():
    sys.stderr.write("matlab_mcp: BELKASGL_TREE must be set to an existing directory — refusing "
                     "to start (tree-scoping would silently degrade to CWD)\n")
    sys.exit(2)
TREE = Path(_tree_env).resolve()

# The named-function allowlist — finalize with the MATLAB install (MD-1.0 §6 open item).
ALLOWED_FUNCTIONS = {
    "registry_smoke",        # the M5 environment fixture
    "read_belka_config",     # config reads (diagnostic)
    "rescore_run",           # single-config rescore (isolate a fault)
    "param_hash",            # KEY/seed recomputation
    "verify_population_parity",
}

TOOLS = [
    {"name": "run_named_function",
     "description": "Run ONE registered BelkaSGL function via matlab -batch (diagnostic only). "
                    f"Allowed: {sorted(ALLOWED_FUNCTIONS)}. Args are a typed list (numbers or "
                    "strings) rendered as MATLAB literals — NO expressions, NO code injection.",
     "inputSchema": {"type": "object", "required": ["function"],
                     "properties": {"function": {"type": "string"},
                                    "args": {"type": "array",
                                             "items": {"type": ["number", "string"]},
                                             "description": "positional args; strings are quoted"}}}},
    {"name": "read_diary",
     "description": "Read a log/diary file inside the BelkaSGL tree (tail by default).",
     "inputSchema": {"type": "object", "required": ["relpath"],
                     "properties": {"relpath": {"type": "string"},
                                    "tail_lines": {"type": "integer", "default": 200}}}},
    {"name": "read_output",
     "description": "List or stat files under the BelkaSGL output/ directory.",
     "inputSchema": {"type": "object",
                     "properties": {"glob": {"type": "string", "default": "output/*"}}}},
    {"name": "license_health",
     "description": "Check MATLAB starts headless and required toolbox licenses answer.",
     "inputSchema": {"type": "object", "properties": {}}},
]


def _inside_tree(rel: str) -> Path:
    p = (TREE / rel).resolve()
    if not p.is_relative_to(TREE):        # true containment — not a startswith prefix (sibling escape)
        raise PermissionError(f"path escapes the BelkaSGL tree: {rel}")
    return p


def _matlab_literal(v) -> str:
    """Render a JSON scalar as a safe MATLAB literal. Strings are single-quoted with internal
    quotes doubled (MATLAB escaping) — no way to break out into an expression."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return "'" + v.replace("'", "''") + "'"
    raise ValueError(f"unsupported arg type: {type(v).__name__}")


def _matlab(code: str, timeout: int = 900) -> dict:
    proc = subprocess.run([MATLAB_BIN, "-batch", code], capture_output=True,
                          text=True, timeout=timeout, cwd=TREE if TREE.exists() else None)
    return {"exit_code": proc.returncode,
            "stdout": proc.stdout[-20000:], "stderr": proc.stderr[-5000:]}


def call_tool(name: str, args: dict) -> dict:
    if name == "run_named_function":
        fn = args["function"]
        if fn not in ALLOWED_FUNCTIONS:
            return {"error": f"{fn} is not a registered diagnostic function "
                             f"(allowed: {sorted(ALLOWED_FUNCTIONS)})"}
        try:
            rendered = ", ".join(_matlab_literal(a) for a in (args.get("args") or []))
        except ValueError as e:
            return {"error": str(e)}
        return _matlab(f"{fn}({rendered})" if rendered else fn)
    if name == "read_diary":
        p = _inside_tree(args["relpath"])
        lines = p.read_text(errors="replace").splitlines()
        n = int(args.get("tail_lines", 200))
        return {"path": str(p), "tail": "\n".join(lines[-n:])}
    if name == "read_output":
        import glob as g
        pattern = str(_inside_tree(args.get("glob", "output/*")))
        entries = []
        for f in sorted(g.glob(pattern))[:200]:
            st = os.stat(f)
            entries.append({"path": f, "bytes": st.st_size, "mtime": st.st_mtime})
        return {"entries": entries}
    if name == "license_health":
        return _matlab(
            "disp(version); "
            "fprintf('stats=%d parallel=%d\\n', "
            "license('test','Statistics_Toolbox'), license('test','Distrib_Computing_Toolbox'))",
            timeout=300)
    return {"error": f"unknown tool {name}"}


# ---- minimal MCP/JSON-RPC loop ----------------------------------------------------------------
def main() -> None:
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            req = json.loads(raw)
        except json.JSONDecodeError:
            continue
        rid = req.get("id")
        method = req.get("method")
        if method == "initialize":
            result = {"protocolVersion": req.get("params", {}).get("protocolVersion", "2024-11-05"),
                      "capabilities": {"tools": {}},
                      "serverInfo": {"name": "matlab", "version": "0.1.0"}}
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            params = req.get("params", {})
            try:
                out = call_tool(params.get("name", ""), params.get("arguments", {}) or {})
            except Exception as e:
                out = {"error": str(e)}
            result = {"content": [{"type": "text", "text": json.dumps(out, indent=1)}],
                      "isError": "error" in out}
        elif method in ("notifications/initialized", "ping"):
            if rid is None:
                continue
            result = {}
        else:
            if rid is None:
                continue
            _reply(rid, error={"code": -32601, "message": f"unknown method {method}"})
            continue
        if rid is not None:
            _reply(rid, result=result)


def _reply(rid, result=None, error=None) -> None:
    msg = {"jsonrpc": "2.0", "id": rid}
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
