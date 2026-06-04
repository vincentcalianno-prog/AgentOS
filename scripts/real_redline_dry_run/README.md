# ACP Real-Redline Dry-Run Harness

End-to-end test harness that runs a synthetic counterparty-redlined MEPA through
all 9 ACP Layer B agents and verifies all expected output artifacts are produced.

## Quick start

From the repo root:

```bash
python3 scripts/real_redline_dry_run/run.py
```

Output lands in `scripts/real_redline_dry_run/outputs/<ISO-timestamp>/`.

## Files

| File | Purpose |
|---|---|
| `run.py` | Main harness: wires agents, runs pipeline, runs smoke test |
| `mock_redline_generator.py` | Generates synthetic redlined MEPAs with configurable patterns |
| `inputs/sample_mepa_base.md` | 20-clause generic MEPA template (outbound position) |
| `outputs/` | Run artifacts — one timestamped subdirectory per run |
| `outputs/.gitkeep` | Keeps directory tracked in git |

## Modification patterns

| Pattern | Clause | Type |
|---|---|---|
| `payment_terms` | 2.9 | accepted_with_addition (liability cap + gross negligence carve-out) |
| `payment_delay` | 3.2 | modified (net-30 → net-45) |
| `termination_notice` | 4.4 | modified (60-day → 30-day notice) |
| `indemnity_deletion` | 6.1 | deleted (removes mutual indemnification) |
| `force_majeure_expansion` | 7.2 | modified (expands FM definition) |

Run a specific subset:

```bash
python3 scripts/real_redline_dry_run/run.py --patterns payment_delay indemnity_deletion
```

Generate a redlined document without running the pipeline:

```bash
python3 scripts/real_redline_dry_run/mock_redline_generator.py \
    --patterns payment_delay termination_notice \
    --out /tmp/redlined_mepa.md
```

## Expected artifacts

After a successful run, the output directory contains:

| File | Agent | Description |
|---|---|---|
| `counterparty_redline.md` | harness | synthetic redlined MEPA |
| `structural_diff.json` | Agent 4 | clause-level diff |
| `redline_analysis.json` | Agent 5 | per-clause recommendations |
| `counter_proposals.json` | Agent 6 | per-clause counter-proposals |
| `lrs_v1.md` | Agent 7 | Legal Review Summary document |
| `lrs_v1_metadata.json` | Agent 7 | LRS metadata sidecar |
| `audit_log.json` | all agents | full audit trail |
| `run_manifest.json` | harness | run metadata and stats |

## Architecture notes

The harness uses:
- **In-memory SQLite** ledger (`:memory:`) — no persistent database needed
- **File-backed storage adapter** — writes artifacts to the output directory
- **Stub LLM functions** — deterministic rule-based stubs that exercise the
  full wiring without requiring an API key
- **`SYNTHETIC_CONFIG`** — the same orchestrator config used in Layer B tests

Agents 1 (Email Watcher), 2 (Document Extractor), and 3 (State Manager) are
seeded directly — the harness synthesizes the events they would normally produce
so the pipeline can start at Agent 4 (Structural Diff).

## Outputs are gitignored

Run outputs are excluded from version control. Only `.gitkeep` is tracked.
