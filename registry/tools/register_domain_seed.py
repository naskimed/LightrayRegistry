"""register_domain_seed — consumes the two NEW seed files through the SAME write path.

Companions to register_seed.py (constants/artifacts/windows/arm-conditionals). Idempotent by
deterministic event_id (double-run => zero new events). Everything lands imported:true where
it transcribes decided history, imported:false where it is a fresh registration of catalog
content — both PROPOSED-until-ratified in the human sense; the barrier is the validator.

Usage:
  python -m registry.tools.register_domain_seed features
  python -m registry.tools.register_domain_seed families
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from ._seed import SEED_DIR, SeedSession, load_seed

# DOC PINS — the transcription sources. The registrar REFUSES to run unless the local copies
# hash-match (no-remembered-literals as mechanism, not discipline). Deferring the docs/ move
# is fine; running the seed against unverified sources is not.
DOC_PINS = {
    "FEATURES.md": "d346b2fc85e4da5f474955f7f727c1c770b8c0ca5441d3ecec00f6b9549837be",
    "SEED_PACK.md": "47664749b5d4835dc59630ff6bd37ead1a3994b772e988acdb74badeb3f22bc9",
}

# SEED PINS (merge-fix 2026-07-10): the seed JSONs are what actually gets REGISTERED, so they
# are pinned too — a doc-pinned run over an edited seed file was the remaining bypass.
SEED_PINS = {
    "features_seed.json": "7149abe4599cbe6ed0258911fec928d2f7ee634357b4ea565b3d38ff9118d363",
    "families_programs_seed.json": "8c922aef5d88c642e603e51890810dcea63d8fd48c433fd720cea58a46bff81a",
}


def _verify_doc_pins(docs_dir: Path) -> None:
    for name, expected in DOC_PINS.items():
        p = docs_dir / name
        if not p.exists():
            raise SystemExit(f"REFUSING: {p} not found — co-locate the docs (any dir via "
                             f"--docs-dir) before seeding; the transcription is unverifiable without it")
        actual = hashlib.sha256(p.read_bytes()).hexdigest()
        if actual != expected:
            raise SystemExit(f"REFUSING: {name} sha256 {actual[:12]}… != pinned {expected[:12]}… — "
                             f"the local doc differs from the transcription source; reconcile versions first")
    print(f"doc pins verified: {', '.join(DOC_PINS)} match")


def _verify_seed_pins() -> None:
    for name, expected in SEED_PINS.items():
        p = SEED_DIR / name
        actual = hashlib.sha256(p.read_bytes()).hexdigest()
        if actual != expected:
            raise SystemExit(f"REFUSING: {name} sha256 {actual[:12]}… != pinned {expected[:12]}… — "
                             f"the seed file itself was edited after transcription; re-pin deliberately")
    print(f"seed pins verified: {', '.join(SEED_PINS)} match")


def _guard(docs_dir: Path | None = None) -> None:
    """Merge-fix 2026-07-10: the guard runs INSIDE the seed functions — importing
    seed_features()/seed_families() directly no longer bypasses it."""
    _verify_doc_pins(docs_dir or SEED_DIR.parent / "docs")
    _verify_seed_pins()


def seed_features(docs_dir: Path | None = None) -> None:
    _guard(docs_dir)
    spec = load_seed("features_seed.json")
    with SeedSession() as s:
        s.submit("constants.register", spec["catalog_constants"],
                 intent="seed:ns2_catalog")
        for row in spec["features"]:
            s.submit("feature.register", row["payload"],
                     intent=f"seed:feature:{row['payload']['feature_id']}",
                     reasoning=f"transcribed: {row['source']}")
        s.report("features")


def seed_families(docs_dir: Path | None = None) -> None:
    _guard(docs_dir)
    spec = load_seed("families_programs_seed.json")
    with SeedSession() as s:
        for row in spec["families"]:
            s.submit("family.register", row["payload"],
                     intent=f"seed:family:{row['payload']['family_id']}",
                     reasoning=f"transcribed: {row['source']}")
        s.submit("constants.register", spec["programs_constants"],
                 intent="seed:ns5_programs")
        s.report("families")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("what", choices=["features", "families"])
    p.add_argument("--docs-dir", type=Path, default=SEED_DIR.parent / "docs",
                   help="dir holding FEATURES.md + SEED_PACK.md (any location; hashes must match)")
    a = p.parse_args()
    {"features": seed_features, "families": seed_families}[a.what](a.docs_dir)


if __name__ == "__main__":
    main()
