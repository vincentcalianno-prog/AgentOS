# ACP — Agent Contract Platform

Implementation of the Agent Contract Platform per Architecture Spec v2.4 and Implementation Guide v1.1.

## Repository Layout

```
acp/
├── layer_b/                       Generic engineering (portable, no deployment-specific values)
│   ├── agents/                    Agent runtime code
│   │   └── state_manager.py       Agent 3 — system spine [BUILT]
│   ├── core/                      Generic infrastructure
│   │   ├── adapters/              Abstract interfaces + dev/test implementations
│   │   │   ├── ledger_adapter.py        Abstract: tenant-scoped persistence
│   │   │   ├── audit_adapter.py         Abstract: append-only audit log
│   │   │   ├── sqlite_ledger.py         Concrete: SQLite (dev/test)
│   │   │   └── in_memory_audit.py       Concrete: in-memory audit (dev/test)
│   │   ├── tenancy.py             Cross-tenant boundary enforcement
│   │   └── types.py               Core dataclasses, state machine, exceptions
│   ├── schemas/                   (Empty — JSON schemas added as needed)
│   └── tests/
│       └── unit/
│           └── test_state_manager.py    29 tests, all synthetic data
│
├── layer_c_antora/                Antora-specific (not portable; Antora work product)
│   ├── adapters/
│   │   └── sheets_ledger.py       Concrete: Google Sheets (STUB — not wired)
│   └── config/                    (Empty — populated during deployment)
│
├── deploy/                        Wires layer_b agents to layer_c_antora adapters
│                                  (Empty — populated when first agent goes live)
│
└── discipline_check.py            Static check for Section 13.7 compliance
```

## Portability Discipline

Layer B is designed to be deployment-agnostic. Specifically:

- **Field names are stack-neutral.** `inbox_thread_id` (not `gmail_thread_id`), `storage_folder_path` (not `drive_folder_path`), `last_outbound_version_sent` (not `last_antora_version_sent`).
- **Role names are deployment-neutral.** `owner` (not `owner_scm`). The deploying organization configures human-readable labels in Layer C.
- **Workflow terminology is generic.** `review_package_status` (not `lrs_status`). Different organizations may call the legal review artifact different things.
- **Test fixtures use synthetic data.** Made-up names (alice, bob, carol; Acme Industrial, Beta Manufacturing, Gamma Components) — no real organizations.

The discipline check (`discipline_check.py`) enforces these patterns automatically. CI fails on any introduction of deployment-specific strings or stack-leaking field names in `layer_b/`.

## Current Build Status (Phase 1)

| Component | Status | Notes |
|-----------|--------|-------|
| ACP_Tracker_v2.xlsx | ✅ Built | Antora-specific deployment with Vincent's 36 rows preserved |
| Tracker Template | ✅ Built | Generic deployment-agnostic version with rich documentation |
| State Manager (Agent 3) | ✅ Built | 29 tests passing, discipline check clean, fully portable |
| SQLite Ledger | ✅ Built | Dev/test backend |
| In-Memory Audit Log | ✅ Built | Dev/test backend |
| Sheets Ledger | 🟡 Stub | Interface defined; live wiring deferred to Agent 1 OAuth pass |
| Email Watcher (Agent 1) | ⬜ Next | Requires Gmail/Outlook OAuth |
| Document Extraction (Agent 2) | ⬜ Pending | Requires storage backend OAuth |
| Other agents | ⬜ Pending | Phases 2-3 |

## Running the Tests

```bash
cd acp/
python3 -m unittest acp.layer_b.tests.unit.test_state_manager -v
```

## Running the Discipline Check

```bash
python3 acp/discipline_check.py
```

Should be run in CI before any merge to main.
