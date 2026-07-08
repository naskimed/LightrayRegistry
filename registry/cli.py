"""`reg` — the human/CLI face of the registry (M2).

Commands:
  reg verify                       walk the hash chain (exact first-bad seq)
  reg state [--json]               replay → summary or full state dump
  reg append <draft.json>          submit an event draft through ingest+barrier+append
                                   (single-user mode: takes the same flock as the daemon)
  reg query <what> [args]          golden-answer queries (incumbent? spent? budget? ...)
  reg snapshot                     write derived projections (disposable caches)
  reg render                       cold-render LEDGER.md from the log
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import config
from .barrier import decide
from .daemon.lock import registry_flock
from .ledger import Ledger, verify
from .reducer import fold, replay
from .render import render_ledger
from .schemas.envelope import EventDraft
from .export import export_all, spend_view
from .ingest import enrich


def _load_state(writable: bool = False):
    lg = Ledger(writable=writable)
    return replay(lg.iter_events()), lg


def cmd_verify(_args) -> int:
    r = verify()
    if r.ok:
        print(f"OK · {r.n_events} events · head {r.head_hash[:16]}")
        return 0
    print(f"FAIL at seq {r.first_bad_seq}: {r.reason}")
    return 1


def cmd_state(args) -> int:
    state, _ = _load_state()
    if args.json:
        d = state.model_dump(mode="json")
        d["dedup"] = sorted(state.dedup)
        print(json.dumps(d, indent=1, default=str))
    else:
        print(f"as_of_seq={state.as_of_seq} head={state.head_hash[:16]}")
        print(f"blocks={len(state.blocks)} scorecards={len(state.scorecards)} "
              f"cards={len(state.cards)} readouts={len(state.readouts)}")
        for lin, v in state.lineages.items():
            b = v.get("budget") or {}
            print(f"lineage {lin}: k={v.get('k_cumulative', 0)} remaining={b.get('remaining')}")
        print(f"open_cycle={state.open_cycle} "
              f"suspended={bool(state.suspensions.get('readout_conditional_channel'))}")
    return 0


def cmd_append(args) -> int:
    """Single-user append path (M2–M3, before the daemon exists). Takes the SAME flock the
    daemon takes, so the two can never write concurrently."""
    draft_raw = json.loads(Path(args.draft).read_text())
    with registry_flock():
        state, lg = _load_state(writable=True)   # holds the flock → may quarantine a torn tail
        draft = EventDraft.model_validate(draft_raw)
        draft = enrich(draft)
        d = decide(state, draft)
        if not d.accepted:
            print(f"REJECTED [{d.code}] {d.reason}")
            return 2
        if d.dedup_noop:
            print("NOOP (event_id already applied)")
            return 0
        ev = lg.append(draft)
        fold(state, ev)
        print(f"ACCEPTED seq={ev.seq} hash={ev.event_hash[:16]}")
    return 0


def cmd_query(args) -> int:
    """The golden-answer query suite (M3 acceptance)."""
    state, _ = _load_state()
    q = args.what
    if q == "incumbent":
        print(json.dumps(state.incumbents, indent=1))
    elif q == "spent":
        print(json.dumps(spend_view(state)["windows"], indent=1))
    elif q == "budget":
        print(json.dumps({l: v.get("budget") for l, v in state.lineages.items()}, indent=1))
    elif q == "constants":
        print(json.dumps({s: {"doc_id": d.get("doc_id"),
                              "provisional": [e["key"] for e in d.get("entries", [])
                                              if e.get("finality") == "provisional"]}
                          for s, d in state.constants.items()}, indent=1))
    elif q == "conditionals":
        print(json.dumps({cid: {"kind": c.get("kind"), "status": c.get("status")}
                          for cid, c in state.conditionals.items()}, indent=1))
    elif q == "placebo":
        print(json.dumps(state.placebo_history, indent=1))
    elif q == "failures":
        print(json.dumps(state.kill_list, indent=1))
    else:
        print(f"unknown query: {q}", file=sys.stderr)
        return 2
    return 0


def cmd_snapshot(_args) -> int:
    state, _ = _load_state()
    export_all(state)
    print(f"projections written under {config.workdir()}")
    return 0


def cmd_render(_args) -> int:
    lg = Ledger()
    out = config.workdir() / "LEDGER.md"
    render_ledger(lg.iter_events(), out)
    print(f"rendered {out}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="reg")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("verify")
    sp = sub.add_parser("state"); sp.add_argument("--json", action="store_true")
    sa = sub.add_parser("append"); sa.add_argument("draft")
    sq = sub.add_parser("query"); sq.add_argument("what")
    sub.add_parser("snapshot")
    sub.add_parser("render")
    args = p.parse_args(argv)
    config.ensure_layout()
    return {"verify": cmd_verify, "state": cmd_state, "append": cmd_append,
            "query": cmd_query, "snapshot": cmd_snapshot, "render": cmd_render}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
