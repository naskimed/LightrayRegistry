"""MATLAB (geometry) bridge — files only, inbox-only submission (TECH_SPEC §7.1).

Outbound: export_job() writes blocks/<id>/job.json — job_hash, task, input refs+digests, the
EMBEDDED precommit body (the registry owns constants; precommit.m is GENERATED), spend
authorization, seeds. The daemon dispatches `matlab -batch "registry_job('<job.json>')"`.

Inbound: ingest_result() consumes inbox result.json — verifies the job_hash echo, computes
physical hashes (MATLAB never hashes), diffs the PC-ECHO against the registered constants
(the one drift class we have actually observed — machine-caught, not review-caught), and
emits trials.* / artifact.* event drafts.

Determinism at ingestion: cheap jobs run twice byte-identical; expensive jobs spot-rerun one
config (the dispatcher's job kind decides which policy applies).
"""
from __future__ import annotations

import json
from pathlib import Path

from .. import config
from ..canon import sha256_canon, sha256_file
from ..schemas.envelope import EventDraft, make_event_id
from ..store import inbox_submit, write_json_atomic

ACTOR = "loop:geometry"


# ---- outbound: the job contract ------------------------------------------------------------
def export_job(block: dict, pc_doc: dict, task: str, inputs: dict, seeds: list[int],
               spend_authorization: dict | None = None, w: Path | None = None) -> Path:
    """Write the frozen job contract the MATLAB shim (registry_job.m) consumes."""
    job = {
        "task": task,                                   # rescore | census | tierB_search | ...
        "block_id": block["block_id"],
        "inputs": inputs,                               # {name: {path, sha256|content_digest}}
        "precommit": pc_doc,                            # EMBEDDED body — precommit.m is generated
        "precommit_hash": sha256_canon(pc_doc.get("entries", [])),
        "seeds": seeds,
        "spend_authorization": spend_authorization,     # None for IS work
        "key_scheme_version": block.get("key_scheme_version", "v1"),
        "index_base": 0,
        "emission_spec": "silent_v1",                   # readout/rehearsal jobs must emit nothing
    }
    job["job_hash"] = sha256_canon(job)
    d = config.jobs_dir(w) / block["block_id"]
    d.mkdir(parents=True, exist_ok=True)
    write_json_atomic(d / "job.json", job)
    return d / "job.json"


# ---- inbound: the result contract -----------------------------------------------------------
def ingest_result(result_path: str | Path, registered_pc_entries_hash: str | None,
                  w: Path | None = None) -> list[Path]:
    """Convert a MATLAB result.json into event drafts submitted via the inbox. Returns the
    submitted draft paths. Raises on job-hash mismatch (the file is quarantined by the caller)."""
    result = json.loads(Path(result_path).read_text())
    job_hash = result.get("job_hash_echo")
    if not job_hash:
        raise ValueError("result.json carries no job_hash echo")

    drafts: list[Path] = []
    # PC-ECHO: the PC struct actually threaded through the computation, canonicalized+hashed
    pc_echo = result.get("pc_echo")
    # register .mat files as declared-lossable engine cache; result JSON is the durable record
    for art in result.get("artifacts", []):
        payload = {
            "artifact_id": f"art_{sha256_file(art['path'])[:12]}" if Path(art["path"]).exists()
                           else f"art_missing_{art['name']}",
            "role": art.get("role", "engine_cache"),
            "path": art["path"],
            "declared_sha256": art.get("sha256"),
            "provenance": {"engine": "matlab_sgl", "job_hash": job_hash},
        }
        drafts.append(_submit("artifact.register", payload, intent=f"{job_hash}:{art['name']}", w=w))

    for batch in result.get("trial_batches", []):
        payload = {
            "batch_id": batch["batch_id"], "block_id": result["block_id"],
            "n_rows": batch["n_rows"], "n_distinct_keys": batch["n_distinct_keys"],
            "rows_file": batch["rows_file"], "null_max_file": batch.get("null_max_file"),
            "gate_ref_q95": batch.get("gate_ref_q95"), "dataset_ref": batch["dataset_ref"],
            "engine_stamp": result.get("engine_stamp", {}),
            "null_spec_hash": batch.get("null_spec_hash"),
            "pc_echo": pc_echo,
            "env_hash": result.get("env_hash"),
        }
        drafts.append(_submit("trials.record", payload, intent=f"{job_hash}:{batch['batch_id']}", w=w))

    if result.get("five_clause"):
        for clause, verdict in result["five_clause"].items():
            payload = {"candidate_id": result["candidate_id"],
                       "lineage_id": result["lineage_id"], "clause": clause,
                       "stamp": "measured_pass" if verdict else "measured_fail",
                       "evidence_ref": result.get("evidence_ref")}
            drafts.append(_submit("cert.clause_stamp", payload,
                                  intent=f"{job_hash}:{clause}", w=w))
    return drafts


def _submit(type_: str, payload: dict, intent: str, w: Path | None) -> Path:
    draft = EventDraft(
        event_id=make_event_id(type_, ACTOR, payload, intent=intent),
        type=type_, actor=ACTOR, provenance="scheduled", payload=payload)
    return inbox_submit(config.inbox_staging(w), config.inbox_pending(w),
                        draft.event_id, draft.model_dump(mode="json"))


# ---- the generated precommit ---------------------------------------------------------------
def generate_precommit_m(pc_doc: dict) -> str:
    """Render precommit_generated.m from the registered constants doc. After cutover the
    original precommit.m is a tombstone erroring 'constants live in the registry'."""
    lines = ["function PC = precommit_generated()",
             "% GENERATED from the registry constants doc "
             f"{pc_doc.get('doc_id')} — DO NOT EDIT (PC-echo will catch drift)"]
    for e in pc_doc.get("entries", []):
        k, v = e["key"], e.get("value")
        if isinstance(v, str):
            lines.append(f"PC.{k} = '{v}';")
        elif isinstance(v, bool):
            lines.append(f"PC.{k} = {str(v).lower()};")
        elif isinstance(v, list):
            lines.append(f"PC.{k} = [{' '.join(str(x) for x in v)}];")
        elif v is not None:
            lines.append(f"PC.{k} = {v};")
    lines.append("end")
    return "\n".join(lines) + "\n"
