"""Human-readable projections: the PREFIX-STABLE LEDGER.md renderer + the daily digest.

Prefix-stability (a SIGNED design property, property-tested at M2):
render(events[0..n]) is a byte-prefix of render(events[0..n+k]) — the human-readable history
never mutates while the log doesn't. Achieved by rendering EACH EVENT to a self-contained
block, append-only, with NO aggregate lines above the fold. Pre-registry prose (the imported
LEDGER) stays authoritative for imported history — imported events render as pointers.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

from . import config
from .schemas.envelope import Event

_HEADER = "# LEDGER — derived, prefix-stable render of the event log. DO NOT EDIT.\n"


def render_event(ev: Event) -> str:
    lines = [f"\n## [{ev.seq}] {ev.ts.isoformat()} · {ev.type} · {ev.actor}"]
    if ev.imported:
        lines.append("*(imported pre-registry act — the original prose ledger stays authoritative)*")
    if ev.provenance == "discretionary" and ev.hypothesis:
        lines.append(f"**Hypothesis:** {ev.hypothesis}")
        if ev.expected_outcome:
            lines.append(f"**Expected:** {ev.expected_outcome}")
    if ev.cites:
        lines.append(f"cites: {', '.join(ev.cites)}")
    if ev.type == "note.record":
        lines.append(f"**{ev.payload.get('title', '')}**")
        lines.append(ev.payload.get("body", ""))
    else:
        keys = sorted(ev.payload.keys())[:8]
        brief = {k: ev.payload[k] for k in keys
                 if isinstance(ev.payload[k], (str, int, float, bool))}
        if brief:
            lines.append("`" + " · ".join(f"{k}={v}" for k, v in brief.items()) + "`")
    lines.append(f"`event {ev.event_id} · hash {ev.event_hash[:12]}`")
    return "\n".join(lines) + "\n"


def render_ledger(events: Iterable[Event], path: Path | None = None) -> str:
    """Full render (cold). The daemon APPENDS render_event() per accepted event instead of
    re-rendering — same bytes by construction, which is the prefix-stability property."""
    out = _HEADER + "".join(render_event(e) for e in events)
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(out)
    return out


def append_ledger_md(ev: Event, w: Path | None = None) -> None:
    p = (w or config.workdir()) / "LEDGER.md"
    if not p.exists():
        p.write_text(_HEADER)
    with open(p, "a") as f:
        f.write(render_event(ev))


def daily_digest(state, date_str: str, w: Path | None = None) -> Path:
    """reports/daily_<date>.md — observation without interaction."""
    lines = [f"# Daily digest — {date_str}\n"]
    lines.append("## Budgets")
    for lin, v in state.lineages.items():
        b = v.get("budget") or {}
        lines.append(f"- {lin}: k={v.get('k_cumulative', 0)} remaining={b.get('remaining')} "
                     f"alarm={'FIRED' if b.get('alarm_fired') else 'ok'} "
                     f"diagnostic={'ON' if b.get('diagnostic_mode') else 'off'}")
    lines.append("\n## Suspensions")
    lines.append(f"- readout_conditional_channel: "
                 f"{'SUSPENDED' if state.suspensions.get('readout_conditional_channel') else 'active'}")
    lines.append("\n## Cards emitted")
    for cid, c in list(state.cards.items())[-20:]:
        lines.append(f"- {cid} ({c.get('card_type')})")
    lines.append("\n## Open cycle")
    lines.append(f"- {state.open_cycle or 'none'}")
    p = config.reports_dir(w) / f"daily_{date_str}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines) + "\n")
    return p
