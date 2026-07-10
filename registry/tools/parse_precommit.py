"""parse_precommit — extract pc_v062.json from the HASHED precommit.m (M3 input for
register_seed windows). Field-parity is asserted by eye + the PC-echo at M5; this parser
covers the scalar/vector assignments and the window blocks; anything it cannot parse lands in
`unparsed` for the human pass. Window dates come FROM THE FILE — never typed.

Usage: python -m registry.tools.parse_precommit <precommit.m> --out pc_v062.json
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from ..canon import sha256_file
from ._seed import load_seed


def parse(path: Path) -> dict:
    # FAIL-CLOSED hash gate (merge-fix 2026-07-10): a missing seed or missing pin used to skip
    # the comparison silently — an unverified precommit could mint a windowset. Now: no pin,
    # no parse; "dates come FROM THE HASHED file" is enforced, not aspirational.
    try:
        spec = load_seed("tierb_artifacts.json")
    except FileNotFoundError:
        raise SystemExit("REFUSING: seed/tierb_artifacts.json not found — the precommit pin is "
                         "unavailable; the source cannot be verified. Seed the pin first.")
    expected = next((a["sha256"] for a in spec["artifacts"] if a["rel"] == "precommit.m"), None)
    if not expected:
        raise SystemExit("REFUSING: no precommit.m pin in tierb_artifacts.json — register the "
                         "pin for this spec version before parsing it.")
    actual = sha256_file(path)
    if actual != expected:
        raise ValueError(f"precommit.m hash {actual} != registered {expected} — drifted copy")

    text = path.read_text(errors="replace")
    scalars: dict = {}
    unparsed: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("PC.") or "=" not in line:
            continue
        m = re.match(r"PC\.([A-Za-z0-9_.]+)\s*=\s*(.+?);", line)
        if not m:
            unparsed.append(line)
            continue
        key, raw = m.group(1), m.group(2).strip()
        if re.fullmatch(r"-?\d+(\.\d+)?([eE]-?\d+)?", raw):
            scalars[key] = float(raw) if ("." in raw or "e" in raw.lower()) else int(raw)
        elif raw.startswith("'") and raw.endswith("'"):
            scalars[key] = raw.strip("'")
        elif raw.startswith("[") and raw.endswith("]"):
            try:
                scalars[key] = [float(x) for x in raw.strip("[]").replace(",", " ").split()]
            except ValueError:
                unparsed.append(line)
        else:
            unparsed.append(line)      # formulas/expressions → declarative FormulaRef by hand

    # window blocks: PC.windows.W1.start = '...' style (adjust to the real precommit shape at M3)
    windows = []
    for w in ("W1", "W2", "W3", "W4"):
        start = scalars.pop(f"windows.{w}.start", None)
        end = scalars.pop(f"windows.{w}.end", None)
        role = scalars.pop(f"windows.{w}.role", None)
        if start and end:
            windows.append({"name": w, "start": start, "end": end,
                            "role": role or ("backward_only" if w == "W1" else
                                             "forward_certifier" if w == "W4" else "middle")})

    # the REAL v0.6.2 shape (M3 adjustment): one multi-line cell array
    #   PC.windows = { 'W1', '<start>', '<end>', '<note>'; ... };
    if not windows:
        m = re.search(r"PC\.windows\s*=\s*\{(.*?)\}\s*;", text, re.DOTALL)
        if m:
            body = m.group(1).replace("...", " ")
            date_re = re.compile(r"\d{4}-\d{2}-\d{2}$")
            for row in body.split(";"):
                cells = re.findall(r"'([^']*)'", row)
                if len(cells) >= 3:
                    name, start, end = cells[0], cells[1], cells[2]
                    # date-shape validation (merge-fix 2026-07-10): positional cells with a
                    # malformed shape must ERROR, never mint garbage window dates silently.
                    if not (date_re.match(start) and date_re.match(end)):
                        raise ValueError(f"window row {cells!r}: cells[1]/[2] are not "
                                         f"YYYY-MM-DD dates — precommit shape changed; refuse")
                    note = cells[3] if len(cells) > 3 else ""
                    # ROLE FROM THE DOC'S OWN TEXT (merge-fix 2026-07-10): the note cell states
                    # the role; name-mapping is only the fallback. A rename/reorder/W5 insert
                    # no longer silently mislabels.
                    nl = note.lower()
                    if "backward" in nl:
                        role = "backward_only"
                    elif "certifier" in nl or "forward" in nl:
                        role = "forward_certifier"
                    elif "middle" in nl:
                        role = "middle"
                    else:
                        role = ("backward_only" if name == "W1" else
                                "forward_certifier" if name == "W4" else "middle")
                    windows.append({"name": name, "start": start, "end": end,
                                    "note": note, "role": role})
            unparsed = [u for u in unparsed if not u.startswith("PC.windows ")]
    if not windows:
        raise ValueError("parsed ZERO windows — the precommit windows block did not match any "
                         "known shape; refusing to return an empty windowset silently")

    exclusions = []
    # re.DOTALL (merge-fix): the sibling windows regex is DOTALL; a multi-line exclusions cell
    # array must not silently match nothing.
    # DOTALL applies to the braces content only; the trailing %-comment (rationale) is
    # single-line by construction ([^\n]*), else it would swallow the rest of the file.
    m = re.search(r"PC\.window_exclusions\s*=\s*\{(.*?)\}\s*;[ \t]*(?:%[ \t]*([^\n]*))?",
                  text, re.DOTALL)
    if m:
        cells = re.findall(r"'([^']*)'", m.group(1))
        for i in range(0, len(cells) - 1, 2):
            exclusions.append({"range": [cells[i], cells[i + 1]],
                               "rationale": (m.group(2) or "").strip()})
        unparsed = [u for u in unparsed if not u.startswith("PC.window_exclusions")]

    return {
        "doc_id": "pc_v0.7.0",
        "precommit_sha256": actual,
        "scalars": scalars,
        "windows": windows,
        "embargo": {"left_days": int(scalars.get("embargo_left_days",
                                                 scalars.get("embargo_left_d", 0)) or 0),
                    "right_days": int(scalars.get("embargo_right_days",
                                                  scalars.get("embargo_right_d", 0)) or 0)},
        "exclusions": exclusions,
        "unparsed": unparsed,          # the human pass finishes these as declarative entries
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("precommit", type=Path)
    p.add_argument("--out", type=Path, default=Path("pc_v062.json"))
    a = p.parse_args()
    doc = parse(a.precommit)
    a.out.write_text(json.dumps(doc, indent=1))
    print(f"parsed {len(doc['scalars'])} scalars, {len(doc['windows'])} windows, "
          f"{len(doc['unparsed'])} lines for the human pass → {a.out}")


if __name__ == "__main__":
    main()
