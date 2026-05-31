# PROJECT_CONTEXT.md — ACP Architecture Substrate

**Purpose:** Durable ground-truth document for new Claude Code sessions working on ACP.
Read this first. Every fact below is sourced from repo files, not memory or handoff notes.

**Last verified:** 2026-05-31
**HEAD:** 3301690 `feat: wire confidence tier headers into Agent 7 stub LRS renderer`
**Branch:** `feature/acp-phase1-migration`
**Tests:** 470 passed, 22 subtests (`python3 -m pytest acp/layer_b/tests/ -q`)
**Discipline:** 4/4 PASS (`python3 acp/discipline_check.py`)

---

## 1. REPO IDENTITY

| Field | Value |
|---|---|
| Repo root | `~/Desktop/Projects/AgentOS` |
| Active branch | `feature/acp-phase1-migration` |
| HEAD commit | `3301690` |
| HEAD message | `feat: wire confidence tier headers into Agent 7 stub LRS renderer` |
| Test count | 470 passed, 22 subtests |
| Discipline | 4/4 PASS |
| ACP sub-project root | `acp/` |

The sub-project is ACP — Agent Contract Platform. It is the only active sub-project
in this repo. All architecture discussion below refers to ACP unless stated otherwise.

---

## 2. THREE-LAYER ARCHITECTURE

ACP enforces a strict three-layer separation. The layer names and their invariants:

### Layer A — AgentOS substrate
- Contains: Python runtime, environment management, repo scaffolding.
- Contains **zero** negotiation logic, domain content, or IP.
- Files: repo root tooling, `acp/__init__.py`, test runner config.

### Layer B — WorkflowOS platform
- Path: `acp/layer_b/`
- Contains: all 9 agent implementations, adapter interfaces, state types, schemas.
- **Same binary in every deployment.** No Antora-specific values hard-coded here.
- Discipline check (`acp/discipline_check.py`) enforces this mechanically at every commit.
- No imports from `layer_c_antora`. No Antora-specific strings (see §13).

### Layer C — Antora deployment shell
- Path: `acp/layer_c_antora/`
- Contains: all Antora-specific content — credentials, adapter implementations,
  playbook YAML (Phase 2a), LLM prompt templates, org-specific config.
- **All IP lives here.** Layer C content never travels upstream to Layer B.
- Subdirectories confirmed: `adapters/` (sheets_ledger.py), `config/` (agent_7_lrs_prompts.py), `llm/`.

### Portability test
A peer organization deploying ACP would create `acp/layer_c_<other_org>/` alongside
`layer_c_antora/`. They would touch **zero** Layer A or Layer B files.

*Sources: `docs/layer_c_wiring_plan.md` lines 1–34; `acp/discipline_check.py` lines 1–9.*

---

## 3. AGENT INVENTORY

All 9 agents live in `acp/layer_b/agents/`. All are Layer B. None contain Antora IP.

> **Harness note:** Agents 1–3 are seeded directly in the dry-run harness. The harness
> synthesizes their output events so the pipeline can start at Agent 4.
> See `scripts/real_redline_dry_run/README.md`.

| # | File | Spec ref | What it does |
|---|---|---|---|
| 1 | `email_watcher.py` | §5.1 | Polls inbox for inbound contract messages; classifies as redline / non-redline / irrelevant; emits state event; marks processed. Haiku-tier LLM for classification. |
| 2 | `document_extraction.py` | §5.2 | Pulls contract attachments from inbox; persists to tenant-scoped storage at canonical paths; computes integrity hashes. |
| 3 | `state_manager.py` | §5.3 | Canonical source of truth for all active negotiations across all operator tenants. Instantiates and maintains `NegotiationRow` records. Forwards platform events to Agent 8. |
| 4 | `structural_diff.py` | §5.4 | Deterministic clause-level diff between outbound version and counterparty redline. Persists `structural_diff.json`. |
| 5 | `redline_analysis.py` | §5.5 | For each changed clause: invokes configured playbook + LLM to produce a `ClauseRecommendation`. Persists `redline_analysis.json`. |
| 6 | `counter_proposal.py` | §5.6 | For clauses where Agent 5 recommended "negotiate" or "reject": drafts counter-proposal language. Persists `counter_proposals.json`. |
| 7 | `lrs_generator.py` | §5.7 | Generates the Legal Review Summary (LRS) document from diff + analysis + proposals. Renders confidence tier headers per `LrsConfidenceTier`. |
| 8 | `workflow_orchestrator.py` | §5.8 | Operational spine: SLA monitoring, retry logic, inbox routing, notification fan-out, degraded-mode management. Does NOT execute pipeline steps (those are Agents 1–7). Five public methods: `scan_sla_violations()`, `retry_failed_event()`, `resolve_inbox_event()`, `route_notification()`, `enter_degraded_mode()`. |
| 9 | `portfolio_aggregator.py` | §5.9 | Read-only cross-tenant aggregation. Produces consolidated team views. Never writes to individual trackers. Query interface only (no `process_event()`). Includes `detect_playbook_update_candidates()` stub (Phase 3). |

**Supporting files in `acp/layer_b/agents/` (not numbered agents):**
- `workflow_orchestrator_config.py` — config dataclasses for Agent 8
- `review_feedback_capture.py` — Gate 1/2 learning signal capture (§7)
- `contract_redline_source.py` — `WorkItemSource` adapter for Agent 9

*Sources: docstrings in each agent file; `scripts/real_redline_dry_run/README.md`.*

---

## 4. SCHEMA ENTITIES

File: `acp/schemas/playbook_schemas.py`

**13 class definitions** (`grep -n "^class " acp/schemas/playbook_schemas.py`):

| Line | Class | Role |
|---|---|---|
| 25 | `AbstractionStatus` (Enum) | Learning loop processing state: `PENDING`, `EXTRACTED`, `SKIPPED`, `FLAGGED_FOR_REVIEW` |
| 36 | `ReviewerReaction` (Enum) | `ACCEPTED`, `EDITED`, `REJECTED` |
| 54 | `RejectionResponse` | Sub-block of AntoraResponse: rationale + counter_proposal |
| 62 | `CompromiseResponse` | Sub-block: conditions + revised_language |
| 70 | `AcceptanceResponse` | Sub-block: rationale for why baseline already protects operator |
| 77 | `AntoraResponse` | Three-state structured response: rejection + compromise + acceptance |
| 89 | `TemplateRef` | Pointer to authoritative template document + section + version |
| 97 | `DefendBaseline` | Clause baseline position with template_ref + guidance |
| 104 | `AcceptModification` | Counterparty modification pattern that is acceptable |
| 113 | `RejectThreshold` | Counterparty change that must always be rejected |
| 126 | `OutcomeRecord` | Single negotiation outcome (raw IP; never leaves Layer C) |
| 149 | `RecommendationReview` | Captures Gate 1/2 reviewer feedback as Tier-2 evidence |
| 170 | `PlaybookEntry` | Top-level entry: Antora's position on a clause type. Authored in Layer C. |

**Layer discipline:** Schemas live in `acp/schemas/` (Layer A substrate), not in `layer_b/`
or `layer_c_antora/`. All layers share the same data contract. `PlaybookEntry` instances
are authored in Layer C and loaded at runtime; the schema definition is shared.

*Source: `acp/schemas/playbook_schemas.py` lines 25–210.*

---

## 5. KEY DATA TYPES

### ClauseRecommendation
- **File:** `acp/layer_b/agents/redline_analysis.py`, line 59
- **NOT in `playbook_schemas.py`** — this is a known deviation from spec.
  Any schema prompt spec referencing `playbook_schemas.py` for this class is wrong.
  Use `redline_analysis.py`.
- Key fields: `clause_reference`, `recommendation` ("accept"|"reject"|"negotiate"|"escalate"),
  `reasoning`, `playbook_reference`, `confidence`, `requires_legal_review`,
  `is_signature_blocker`, `playbook_grounded`, `evidence_source`, `original_text`,
  `antora_response`.
- `playbook_grounded=True` → Agent 5 matched a `PlaybookEntry`; counter from `antora_response`.
- `playbook_grounded=False` → No `PlaybookEntry` for this clause; response is LLM-reasoned.
- `evidence_source` format: `"<entry_id> | <evidence_tier> | <source_description>"` (None when `playbook_grounded=False`).

### LrsConfidenceTier
- **File:** `acp/layer_b/agents/redline_analysis.py`, line 47
- Three values:
  - `PLAYBOOK_VERIFIED` — playbook hit + evidence_tier = "verified" (Tier 1 closed agreement)
  - `PLAYBOOK_PROVISIONAL` — playbook hit + evidence_tier = "provisional" (Tier 2 feedback)
  - `AGENT_REASONED` — no playbook entry; LLM-reasoned from general contract principles

### resolve_confidence_tier()
- **File:** `acp/layer_b/agents/redline_analysis.py`, line 82
- Pure function — no side effects, no I/O. Called by Agent 7 during LRS rendering.
- Logic: if `not rec.playbook_grounded` → `AGENT_REASONED`; elif `"verified"` in `evidence_source` → `PLAYBOOK_VERIFIED`; else → `PLAYBOOK_PROVISIONAL`.

### AntoraResponse
- **Canonical definition:** `acp/schemas/playbook_schemas.py`, line 77
- Do NOT redefine in layer_b agents. `redline_analysis.py` imports from `playbook_schemas`.

*Sources: `acp/layer_b/agents/redline_analysis.py` lines 47–91; `acp/schemas/playbook_schemas.py` lines 77–81.*

---

## 6. LOADERS

### PilotEntryLoader
- **File:** `acp/layer_b/loaders/pilot_entry_loader.py`
- **Purpose:** Harness-only bridge. Looks up `PilotEntryRef` by clause reference.
  Returns lightweight reference carrying `entry_id`, `evidence_tier`, `negotiability`, `description`.
- **`CLAUSE_TO_PILOT`** maps exactly two clause references:
  - `"5.1"` → `"warranty_period"` (entry_id: `mepa.warranty.warranty_period`)
  - `"8.3"` → `"lol_direct_damages"` (entry_id: `mepa.limitation_of_liability.direct_damages_clarification`)
- **This is NOT the production playbook loader.** Phase 2a will replace it with a full
  `playbook_loader` that reads YAML from `acp/layer_c_antora/`. `PilotEntryLoader` is the
  bridge used by the dry-run harness and Phase 2 validation tests until then.
- Methods: `lookup(clause_reference)`, `has_entry(clause_reference)`, `evidence_source_string(clause_reference)`.

*Source: `acp/layer_b/loaders/pilot_entry_loader.py` lines 1–91.*

---

## 7. REVIEW FEEDBACK CAPTURE

### ReviewFeedbackCapture
- **File:** `acp/layer_b/agents/review_feedback_capture.py`
- **Purpose:** Wires human review actions into structured `RecommendationReview` records
  on `PlaybookEntry.recommendation_reviews`. Records become Tier-2 playbook evidence
  processed by Agent 9 in Phase 3.
- **Pure except for** audit log writes and `date.today()` calls.
- **Caller is responsible for persisting** the returned updated entry. This module
  does no direct writes to storage.

Two public methods:

| Method | Gate | Reviewer | Trigger |
|---|---|---|---|
| `capture_owner_feedback()` | Gate 1 | Owner (e.g. SCM role in Layer C) | Owner reviews Agent 5 recommendation |
| `capture_legal_feedback()` | Gate 2 | Legal (e.g. Sandelin) | Legal reviews Agent 6 counter-language |

**Naming note:** The method is `capture_owner_feedback`, NOT `capture_scm_feedback`.
"SCM" is in `ANTORA_FORBIDDEN` (see §13). The rename was required to pass the
discipline check.

`reviewer_role` field format: `"owner:<reviewer_name>"` (Gate 1) or `"legal:<reviewer_name>"` (Gate 2).
`abstraction_status` is always initialized to `AbstractionStatus.PENDING`.

*Source: `acp/layer_b/agents/review_feedback_capture.py` lines 1–153.*

---

## 8. LEARNING LOOP

Two distinct flows. Neither runs autonomously.

### Flow 1 — Outcome abstraction (Phase 3 execution)
```
OutcomeRecord (Layer C, raw IP)
  → IP-strip step
  → shared registry (Layer B pattern store)
  → Layer A refinements
```
`OutcomeRecord.abstraction_status` (`AbstractionStatus` enum) prevents double-processing.
Schema is designed now (`acp/schemas/playbook_schemas.py` line 126). Execution is Phase 3.
Raw `OutcomeRecord` never leaves Layer C.

### Flow 2 — Recommendation review signal (stub wired)
```
Human edits Agent 5/6 output
  → ReviewFeedbackCapture.capture_*_feedback()
  → RecommendationReview appended to PlaybookEntry.recommendation_reviews
  → Agent 9 detect_playbook_update_candidates() surfaces entries with 2+ legal EDITED reviews
  → (Phase 3) notification to Sandelin for approval
```
`RecommendationReview.abstraction_status` prevents double-processing.

**Control invariant:** No agent autonomously updates playbook positions. Human approval
(Sandelin) required for any position change. Agent 9 surfaces candidates only.

*Sources: `acp/schemas/playbook_schemas.py` lines 25–33, 126–209;
`acp/layer_b/agents/review_feedback_capture.py`;
`acp/layer_b/agents/portfolio_aggregator.py` lines 186–216.*

---

## 9. TWO-TIER EVIDENCE MODEL

### Tier 1 — Verified (closed agreements only)
Evidence from agreements that have been executed. Highest confidence.

Current Tier 1 inventory:
- **MPI Morheat MPA** — no-redline baseline (accepted Antora template verbatim)
- **MCM PO T&Cs** — 4-round negotiated agreement, closed May 6, 2026

**Zero executed MEPAs as of 2026-05-31.** The first MEPA close is a major calibration
event — all MEPA pilot entries will be updatable to Tier 1 at that point.

### Tier 2 — Provisional (redline feedback)
Evidence from Jeff/Sandelin redline feedback sessions. Not yet validated by a closed deal.
`evidence_tier: provisional` in playbook entry YAML.

**This is an epistemic flag, not a quality flag.** Provisional positions represent
considered legal judgment; they are not guesses. They require upgrade to Tier 1 on
the first closed agreement matching the clause type.

`ClauseRecommendation.evidence_source` encodes tier inline:
`"<entry_id> | verified | <desc>"` or `"<entry_id> | provisional | <desc>"`.
`resolve_confidence_tier()` reads this string to assign `LrsConfidenceTier`.

*Sources: `acp/layer_b/agents/redline_analysis.py` lines 82–91;
`docs/architecture/pilot_entries/` YAML blocks.*

---

## 10. PILOT ENTRIES

Two pilot `PlaybookEntry` instances authored and committed:

| File | Entry ID | Clause | Negotiability | evidence_tier |
|---|---|---|---|---|
| `docs/architecture/pilot_entries/mepa_lol_direct_damages.md` | `mepa.limitation_of_liability.direct_damages_clarification` | §8.3 LoL direct damages | `signature_blocker` | `provisional` |
| `docs/architecture/pilot_entries/mepa_warranty_warranty_period.md` | `mepa.warranty.warranty_period` | §6.1(vi) warranty period | `parametric` | `provisional` |

Both entries:
- `evidence_tier: provisional` — sourced from Jeff/Sandelin MEPA redline feedback, May 2026
- `antora_response` 3-part block populated (rejection, compromise, acceptance states)
- JST §8.3 positions (supersede original broad-list template language)
- Status: "Draft, pending Sandelin review"

**Both require update to Tier 1 on the first executed MEPA close.**

*Sources: `docs/architecture/pilot_entries/mepa_lol_direct_damages.md` lines 1–5, 259;
`docs/architecture/pilot_entries/mepa_warranty_warranty_period.md` line 272.*

---

## 11. DRY-RUN HARNESS

**Location:** `scripts/real_redline_dry_run/`

**Purpose:** End-to-end test harness that runs a synthetic counterparty-redlined document
through all 9 ACP Layer B agents and verifies all expected output artifacts are produced.

**Run:** `python3 scripts/real_redline_dry_run/run.py` from repo root.

### Modification patterns (7 total)

| Pattern | Clause | Description |
|---|---|---|
| `payment_terms` | 2.9 | accepted_with_addition (liability cap + gross negligence carve-out) |
| `payment_delay` | 3.2 | modified: net-30 → net-45 |
| `termination_notice` | 4.4 | modified: 60-day → 30-day notice |
| `indemnity_deletion` | 6.1 | deleted: removes mutual indemnification |
| `force_majeure_expansion` | 7.2 | modified: expands FM to include supply chain disruptions |
| `warranty_period_shortening` | 5.1 | modified: 36-month → 12-month warranty *(pilot entry pattern)* |
| `lol_direct_damages_expansion` | 8.3 | modified: expands direct damages to production loss *(pilot entry pattern)* |

Patterns 1–5 are synthetic. Patterns 6–7 map to authored pilot `PlaybookEntry` instances
via `PilotEntryLoader`. Content mismatch with base MEPA template is intentional — these
patterns exercise playbook lookup and confidence tier rendering, not template fidelity.

### Architecture
- In-memory SQLite ledger (`:memory:`) — no persistent database
- File-backed storage adapter — artifacts written to timestamped output directory
- Stub LLM functions — deterministic, rule-based, no API key required
- Agents 1–3 seeded directly; pipeline starts at Agent 4 (Structural Diff)
- `PilotEntryLoader` wired — `playbook_grounded` and `evidence_source` correctly
  populated for clause references "5.1" and "8.3"

### Expected output artifacts (8 files per run)

| File | Producer |
|---|---|
| `counterparty_redline.md` | harness |
| `structural_diff.json` | Agent 4 |
| `redline_analysis.json` | Agent 5 |
| `counter_proposals.json` | Agent 6 |
| `lrs_v1.md` | Agent 7 |
| `lrs_v1_metadata.json` | Agent 7 |
| `audit_log.json` | all agents |
| `run_manifest.json` | harness |

Run outputs are gitignored. Only `outputs/.gitkeep` is tracked.

*Source: `scripts/real_redline_dry_run/README.md`; `scripts/real_redline_dry_run/mock_redline_generator.py` lines 80–162.*

---

## 12. TEMPLATE READ-ONLY RULE

**All legal template and pilot content files are read-only. Absolutely mandatory.**

Files that must never be modified by dev process, harness, agents, schema changes, or
any automated tool:

- `scripts/real_redline_dry_run/inputs/sample_mepa_base.md`
- `docs/architecture/pilot_entries/mepa_lol_direct_damages.md`
- `docs/architecture/pilot_entries/mepa_warranty_warranty_period.md`
- Any file in `acp/layer_c_antora/` that represents a legal template or position doc
- Any `TemplateRegistry`-referenced file

**Sandelin controls versioning** of all template and position content. The dev team
reads these files; it never writes them.

This rule is mandatory, not advisory. Do not include these in "DO NOT TOUCH" lists
as optional — they are always off-limits.

---

## 13. DISCIPLINE CHECK

**File:** `acp/discipline_check.py`

**Per:** Architecture Spec v2.4 Section 13.7

**Run:** `python3 acp/discipline_check.py` — must output `DISCIPLINE CHECK PASSED` (4/4)
before every commit to a feature branch.

### Four checks

| # | Check | Pass condition |
|---|---|---|
| 1 | Layer B import boundary | No file in `acp/layer_b/` imports from `layer_c_antora` |
| 2 | Antora-specific strings | No file in `acp/layer_b/` contains any string from `ANTORA_FORBIDDEN` |
| 3 | Required adapter interfaces | `acp/layer_b/core/adapters/ledger_adapter.py` and `audit_adapter.py` both exist |
| 4 | `workflow_id` at emit sites | Every `StateEvent(...)` and `NegotiationRow(...)` constructor call includes `workflow_id` |

### ANTORA_FORBIDDEN list (from `discipline_check.py` lines 21–68)

Specific people: `"Vincent Calianno"`, `"Sandelin Sikes"`, `"Ranjeet Mankikar"`,
`"Tom Butler"`, `"Emily Wang"`, `"Mugdha Thakkar"`

Specific suppliers: `"Texas Transformers"`, `"MCM Engineering"`, `"Federal Pacific"`,
`"Nanez"`, `"JL Precision"`, `"Bizlink"`, `"nVent"`, `"Shermco"`, `"Cummins"`,
`"Hitachi"`, `"Toshiba"`, `"Virginia Transformer"`, `"MPI Morheat"`, `"Areias"`, `"Xometry"`

Channel/folder IDs: `"C0ASTTRRF47"`, `"C0ATR4S9WCS"`, `"1Ekb76OLfHKxj3SuBN3jANgDS_Nn5scyR"`

Email/domain: `"@antora.energy"`, `"antora.energy"`, `"vincent.calianno"`

Domain-leaking field names: `"gmail_thread_id"`, `"gmail_message_id"`, `"drive_folder_path"`, `"drive_path"`

Domain-leaking role names: `"owner_scm"`, `"last_antora_version_sent"`, `"lrs_status"`, `"last_lrs_sent_date"`

**Antora-specific role and contract terminology:**
- `"SCM"` — Antora role name; use `"owner"` or `"tenant owner"` in Layer B
- `"supplier"` — Antora domain term; use `"counterparty"` in Layer B
- `"vendor"` — synonym for supplier; use `"counterparty"` in Layer B
- `"MEPA"` — Antora contract type; use `"generic-agreement"` in Layer B tests
- `"MPA"` — Antora contract type; use `"generic-agreement"` in Layer B tests

**Key implication:** `capture_scm_feedback` was renamed to `capture_owner_feedback`
because "SCM" is in `ANTORA_FORBIDDEN`. "MEPA" is forbidden in Layer B — all Layer B
tests use `"generic-agreement"` as the contract type string.

*Source: `acp/discipline_check.py` lines 1–247.*

---

## 14. PHASE ROADMAP

### Phase 1 — Complete
All 9 agents built, tested, and discipline-clean.
HEAD: `3301690`, 470 tests passing, discipline 4/4.

Includes:
- All 9 agent implementations in `acp/layer_b/agents/`
- All schema entities in `acp/schemas/playbook_schemas.py`
- `PilotEntryLoader` in `acp/layer_b/loaders/`
- `ReviewFeedbackCapture` with Gate 1/2 methods
- `detect_playbook_update_candidates()` stub in Agent 9
- Dry-run harness with 7 patterns including 2 pilot-entry patterns
- Two pilot `PlaybookEntry` documents in `docs/architecture/pilot_entries/`

### Phase 2a — BLOCKED
**Hard blocker:** Sandelin IP/confidentiality conversation not yet scheduled.
Agenda covers `docs/layer_c_wiring_plan.md` §9 + Q1–Q9, including:
- Q8: MPA/MEPA warranty gap (18-month MPA vs 3-year MEPA standard)
- Q9: Governing law conflict (CA/JAMS vs Delaware)

Items blocked until this conversation happens:
- `playbook_loader` (reads YAML from `layer_c_antora/playbook/`)
- `skill_loader`
- `prompt_registry`
- Overlay resolver
- Live adapters: Gmail (`InboxAdapter`), Google Drive (`StorageAdapter`), Slack, Anthropic SDK

### Phase 2b — In progress (2 pilot entries committed)
Pilot entry authoring in `docs/architecture/pilot_entries/`.
Sprint 1 target: MEPA §2.3 DDP (direct damages provision).
**Requires:** Ontology lock first (see §15).

### Phase 3+ — Schema designed, execution deferred
Learning loop execution (Flow 1 + Flow 2). Schema designed in Phase 1.
`OutcomeRecord` and `RecommendationReview` structures are complete.
Notification wiring for Agent 9 candidates is a Phase 3 TODO.

*Source: `docs/layer_c_wiring_plan.md` lines 1–7; `acp/layer_b/agents/portfolio_aggregator.py` line 204.*

---

## 15. OPEN BLOCKERS

### Hard gate: Sandelin IP conversation
Not yet scheduled as of 2026-05-31. Required before Phase 2a live adapter wiring.
Agenda: `docs/layer_c_wiring_plan.md` §9 + Q1–Q9.
Key questions: Q8 (warranty gap 18mo vs 3yr), Q9 (governing law CA/JAMS vs Delaware).
Nothing in Phase 2a can proceed until this conversation happens and positions are locked.

### Ontology lock
`docs/architecture/ontology.md` — not yet written.
Required before Sprint 1 mass authoring of pilot entries (Phase 2b).
Without a locked ontology, pilot entry IDs and category taxonomy are unstable.

### PROJECT_CONTEXT.md
This file — was not present before this session. Written from repo evidence 2026-05-31.

---

## 16. AGENT 9 PORTFOLIO AGGREGATOR

### detect_playbook_update_candidates()
- **File:** `acp/layer_b/agents/portfolio_aggregator.py`, line 186
- **Status:** Implemented (stub — not yet wired to notification system)
- **Logic:** Scans `PlaybookEntry.recommendation_reviews` for entries with 2 or more
  `EDITED` reactions where `reviewer_role.startswith("legal:")`.
- **Returns:** `list[tuple[str, int, str]]` — `(entry_id, edit_count, sample_rationale)`
  for each qualifying entry. `sample_rationale` is from the first qualifying EDITED review.
- **Does NOT update the playbook.** Surfaces candidates for Sandelin's review only.
- **Phase 3 TODO** at line 204: wire to notification system.

Multiple legal edits on the same clause type are the strongest learning signal that
the playbook position needs recalibration. This function makes that signal visible.

*Source: `acp/layer_b/agents/portfolio_aggregator.py` lines 186–216.*

---

## 17. KEY DEVIATIONS FROM SPEC

These deviations are real and affect how code must be written. Do not rely on spec
documents alone — verify against the actual files listed here.

### 1. ClauseRecommendation location
**Spec says:** `playbook_schemas.py`
**Actual:** `acp/layer_b/agents/redline_analysis.py`, line 59
**Impact:** Any prompt spec that imports or references `ClauseRecommendation` from
`playbook_schemas.py` is wrong. Use `redline_analysis.py`.

### 2. capture_scm_feedback renamed
**Old name:** `capture_scm_feedback`
**New name:** `capture_owner_feedback` (`review_feedback_capture.py`, line 45)
**Reason:** "SCM" is in `ANTORA_FORBIDDEN`. Discipline check fails if the old name is used.

### 3. acp/schemas/ directory
Created in commit `bcf3015`. Did not exist before that commit.
Prior code that referenced schema classes directly from `layer_b/` is now wrong.
Import from `acp.schemas.playbook_schemas`.

### 4. acp/layer_b/loaders/ package
Created in commit `cc36858`. New package — did not exist before.
Contains: `__init__.py`, `pilot_entry_loader.py`.

### 5. AntoraResponse canonical location
Canonical definition is `acp/schemas/playbook_schemas.py`, line 77.
`redline_analysis.py` imports from there. Do NOT redefine in any agent.

---

## 18. SESSION DISCIPLINE

Rules for working in this repo. Non-negotiable.

### One session at a time
One active Claude Code session. Sequential prompts in the same session are preferred
over parallel sessions (shared branch, shared test suite).

### Gate before every commit
```bash
python3 acp/discipline_check.py       # must be 4/4 PASS
python3 -m pytest acp/layer_b/tests/ -q  # must be 470+ passed
```
Both must pass before `git commit`. No exceptions.

### Template files are read-only — always mandatory
All files listed in §12 are off-limits. Never pass them in "DO NOT TOUCH" lists
as optional — treat them as permanently immutable from the dev side.

### Layer discipline
- Never add Antora-specific strings to `acp/layer_b/` code.
- Never import from `layer_c_antora` in any `layer_b/` file.
- Never use `"counterparty"` synonyms (`"supplier"`, `"vendor"`) in Layer B.
- Never use contract type names (`"MEPA"`, `"MPA"`) in Layer B tests.
- Use `"generic-agreement"` as the contract type string in all Layer B test fixtures.

### Terminology
In Layer B code and tests: `"counterparty"` (never `"supplier"` or `"vendor"`).
In Layer B code and tests: `"owner"` or `"tenant owner"` (never `"SCM"`).
In Layer B code and tests: `"generic-agreement"` (never `"MEPA"` or `"MPA"`).

### Do not touch
- Legal template files (§12)
- Files under `scripts/real_redline_dry_run/inputs/`
- Files in `docs/architecture/pilot_entries/`
- Any `.md` representing a contract template or position document
- Any existing passing test
