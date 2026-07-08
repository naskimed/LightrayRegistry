# LightrayRegistry

Event-sourced, hash-chained, single-writer **system of record** for the R&D trading-research
pipeline ("one frozen matrix, two engines"). Everything else — the vectorbt population engine,
the MATLAB SGL geometry engine, cards, the Claude Code boundary/shadow/operator sessions,
one-shot OOS readouts, certification — is a **client** that reads frozen contract exports and
submits events through one write path.

**Authoritative design:** `docs/` (PLAN v10.4 · TECH_SPEC TS-2.0 · AGENT_CONTRACTS AC-1.0 ·
MATLAB_DEPLOYMENT MD-1.0 and the rest of the LightrayRegistryDocs set). Where code and docs
disagree, the docs win and the discrepancy is a defect here.

## The four sentences that generate the design

1. **The append-only event log is the only truth**; all state, spend maps, budgets, and even
   `LEDGER.md` are derived, rebuildable projections (`state == replay(log)`).
2. **One write path**: ingest/enrichment (impure — computes hashes) → pure `decide(state, event)`
   barrier → fsync append → pure reducer. Nothing else writes, ever.
3. **Identity is content**: sha256 over canonical bytes; KEY ≠ seed; frozen objects are never
   mutated, only superseded — and supersession carries its spends.
4. **History gates access to the exam, never the grade** (verdict invariance): budgets,
   velocities, and one-shot flags control *whether* a readout may happen; the frozen gate alone
   decides *what passed*.

## Layout

```
registry/
  canon.py            canonical JSON + sha256 + parquet content-digest v1
  store.py            atomic writes, JSONL, CAS, var/ layout
  ledger.py           hash-chained events.jsonl, verify, quarantine, git anchoring
  schemas/            Pydantic v2 models: envelope, all namespace payloads, state,
                      scorecards (TS-2.0 §5.5), conditionals (NS12), look budget (NS7)
  barrier.py          pure decide(state, event) — the full REG-INV / STAT-INV catalog
  predicates.py       named + versioned predicate functions (no eval, no DSL)
  spend.py            spend stack: one-shot / velocity / lifetime look budget / placebo
  reducer.py          pure fold(state, event); replay applies reducers only
  cascade.py          cycles, promotion projection, dial, novelty quota (TS-2.0 §5.5)
  cards.py            deterministic card compressors (byte-identical re-emit)
  export.py           contracts/ exports — the ONLY files engines read
  render.py           prefix-stable LEDGER.md renderer + daily digest
  cli.py              reg append|state|verify|query|snapshot
  daemon/             single-writer daemon: writer thread, inbox, HTTP api,
                      scheduler (jobs, conditionals, cycles, placebo), agent runner
  bridges/            matlab.py (job/result contracts, PC-echo), vbt.py (audit gate)
  io/mt3.py           the ONE canonical MT3 CSV reader
  tools/              t=0 converters (idempotent, imported:true)
mcp/matlab_mcp.py     stdio MCP server wrapping matlab -batch (operator-only)
roles/                versioned role prompts (boundary/shadow/operator + CLAUDE.md)
matlab/registry_client/  registry_load_contract.m, registry_submit.m
seed/                 seed-data JSONs (registered hashes/fingerprints, with provenance)
deploy/               systemd units
var/                  runtime workdir (gitignored) — or $LIGHTRAY_REGISTRY_WORKDIR
```

## Build order (milestones — PLAN §7)

M0 log mechanics → M1 schemas+barrier → M2 CLI+store+replay → M3 t=0 seed + artifact recovery →
M4 daemon+inbox+conditionals → M5 MATLAB bridge round-trip → M6 vbt bridge round-trip →
M7 night-1 joint block + cards → M8S cascade mechanics → M9S campaign one, hosted →
M10S boundary+shadow supervised → M11 unattended epochs.

## Run

```bash
pip install -e ".[bridges]"        # bridges extra only needed on the engine host
reg verify                          # walk the chain
reg-daemon                          # foreground; deploy/registry-daemon.service for systemd
```

Kill switches: `touch $WORKDIR/HALT` (stops all dispatch) · `touch $WORKDIR/READONLY`
(engines run; no new proposals accepted).
