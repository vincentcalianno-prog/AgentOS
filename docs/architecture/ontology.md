# ACP Ontology — Playbook Taxonomy and Entry ID Specification

**Status:** LOCKED  
**Locked date:** 2026-05-31  
**Authority:** This document is the normative reference for all playbook entry IDs, category names, and contract type codes. Once locked, entry IDs and category structure do not change without an explicit ontology revision recorded here.

> **Why this matters:** PlaybookEntry `id` values are the join key between authored YAML, `PilotEntryLoader.CLAUSE_TO_PILOT`, and `ClauseRecommendation.evidence_source` strings. Renaming an entry ID after authoring breaks all three surfaces simultaneously. Lock the taxonomy before authoring begins.

---

## 1. Purpose and Status

This document locks the identifier taxonomy before Sprint 1 mass playbook authoring. It is derived exclusively from committed repo files as of 2026-05-31. Sources:

- `docs/architecture/pilot_entries/mepa_lol_direct_damages.md` — first pilot entry
- `docs/architecture/pilot_entries/mepa_warranty_warranty_period.md` — second pilot entry
- `acp/schemas/playbook_schemas.py` — `PlaybookEntry` dataclass field definitions
- `acp/layer_b/loaders/pilot_entry_loader.py` — `CLAUSE_TO_PILOT` and `_PILOT_ENTRIES`
- `scripts/real_redline_dry_run/` — harness modification patterns (clauses 2.9, 3.2, 4.4, 6.1, 7.2)
- `docs/layer_c_wiring_plan.md` — playbook structure, skill taxonomy
- `docs/PROJECT_CONTEXT.md` — phase roadmap, Sprint 1 targets

**Locked sections:** Entry ID format (§2), Contract Types (§3), Category Taxonomy (§4), Sub-Clause Naming Rules (§5).  
**Reference sections:** Cross-Clause Dependency Rules (§6), Overlay Axis Rules (§7), Sprint 1 Authoring Sequence (§8).

---

## 2. Entry ID Format

### Structure

```
<contract_type_id>.<category_id>.<sub_clause_id>
```

Three dot-separated segments. All lowercase. No spaces. No hyphens within segment names. Underscores are used within segments where multi-word names are needed.

### Confirmed examples (from committed pilot entries)

| Entry ID | contract_type_id | category_id | sub_clause_id |
|---|---|---|---|
| `mepa.limitation_of_liability.direct_damages_clarification` | `mepa` | `limitation_of_liability` | `direct_damages_clarification` |
| `mepa.warranty.warranty_period` | `mepa` | `warranty` | `warranty_period` |

### Schema mapping

`PlaybookEntry` in `acp/schemas/playbook_schemas.py` (lines 177–180) declares:

```python
id: str = ""                # composite: <contract_type_id>.<category_id>.<sub_clause_id>
contract_type_id: str = ""  # first segment
category_id: str = ""       # second segment
sub_clause_id: str = ""     # third segment
```

These are plain string fields — no enum enforcement at the schema level. This ontology document is the normative reference. The schema validates structure; the ontology validates vocabulary.

### Immutability rules

- Entry IDs **must not be renamed** after any of the following reference them:
  - `PilotEntryLoader.CLAUSE_TO_PILOT` (maps clause reference → pilot name)
  - `PilotEntryLoader._PILOT_ENTRIES` (maps pilot name → `PilotEntryRef.entry_id`)
  - `ClauseRecommendation.evidence_source` strings (format: `"<entry_id> | <tier> | <desc>"`)
  - `PlaybookEntry.related_entries` lists in other authored entries
  - `CrossClauseDependency.involved_entries` lists
- If a rename is required: update all four surfaces atomically in a single commit with an ontology revision note in this document.

---

## 3. Contract Types

Seven contract type codes are registered. These are the only valid values for `contract_type_id` in `PlaybookEntry`.

| Code | Full Name | Typical use at Antora |
|---|---|---|
| `mepa` | Master Equipment Purchase Agreement | Primary equipment procurement; long-term supplier relationships; highest clause complexity |
| `mpa` | Master Purchase Agreement | Commodity and component procurement; lighter clause set than MEPA |
| `nda` | Non-Disclosure Agreement | Pre-engagement IP protection; occasionally embedded within MEPA as a standalone exhibit |
| `msa` | Master Services Agreement | Service providers; engineering, testing, installation contractors |
| `po` | Purchase Order | Single-transaction procurement; governed by MEPA or MPA T&Cs when in place |
| `sow` | Statement of Work | Scope exhibit attached to MSA or MEPA; defines deliverables, milestones, acceptance criteria |
| `mou` | Memorandum of Understanding / Letter of Intent | Pre-contract commercial alignment; not a binding agreement on its own |

**Sprint 1 priority:** `mepa` and `mpa` are the primary authoring targets. `nda`, `msa`, `po`, `sow`, `mou` entries are lower priority and will be authored after MEPA/MPA coverage reaches a baseline threshold.

**MEPA/MPA gap note (open item):** The warranty period baseline differs between MEPA (3-year standard) and MPA (18-month standard). Q8 in `docs/layer_c_wiring_plan.md` §9 must be resolved with Sandelin before MPA warranty entries are authored. Do not author `mpa.warranty.*` entries until that conversation occurs.

---

## 4. Category Taxonomy

Categories form the second segment of the entry ID. They group clauses by commercial subject matter, not by template section number (section numbers change across template versions; categories are stable).

The following twelve categories are defined for Sprint 1 MEPA coverage. The two pilot entries confirm `warranty` and `limitation_of_liability`. The remaining ten are confirmed from harness modification patterns, pilot entry carve-out references, wiring plan skills, and project context documents (see §1 source list).

### 4.1 `delivery`

Delivery terms, risk of loss transfer, DDP (Delivered Duty Paid) obligations, inspection and acceptance milestones, scheduling. Sections typically in Article 2 of the MEPA template.

*Repo evidence:* Harness template §2.3 "Delivery Obligations"; `docs/PROJECT_CONTEXT.md` §14 "Sprint 1 target: MEPA §2.3 DDP."

### 4.2 `payment`

Payment terms (net-N), invoicing requirements, milestone payment schedules, late payment interest, early-pay discounts. Sections typically in Articles 2–3.

*Repo evidence:* Harness patterns `payment_terms` (clause 2.9) and `payment_delay` (clause 3.2); `docs/layer_c_wiring_plan.md` §2a example YAML (`clause_ref_pattern: "^(2\\.\\d+|3\\.\\d+)"`).

### 4.3 `warranty`

Warranty period duration, trigger event (shipment vs. acceptance), warranty scope and exclusions, remedy hierarchy during warranty, no-cost repair/replacement obligations. **Pilot entry authored.**

*Repo evidence:* `docs/architecture/pilot_entries/mepa_warranty_warranty_period.md` (`category_id: warranty`). Harness pattern `warranty_period_shortening` (clause 5.1).

### 4.4 `limitation_of_liability`

Aggregate cap on total liability (LoL amount), exclusion of consequential/indirect/special damages, carve-outs from the cap (IP, indemnity, BI/PD, fraud, willful misconduct), direct damages clarification, sub-cap structure. **Pilot entry authored.**

*Repo evidence:* `docs/architecture/pilot_entries/mepa_lol_direct_damages.md` (`category_id: limitation_of_liability`). Harness pattern `lol_direct_damages_expansion` (clause 8.3). Uncapped carve-outs referenced throughout pilot entry §8.1 guidance.

### 4.5 `indemnification`

Mutual vs. unilateral indemnification, defense obligations, IP infringement indemnity, third-party claim procedures, indemnification caps and uncapping interaction with LoL.

*Repo evidence:* Harness pattern `indemnity_deletion` (clause 6.1); `docs/layer_c_wiring_plan.md` §2b skill `clause-analysis-liability.md` ("indemnification, limitation-of-liability").

### 4.6 `intellectual_property`

IP ownership (work-for-hire vs. license), background IP licenses, foreground IP developed under the agreement, open-source compliance obligations. Interacts with the LoL cap carve-out for IP claims.

*Repo evidence:* Pilot entry `mepa_lol_direct_damages.md` §8.1 guidance: "Uncapped carve-outs: ... IP and confidentiality obligations."

### 4.7 `confidentiality`

NDA provisions embedded within MEPA, definition of Confidential Information, exclusions (publicly available, independently developed), survival period, permitted disclosure.

*Repo evidence:* Pilot entry `mepa_lol_direct_damages.md` §8.1 guidance: "Uncapped carve-outs: ... IP and confidentiality obligations." `docs/layer_c_wiring_plan.md` §1 explicitly lists confidentiality as a carve-out surface.

### 4.8 `term_and_termination`

Contract duration (fixed term vs. evergreen), renewal terms, termination for convenience (notice period), termination for cause, suspension rights, effect of termination (surviving obligations).

*Repo evidence:* Harness pattern `termination_notice` (clause 4.4, "60-day → 30-day notice").

### 4.9 `force_majeure`

Force majeure definition scope, qualifying events, exclusions (supply chain disruptions, price changes), notice requirements, mitigation obligations, extended FM triggers for termination rights.

*Repo evidence:* Harness pattern `force_majeure_expansion` (clause 7.2, "expands FM to include supply chain disruptions").

### 4.10 `insurance`

Required insurance coverages (CGL, workers comp, auto, umbrella), minimum limits, certificate of insurance requirements, additional insured obligations, waiver of subrogation. Interacts with LoL cap: bodily injury and property damage claims are typically uncapped.

*Repo evidence:* Pilot entry `mepa_lol_direct_damages.md` §8.1 guidance: "Uncapped carve-outs: ... claims for bodily injury or property damage." Insurance carve-out structure implies a corresponding coverage requirement clause.

### 4.11 `dispute_resolution`

Governing law, arbitration vs. litigation, venue, JAMS vs. AAA rules, pre-arbitration escalation tiers (negotiation → mediation → arbitration), provisional remedies.

*Repo evidence:* `docs/PROJECT_CONTEXT.md` §15 Open Blockers: "Q9: Governing law conflict (CA/JAMS vs Delaware)" — Sandelin meeting required to resolve MEPA governing law position before authoring this category.

> **Authoring note:** Do not author `mepa.dispute_resolution.*` entries until Q9 is resolved with Sandelin. Governing law and venue are subject to active open question.

### 4.12 `general`

Definitions, notices (method and address requirements), entire agreement / integration clause, amendment procedures, waiver, assignment (including change of control), severability, counterparts. Catch-all for clauses without a dedicated category.

*Repo evidence:* MEPA template Article 1 "Definitions and Interpretation" (§1.1–§1.5); standard MEPA structure confirmed by template fixture.

---

## 5. Sub-Clause Naming Rules

Sub-clause IDs are the third segment of the entry ID. They name the specific commercial issue a `PlaybookEntry` addresses within its category.

### Rules

1. **All lowercase, underscores only.** No hyphens. No spaces. No section numbers.
2. **Noun phrase, not verb phrase.** Name the issue, not the action.
   - Correct: `direct_damages_clarification`, `warranty_period`, `aggregate_cap`
   - Avoid: `clarify_direct_damages`, `set_warranty_period`
3. **Name for the dominant commercial risk**, not the clause title. If §8.3 is titled "Special Damages" in some templates but the risk is recharacterization of direct damages, name it `direct_damages_clarification`.
4. **Section numbers are not sub-clause IDs.** Section numbers change across template versions. Sub-clause IDs are version-stable.
5. **One entry per distinct commercial position.** If two sub-issues within a clause require materially different positions (e.g., the LoL cap amount and the cap exclusions are different negotiation surfaces), author two separate entries.
6. **Unique across all entries with the same contract_type_id and category_id.** Two entries in the same category cannot share a sub_clause_id.

### Confirmed examples

| sub_clause_id | Clause | What it names |
|---|---|---|
| `direct_damages_clarification` | §8.3 | The three-category restriction on what counts as direct damages (JST-calibrated) |
| `warranty_period` | §6.1(vi) | Duration and trigger event for the supplier warranty |

### Planned sub-clause IDs for Sprint 1 (not yet authored)

These are reserved identifiers derived from the authoring sequence in §8. Do not use these strings for a different commercial issue.

| Planned entry ID | Commercial issue |
|---|---|
| `mepa.delivery.ddp_terms` | Delivered Duty Paid obligation scope and exceptions |
| `mepa.delivery.risk_of_loss` | When title and risk transfer from supplier to Antora |
| `mepa.delivery.inspection_acceptance` | Acceptance milestone definition and timeline |
| `mepa.payment.net_terms` | Net payment window (net-30 baseline, net-45 floor) |
| `mepa.payment.invoicing_requirements` | Invoice format, supporting documentation requirements |
| `mepa.payment.late_payment_interest` | Late fee rate and calculation basis |
| `mepa.warranty.scope_and_exclusions` | What the warranty covers and what voids or limits it |
| `mepa.warranty.remedy_hierarchy` | Repair → replace → refund sequencing and timelines |
| `mepa.limitation_of_liability.aggregate_cap` | §8.1 total cap amount and fallback floors |
| `mepa.indemnification.third_party_claims` | Mutual indemnity obligation scope and defense procedures |

---

## 6. Cross-Clause Dependency Rules

### When to create a CrossClauseDependency

Create a `CrossClauseDependency` when two or more `PlaybookEntry` instances interact such that accepting a counterparty position on one without considering the other creates a commercially dangerous exposure that neither clause analysis catches in isolation.

**Test:** "If we negotiated these two clauses in separate rounds, or in separate documents (e.g., MEPA and a standalone PO), would a favorable position on one mask an adverse position on the other?" If yes, create a dependency.

### Confirmed examples from pilot entries

| Dependency ID | Involved entries | Type | Risk |
|---|---|---|---|
| `consequential_exclusion_plus_direct_damages_clarification` | `mepa.limitation_of_liability.disclaimer_of_certain_damages` + `mepa.limitation_of_liability.direct_damages_clarification` | `requires_consistency` | MCM cross-document attack: accepting mutual consequential exclusion in PO T&Cs while LoL clause lacks direct-damages carve-out |
| `warranty_period_anchors_downstream_obligations` | `mepa.warranty.warranty_period` + `mepa.warranty.service_period` + `mepa.warranty.repairs_remedies` + `mepa.warranty.spare_parts_availability` | `requires_consistency` | Shortening warranty period silently shortens service period, spare parts availability, and no-cost remedy window |

### `interaction_type` values

| Value | Meaning |
|---|---|
| `mutual_dependency` | Both clauses must be in place; either clause is commercially ineffective without the other |
| `mutual_exclusion` | Accepting the position on one clause bars the position on the other — they cannot both hold |
| `requires_consistency` | Language in both clauses must be consistent; they do not require each other but cannot conflict |

### Authoring rules

- Document dependencies at authoring time, not retroactively. When authoring a new entry, check every existing entry in the same category for potential interaction.
- Minimum check: within-category scan. Extended check: cross-category scan when LoL, indemnification, or insurance entries are involved (these categories interact frequently).
- Do not add a `detection_pattern` field. The LLM performs semantic consistency checking at analysis time; hard-coded pattern matching is fragile across template versions.
- `CrossClauseDependency` records are authored in the same pilot entry file as the primary `PlaybookEntry`. Standalone dependency files are not required unless the dependency spans entries authored separately.

---

## 7. Overlay Axis Rules

Three overlay axes are hardcoded: `counterparty`, `project`, `commodity`.

### When to add an overlay

Add a `PlaybookOverlay` when Antora takes a materially different negotiating position based on a specific axis value. Most clauses are policy-uniform across the Antora supply base — overlays are the exception, not the default.

**Decision test:** "Would we negotiate this clause differently with a strategic sole-source supplier vs. a commodity supplier with multiple alternatives?" If yes, `counterparty` overlay candidate. "Does this clause apply differently to high-BOP-impact equipment vs. standard components?" If yes, `project` or `commodity` overlay candidate.

### Axis definitions

| Axis | When to use |
|---|---|
| `counterparty` | Antora's position on this clause shifts based on who the counterparty is (e.g., sole-source strategic supplier vs. commodity supplier, or a counterparty with a known negotiation pattern like the MCM cross-document attack) |
| `project` | Position shifts based on project characteristics (e.g., customer-facing project with pass-through LDs vs. internal procurement) |
| `commodity` | Position shifts based on what is being procured (e.g., transformers vs. switchgear vs. services; different risk profiles require different warranty or LoL floors) |

### Fourth axis

A fourth axis is deferred. Do not add one until Sprint 1 authoring produces evidence that the three defined axes are insufficient to capture a material commercial distinction.

---

## 8. Sprint 1 Authoring Sequence

Recommended authoring order after the two committed pilot entries. Clusters are ordered by negotiation frequency — delivery clauses are redlined in nearly every MEPA; general/admin clauses are rarely contested.

### Committed (pre-Sprint 1)

| Entry ID | Category | Status |
|---|---|---|
| `mepa.limitation_of_liability.direct_damages_clarification` | `limitation_of_liability` | Committed — provisional, pending Sandelin review |
| `mepa.warranty.warranty_period` | `warranty` | Committed — provisional, pending Sandelin review |

### Sprint 1 Cluster A — Delivery (highest negotiation frequency)

| Entry ID | Notes |
|---|---|
| `mepa.delivery.ddp_terms` | §2.3; DDP scope, exclusions, cost allocation |
| `mepa.delivery.risk_of_loss` | When title and risk transfer |
| `mepa.delivery.inspection_acceptance` | Acceptance milestone definition; connects to warranty trigger |

### Sprint 1 Cluster B — Payment

| Entry ID | Notes |
|---|---|
| `mepa.payment.net_terms` | Net-30 baseline; net-45 floor; early-pay discount structure |
| `mepa.payment.invoicing_requirements` | Invoice documentation, format, submission method |
| `mepa.payment.late_payment_interest` | Late fee rate and calculation |

### Sprint 1 Cluster C — Warranty (remaining entries)

| Entry ID | Notes |
|---|---|
| `mepa.warranty.scope_and_exclusions` | What the warranty covers; void conditions |
| `mepa.warranty.remedy_hierarchy` | Repair → replace → refund sequencing |

*Note:* `mepa.warranty.service_period`, `mepa.warranty.repairs_remedies`, and `mepa.warranty.spare_parts_availability` are referenced in the `warranty_period_anchors_downstream_obligations` dependency. Author these after scope and remedy entries to allow dependency resolution.

### Sprint 1 Cluster D — Limitation of Liability and Indemnification (high commercial risk)

| Entry ID | Notes |
|---|---|
| `mepa.limitation_of_liability.aggregate_cap` | §8.1 cap amount; fallback floors; uncapped carve-out list |
| `mepa.indemnification.third_party_claims` | Mutual indemnity scope; defense procedures; interaction with LoL |

*Note:* `mepa.limitation_of_liability.disclaimer_of_certain_damages` (referenced in the `consequential_exclusion_plus_direct_damages_clarification` dependency) should be authored in Cluster D alongside `aggregate_cap` to resolve the dangling dependency reference.

### Deferred categories (post-Sprint 1)

| Category | Blocker |
|---|---|
| `mepa.dispute_resolution.*` | Q9 (governing law CA/JAMS vs. Delaware) — requires Sandelin conversation |
| `mpa.*` | Q8 (warranty gap 18-month vs. 3-year) — requires Sandelin conversation |
| `nda.*`, `msa.*`, `po.*`, `sow.*`, `mou.*` | Lower priority; begin after MEPA baseline is established |

---

## 9. Revision History

| Date | Change | Author |
|---|---|---|
| 2026-05-31 | Initial lock — derived from pilot entries, schema, harness patterns, wiring plan | Claude Code session |
