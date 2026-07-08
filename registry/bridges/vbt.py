"""vectorbt (population) bridge (TECH_SPEC §7.2).

Block kind population_vbt: the job pins the strategy family/param grid, snapshot digest, the
EXPLICIT fill model (intrabar_ordering, entry_ref, fee_bps, size), kill gates + null spec, and
gates_required=["mutation_audit"].

The runner contract (the engine itself lives on the engine host — /workspace/lightray or the
current server tree): run(spec) → trades_df with indicators/signals computed inside the SAME
materialize() the mutation audit consumes (single definition), then the audit as a HARD gate
(REG-INV-20: no audit ⇒ the barrier rejects usable status), then population parquet + manifest
+ result.json with kill-gate stats and the env hash.
"""
from __future__ import annotations

import json
import platform
import subprocess
import sys
from pathlib import Path

from .. import config
from ..canon import content_digest_v1, sha256_canon, sha256_file
from ..schemas.envelope import EventDraft, make_event_id
from ..store import inbox_submit, write_json_atomic

ACTOR = "loop:population"

POPULATION_COLUMNS = [
    "trade_id", "side", "entry_ts", "exit_ts", "entry_price", "exit_price", "volume",
    "profit", "exit_reason", "f_hour", "f_ema", "f_mom", "f_dv", "f_iv", "f_hurst",
    "incumbent_cluster_id", "legacy_row_index", "mt5_deal_in", "mt5_deal_out",
]
POPULATION_DTYPES = {
    "trade_id": "string", "side": "string", "entry_ts": "timestamp_us",
    "exit_ts": "timestamp_us", "entry_price": "float64", "exit_price": "float64",
    "volume": "float64", "profit": "float64", "exit_reason": "string",
    "f_hour": "float64", "f_ema": "float64", "f_mom": "float64", "f_dv": "float64",
    "f_iv": "float64", "f_hurst": "float64", "incumbent_cluster_id": "int64",
    "legacy_row_index": "int64", "mt5_deal_in": "int64", "mt5_deal_out": "int64",
}


def env_hash() -> str:
    """sha256 of SORTED pip freeze + python version + platform/BLAS tuple (R10)."""
    freeze = subprocess.run([sys.executable, "-m", "pip", "freeze"],
                            capture_output=True, text=True).stdout
    return sha256_canon({"freeze": sorted(freeze.splitlines()),
                         "python": sys.version, "platform": platform.platform()})


def export_job(block: dict, snapshot: dict, w: Path | None = None) -> Path:
    job = {
        "task": "population_vbt",
        "block_id": block["block_id"],
        "snapshot": {"path": snapshot["path"], "content_digest": snapshot.get("canonical_content_digest")},
        "fill_model": block.get("fill_model"),          # PINNED: intrabar_ordering, entry_ref, fee_bps, size
        "grid": block.get("grid"),
        "kill_gates": block.get("kill_gates"),
        "null_spec": block.get("null_spec"),
        "gates_required": block.get("gates_required", ["mutation_audit"]),
        "featureset_hash": block["featureset_hash"],
    }
    job["job_hash"] = sha256_canon(job)
    d = config.jobs_dir(w) / block["block_id"]
    d.mkdir(parents=True, exist_ok=True)
    write_json_atomic(d / "job.json", job)
    return d / "job.json"


def population_manifest(trades_rows: list[dict], snapshot_ref: str, featureset_hash: str,
                        strategy_config_hash: str, engine: dict, clock: str,
                        truncations_explained: dict | None = None) -> dict:
    """The frozen-matrix manifest (B2). Canonical matrix stores RAW features; standardization
    stays engine-side, train-only. Stamps are additive files, event-logged."""
    digest = content_digest_v1(trades_rows, POPULATION_COLUMNS, POPULATION_DTYPES,
                               sort_key=["entry_ts", "trade_id"])
    return {
        "snapshot_ref": snapshot_ref,
        "featureset_hash": featureset_hash,
        "strategy_config_hash": strategy_config_hash,
        "engine": engine,                                # {name, version, git}
        "n_trades": len(trades_rows),
        "truncations_explained": truncations_explained or {},
        "clock": clock,                                  # "utc" | "mt5_server_eet_dst"
        "content_digest": digest,
        "digest_scheme_version": "digest_v1",
    }


def ingest_result(result_path: str | Path, w: Path | None = None) -> list[Path]:
    """result.json → event drafts. The mutation-audit stamp is the GATE: without a passing
    stamp the population never reaches usable status (REG-INV-20 barrier law)."""
    result = json.loads(Path(result_path).read_text())
    drafts: list[Path] = []
    pop_path = result["population_parquet"]
    art_id = f"art_{sha256_file(pop_path)[:12]}"
    drafts.append(_submit("artifact.register", {
        "artifact_id": art_id, "role": "population", "path": pop_path,
        "declared_sha256": sha256_file(pop_path),
        "content_digest": result.get("content_digest"),
        "digest_scheme_version": "digest_v1",
        "provenance": {"engine": "vbt", "job_hash": result.get("job_hash_echo"),
                       "env_hash": result.get("env_hash"),
                       "causality_class": result.get("causality_class", "audited")},
    }, intent=f"pop:{art_id}", w=w))

    audit = result.get("mutation_audit", {})
    drafts.append(_submit("artifact.stamp", {
        "artifact_id": art_id, "stamp_kind": "mutation_audit",
        "passed": bool(audit.get("passed")),
        "detail": {"positive_control_caught": audit.get("positive_control_caught"),
                   "leaks_found": audit.get("leaks_found"),
                   "cut_fracs": audit.get("cut_fracs")},
    }, intent=f"audit:{art_id}", w=w))
    return drafts


def _submit(type_: str, payload: dict, intent: str, w: Path | None) -> Path:
    draft = EventDraft(
        event_id=make_event_id(type_, ACTOR, payload, intent=intent),
        type=type_, actor=ACTOR, provenance="scheduled", payload=payload)
    return inbox_submit(config.inbox_staging(w), config.inbox_pending(w),
                        draft.event_id, draft.model_dump(mode="json"))
