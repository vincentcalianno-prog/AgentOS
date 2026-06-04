## Session Decisions — 2026-06-03 (Workflow #2 Scoping + Scaffold Sprint)

### Commit landed
`9ecc73e` on `feature/acp-phase1-migration` — 41 files, 1441 insertions.
discipline_check 4/4, 624 tests green.

### Architecture decisions (locked)

**D1 — po-agent-* launchd jobs: downstream-first.**
Workflow #2 layers intelligence on top of existing po-agent-ingest and
po-agent-followup. No subsumption in this sprint. Subsume is the right
eventual move; not the first move.

**D2 — rtbellc.com governance: confirmed non-blocking.**
adam.panzer@rtbellc.com is a known, governed counterparty. Past Due report
data already leaves Antora regardless of LLM egress. Not a new exposure
category. Proceed.

**D3 — PlaybookConfig → KnowledgeConfig (platform finding).**
Cat 3 deployment config renamed. PlaybookConfig was contract-negotiation
artifact; KnowledgeConfig is the workflow-agnostic slot. PlaybookEntry,
playbook_loader, PlaybookLoader unchanged — those are Workflow #1 domain
objects, correctly named.

**D4 — playbook_loader relocated Layer B → Layer C.**
acp/layer_b/loaders/playbook_loader.py → acp/layer_c_antora/loaders/playbook_loader.py.
Abstract KnowledgeLoader ABC added to layer_b/loaders/knowledge_loader.py.
PlaybookLoader now subclasses KnowledgeLoader. Two test files moved to
layer_c_antora/tests/ to preserve discipline_check 4/4.

**D5 — No playbook schema for Workflow #2.**
Report triage knowledge is plain YAML config (column maps, grain, owner
rules, thresholds) — not negotiation postures. PlaybookEntry shape is wrong
for this domain. Report configs live in layer_c_antora/report_triage/reports/.

**D6 — One Triage/Summarization agent (Layer C cell).**
Action Drafting is template-first; LLM path only if template output is
demonstrably insufficient. Everything else (parser, normalizer, tracker,
fanout) is deterministic Layer B engine. Escalation is rule-based, not
an agent.

**D7 — entity_name field (not vendor).**
"vendor" is in ANTORA_FORBIDDEN. Generic portable term is entity_name.
Layer C column_map translates whatever the report calls it into entity_name.
discipline_check.py not modified.

**D8 — Google Sheets storage: two tabs, one workbook.**
Action Tracker tab (mutable, open items) + Repository tab (append-only,
resolved items). Supply chain team can manually edit Action Tracker.
Workbook ID loaded from ANTORA_SHEETS_WORKBOOK_ID env var — never committed.
sheets_ledger.py not modified (Workflow #1 only). GAP flags in
sheets_tracker_adapter.py: upsert and append methods need implementation.

**D9 — Conflict detection: Option C.**
If human_status_override = manually_closed AND item still on current report
→ set conflict_flag=True, write conflict_detail, status=conflict.
Agent never resolves conflict autonomously. human_notes and
human_status_override are agent-immutable fields in Layer B.

### Files created this session (key paths)
- acp/layer_a/behaviors/report_triage_lifecycle.md — behavioral contract
- acp/layer_b/loaders/knowledge_loader.py — abstract KnowledgeLoader ABC
- acp/layer_b/report_triage/ — engine skeleton (8 files)
- acp/layer_c_antora/loaders/playbook_loader.py — relocated from Layer B
- acp/layer_c_antora/report_triage/ — config skeleton (10 files incl. storage)
- acp/layer_c_antora/tests/ — new test home for Layer C tests
- scripts/report_triage_dry_run/run.py — dry-run harness skeleton
- tests/fixtures/report_triage/ — sanitized/ kept, real/ gitignored
- .env.example — ANTORA_SHEETS_WORKBOOK_ID placeholder

### Known follow-up items (next sprint gates)
1. Fill Layer C YAML configs: match_sender/match_subject per report,
   item_key_fields, column_map, owner_field, staleness thresholds.
   Needs: Jerome's email/subject for Instance A; Past Due subject pattern.
2. Implement sheets_tracker_adapter.py (upsert + append methods).
3. Build Layer B parser.py — SpreadsheetML XML-2003 path is highest
   technical risk; de-risk first with real fixture.
4. Create sanitized fixtures for both reports (scrubbed vendor names,
   amounts, memos). Keep real copies in git-ignored local dir.
5. Confirm Past Due report cadence (currently "per its schedule" in §2).
6. Fill owners.yaml with actual buyer roster + fallback rules.
7. Sandelin IP/confidentiality conversation — still the longest lead item
   for Phase 2a; do not defer indefinitely.
