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
    expected = None
    try:
        spec = load_seed("tierb_artifacts.json")
        expected = next((a["sha256"] for a in spec["artifacts"] if a["rel"] == "precommit.m"), None)
    except FileNotFoundError:
        pass
    actual = sha256_file(path)
    if expected:
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
    return {
        "doc_id": "pc_v0.7.0",
        "precommit_sha256": actual,
        "scalars": scalars,
        "windows": windows,
        "embargo": {"left_days": int(scalars.get("embargo_left_days", 0) or 0),
                    "right_days": int(scalars.get("embargo_right_days", 0) or 0)},
        "exclusions": [],
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
