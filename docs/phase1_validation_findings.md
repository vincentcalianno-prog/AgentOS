# Phase 1 Validation Findings — Texas Transformers (TTE) Clauses 2.9, 4.5, 6.1

**Date:** 2026-05-26  
**Validator:** Vincent Calianno  
**Method:** Manual walkthrough against actual Layer B code (no LLM invocation; synthetic mocks replaced with real clause text for analysis)  
**Scope:** Agents 4, 5, 6, 7 — Structural Diff → Redline Analysis → Counter-Proposal → LRS Generator

---

## How to read this report

Each finding is categorized:

- **Cat 1 — Schema gap:** Add a field to an existing dataclass. Small fix.
- **Cat 2 — Abstraction mismatch:** Function signatures or context shapes need refactoring. Medium refactor.
- **Cat 3 — Pipeline gap:** Events, agent boundaries, or workflow needs design work. Design work needed.
- **Cat 4 — Output quality:** Layer C concern; no Layer B change required.
- **Cat 5 — Workflow doesn't fit:** The underlying model is wrong. Requires rethinking.

---

## Test Case 1 — Clause 2.9 (Hybrid modification: acceptance + contradictory insertion)

**What happened:** TTE accepted Antora's rejection-rights clause verbatim, then immediately inserted a new paragraph that nullifies it on three dimensions: (a) no rejection on technical grounds, (b) mutual-agreement veto on defect responsibility, (c) 5-day notice window.

---

### Agent 4 — Structural Diff

**Code path:** `_diff_clauses()` in `structural_diff.py`. Matching is done by `clause_reference` — clauses present in both documents are compared textually; present only in counterparty → "added"; only in outbound → "deleted".

**Would it detect the change?**

Depends entirely on how the document parser assigns references to the inserted paragraph. Two scenarios:

**Scenario A — Parser assigns the insertion a new reference (e.g., "2.9.1" or "2.9a"):**
- Clause "2.9": `change_type = "unchanged"` — original text matches, pipeline treats this as no-change.
- Clause "2.9.1": `change_type = "added"` — insertion is detected, but as a standalone new clause.
- **Problem:** The causal relationship — that 2.9.1 was inserted immediately after an accepted 2.9 and directly contradicts it — is invisible to the diff. Agent 5 would analyze 2.9.1 in isolation, with no knowledge that 2.9 exists unchanged alongside it.

**Scenario B — Parser folds the insertion into the text of clause 2.9:**
- Clause "2.9": `change_type = "modified"`, large positive `character_delta`.
- Both versions are fully captured in `original_text` / `counterparty_text`.
- **This works.** An LLM in Agent 5 can see that TTE preserved the original text and appended language that contradicts it.

**Edge case not covered:**

The diff algorithm has no notion of cross-clause semantic relationships. In Scenario A, "2.9 unchanged + 2.9.1 added" is the same structural signal as any other clause addition. The pipeline cannot represent "this added clause exists to nullify the accepted clause immediately above it." The `surrounding_context` field captures adjacent reference strings ("2.9 | 2.10"), not semantic adjacency or intent.

**Finding:** The hybrid modification pattern is correctly handled IF the document parser assigns the insertion to the same clause reference. It is silently misrepresented if the parser assigns a new reference. This is a parser fidelity concern (Layer C) but Agent 4's data model has no field to represent within-round cross-clause relationships even when the parser cooperates.

**Category: Cat 4 for the parser fidelity question. Cat 1 for the missing cross-clause context field** — a `related_clause_refs: list[str]` field on `DiffEntry` could allow the parser to express that 2.9.1 is a sub-clause of 2.9 and was inserted in the same position.

---

### Agent 5 — Redline Analysis

**Code path:** `analyze_clause(clause_reference, change_type, original_text, counterparty_text, playbook_context)` → `ClauseRecommendation`.

**What would Agent 5 need to produce a correct recommendation?**

The correct recommendation is: **reject** (confidence: high, requires_legal_review: True), with reasoning that identifies all three contradictions.

**What Agent 5 actually receives:**
- `clause_reference`: "2.9" (or "2.9.1" in Scenario A)
- `change_type`: "modified" (Scenario B) or "added" (Scenario A)
- `original_text` / `counterparty_text`: the clause text before and after
- `playbook_context`: a static string, identical for every clause in the negotiation

**What's missing:**

1. **Prior round context.** Vincent's explicit position: "This is the same language we rejected in the prior round, just re-inserted with different framing." Agent 5 has zero access to prior round analysis. The `analyze_clause` signature has no prior-round parameter. The round number is in the event payload but is **not passed to the LLM callable** — `process_event` reads it but never forwards it to `_analyze_entry`. A capable LLM could detect the insertion as problematic on its own, but cannot flag "we've seen this before; counterparty is re-inserting rejected language."

2. **Cross-clause context.** In Scenario A, Agent 5 analyzes "2.9.1" without knowing "2.9" was accepted unchanged. The relationship is invisible.

3. **Structured playbook per clause.** Whether "no technical rejection" is a hard red line vs. a negotiating position depends on Antora's playbook. The static `playbook_context` string can encode this, but it's a flat blob — there's no structure that lets the LLM reliably distinguish "this is required" from "this is preferred" for a specific clause type.

**Finding:** For Scenario B, a capable LLM in Agent 5 could likely produce a correct recommendation without prior-round context. The `original_text`/`counterparty_text` comparison makes the contradiction visible. For Scenario A, the analysis of 2.9.1 in isolation might still reach "reject" (the new paragraph is facially problematic) but would miss the historical framing. The three specific objections might all appear in reasoning, or they might not — it depends on LLM quality and playbook richness.

**Gap:** The missing `round_number` pass-through to the LLM callable is a real bug relative to design intent. The round number is available in the event and relevant to analysis quality.

**Category: Cat 2 (Abstraction mismatch)** — `analyze_clause` signature needs `round_number: int` and optionally `prior_round_context: Optional[str]` to support historical recurrence detection. **Cat 4** for playbook richness (Layer C concern).

---

### Agent 6 — Counter-Proposal Drafting

**Code path:** `draft_counter_proposal(clause_reference, recommendation, reasoning_from_analysis, original_text, counterparty_text, playbook_context)` → `CounterProposalDraft`.

**What would Agent 6 produce?**

Given `recommendation = "reject"`, `original_text = Antora's clause`, `counterparty_text = TTE's version with insertion`, Agent 6 would draft: "Delete the inserted paragraph; restore Antora's original clause 2.9 text in full." This is approximately correct.

**What's missing:**

1. **Three structured sub-objections.** The counter-text field is a single string. Vincent's position has three distinct objections to three distinct insertions within the paragraph. Agent 6 produces one `counter_text`, which could address all three in prose — but there's no structured output that maps objection to clause sub-element. For the LRS and for drafting the actual response letter, structuring the objections matters.

2. **"Restore verbatim" instruction.** For "reject" recommendations on language that should be reinstated without modification, Agent 6 should ideally be able to say "restore original verbatim" rather than LLM-generating a paraphrase of Antora's original. A paraphrase might subtly weaken the language. The current abstraction has no "restore original" flag.

3. **Tone input from operator.** The appropriate tone for this clause (TTE accepted, then immediately tried to nullify) is firm. The `tone` field in `CounterProposalDraft` is determined by the LLM — Vincent has no channel to express tone intent.

**Category: Cat 1** — add `sub_positions: list[str]` to `CounterProposalDraft` for structured multi-objection capture. **Cat 2** — add a `restore_original: bool` hint to the drafter signature for rejection cases where verbatim restoration is the correct counter. **Cat 4** for tone (Layer C playbook context can encode tone guidance).

---

### Agent 7 — LRS Generator

**Code path:** `LRSInput(negotiation_id, workflow_id, contract_type, round_number, counterparty_name, diff, analysis, counter_proposals)` → `RenderLRSFn` → `LRSOutput`.

**What the LRS would contain:**
- The diff entry for 2.9 (modified or the 2.9.1 addition)
- Agent 5's recommendation and reasoning
- Agent 6's counter_text
- `requires_legal_review` flag

**What would be missing from the LRS for legal review:**

1. **Prior round reference.** "TTE re-inserted this language after we rejected it in Round 1" is the single most important piece of context for legal and for Vincent's cover note. `LRSInput` has no `prior_round_summary` field. The renderer cannot include it because it doesn't exist anywhere in the data model.

2. **Operator position statement.** Vincent's articulated position ("The inserted paragraph directly nullifies the rejection rights TTE just accepted") is not in the pipeline. The LRS would contain Agent 5's analytical reasoning, which might or might not match Vincent's framing.

3. **Counterparty profile.** `counterparty_profile_ref` exists on `NegotiationRow` but is NOT in `LRSInput`. A renderer could tailor the LRS to known TTE behavior patterns (e.g., "TTE has a pattern of accepting clauses and inserting nullifying language") — but that information is inaccessible to Agent 7.

4. **Operational stakes.** That these are transformers, that commissioning may be weeks after delivery (making the 5-day notice window a real operational problem), that transformer defects can cause fires — none of this is in `LRSInput`. It must either be in playbook_context (and thus in Agent 5's reasoning) or it is absent from the LRS.

**Category: Cat 1** — add `prior_round_summary: Optional[str]` and `operator_position: Optional[str]` fields to `LRSInput`. These are schema additions that don't require restructuring the pipeline. **Cat 3** — prior round data needs a pipeline path into Agent 7; currently no event carries it.

---

## Test Case 2 — Clause 4.5 (Replacement with deferral language)

**What happened:** TTE deleted Antora's detailed cancellation cost clause and replaced it with: "In the event of any such termination, the cancellation terms as specified in our offer shall be applicable."

---

### Agent 4 — Structural Diff

**Would it detect the change?** Yes, correctly and cleanly. Clause "4.5" appears in both documents with different text → `change_type = "modified"`, `character_delta` strongly negative (long clause replaced by one sentence). Both texts fully captured.

**No gap for this test case.** This is the standard "replacement" pattern Agent 4 was designed for.

---

### Agent 5 — Redline Analysis

**What would Agent 5 need?**

The correct recommendation is: **reject** — this is not a counter-proposal, it is a deferral to an external document that introduces open-ended liability.

**What Agent 5 receives:** full `original_text` (Antora's detailed clause with exclusions), full `counterparty_text` (the deferral sentence). An LLM can clearly detect the asymmetry and the risk: one sentence replaces a clause with specific exclusions. This is Agent 5's strongest case.

**What's missing:**

1. **What's in TTE's offer.** The specific risk is that TTE's cancellation schedule includes overhead, G&A, and profit — the exact items Antora's clause excluded. Agent 5 cannot reason about external referenced documents. If the playbook_context says "counterparty offer cancellation terms are unknown to Antora and may include excluded cost categories," Agent 5 can flag this. But it's speculative reasoning, not informed analysis.

2. **MEPA boundary awareness.** The insight that "our offer is not part of the MEPA" is a structural legal observation. The LLM in Agent 5 might produce this, or might not — it depends on playbook quality and whether the LLM is told what documents constitute the agreement.

**Finding:** For this test case, Agent 5 would likely produce a correct recommendation with a capable LLM. The gap is in the depth of reasoning about external documents, which is a playbook richness concern.

**Category: Cat 4.** The abstraction is sufficient; the quality of Layer C playbook content determines whether the reasoning is complete.

---

### Agent 6 — Counter-Proposal Drafting

**What would Agent 6 produce?**

Given `original_text = Antora's full clause`, `counterparty_text = deferral sentence`, `recommendation = "reject"`, the ideal counter is: reinstate Antora's original language verbatim.

This is the "restore verbatim" case again. Agent 6 would LLM-generate a counter, which might restate the original clause with minor variations. The `restore_original` gap identified in Test Case 1 applies here equally.

**Category: Cat 2** (same finding as TC1 — restore verbatim mechanism missing).

---

### Agent 7 — LRS Generator

**What the LRS would contain:** The diff (modified, large negative delta), Agent 5's rejection recommendation and reasoning, Agent 6's counter-language.

**What's missing:**

1. **NegotiationRow metadata.** The LRS renderer doesn't know this is a MEPA, doesn't know the dollar value of the purchase order, doesn't know the delivery schedule (relevant to the "reasonable quantities consistent with delivery schedule" language in the original clause). These are in NegotiationRow fields (`contract_type`, `category`, `priority`) but `LRSInput` doesn't carry NegotiationRow metadata beyond `contract_type` and `counterparty_name`.

2. **Separation of "TTE's offer" context.** The LRS cannot flag "TTE referenced an external document (their offer) which is not incorporated into this MEPA and has not been reviewed" because that context is not a structured field.

**Category: Cat 1** — `LRSInput` should carry `negotiation_priority`, `estimated_value`, and a generic `operator_notes: Optional[str]` field for context that doesn't fit the automated pipeline.

---

## Test Case 3 — Clause 6.1 (Entire clause deleted)

**What happened:** TTE's document is missing the entire General Indemnity clause. No replacement language. Deletion only.

---

### Agent 4 — Structural Diff

**Would it detect the change?** Yes. Clause "6.1" appears in outbound (Antora's version), does not appear in counterparty → `change_type = "deleted"`, `original_text = full indemnity text`, `counterparty_text = ""`. This is straightforward.

**One edge case:** What if TTE renumbered the clause (e.g., TTE's equivalent of indemnity is at "7.1" or is titled differently)? Agent 4 matches by reference only. If TTE moved or renumbered the clause, it would appear as "6.1 deleted" + "7.1 added" — two separate DiffEntries — rather than a single "modified" entry. A human reviewer would recognize these as related; Agent 4 would not.

**Category: Cat 1** — `DiffEntry` could carry a `likely_renamed_from: Optional[str]` field populated by a fuzzy-match pass in the diff algorithm. Not critical for Phase 1 but relevant for renaming patterns.

---

### Agent 5 — Redline Analysis

**What would Agent 5 receive:**
- `change_type = "deleted"`
- `original_text = Antora's full indemnity clause`
- `counterparty_text = ""`

**Would it produce a correct recommendation?**

A capable LLM analyzing `change_type = "deleted"` for a clause containing the text "indemnify, hold harmless… bodily injury, personal injury, death or property damage caused by the Products" should recommend "escalate" with `requires_legal_review = True`. This is the clearest case — there is no counterparty text to evaluate.

**What's missing:**

1. **Clause criticality signal.** If the playbook_context says "6.1 General Indemnity is a required non-negotiable clause; deletion is not acceptable and requires immediate legal escalation," Agent 5 can act on it. Without this, the LLM has to infer from clause content alone that this is high-severity. A capable LLM would — the word "indemnify" in a deleted clause with `counterparty_text = ""` is unambiguous — but the pipeline has no mechanism to guarantee this.

2. **"Intentional vs. accidental" disambiguation.** Vincent explicitly raises this: "Whether the deletion was intentional or a copy-paste accident is itself a question." The current `ClauseRecommendation` schema has no field for this. An LLM might include the question in `reasoning` text, but it's not a structured output. There's no way for Agent 7 to surface this as a distinct callout in the LRS without parsing the reasoning string.

3. **Severity beyond the boolean.** `requires_legal_review` is a bool. Clause 6.1 deletion is categorically different from (say) a minor indemnity scope change. A legal reviewer needs to know this is a blocker to signature, not just a flagged item. There's no severity or blocking status field.

**Category: Cat 1** — add `severity: str` ("low" | "medium" | "high" | "critical") and `is_signature_blocker: bool` to `ClauseRecommendation`. **Cat 1** — add `intentionality_flag: Optional[str]` ("likely_intentional" | "possibly_accidental" | "unknown") for deletions.

---

### Agent 6 — Counter-Proposal Drafting

**What happens:** If Agent 5 recommends "escalate" → Agent 6 skips this clause entirely (`_DRAFTABLE_RECOMMENDATIONS = frozenset({"negotiate", "reject"})`). The LRS would carry no counter-language for 6.1.

This is **correct behavior** for Phase 1. Escalate means "human must draft the response." The pipeline should not produce counter-language for a critical clause deletion.

**One concern:** If Agent 5 recommends "reject" instead of "escalate" (reasonable for a deletion), Agent 6 would draft counter-language. For a deletion, the correct counter is "reinstate Antora's original language verbatim." Agent 6 would LLM-generate a version of the indemnity clause — which might subtly vary from the standard Antora clause. For a provision as legally precise as General Indemnity, LLM paraphrasing is a real risk.

The `restore_original: bool` gap (identified in TC1) is most critical here. For deleted clauses, the counter-proposal should always be the verbatim original, not an LLM-generated approximation.

**Category: Cat 2** (same restore_original finding — highest priority here).

---

### Agent 7 — LRS Generator

**What the LRS would contain:** Diff showing "deleted", analysis showing "escalate" + `requires_legal_review = True`, no counter-proposals section (Agent 6 skipped).

**What's missing:**

1. **Blocking status.** The LRS has `requires_legal_review = True` in the metadata sidecar. It does NOT have a field that says "this negotiation cannot proceed to signature without this clause being reinstated." A legal reviewer receiving this LRS needs to understand that 6.1 is a signature blocker, not just a flagged item. Nothing in `LRSInput` or `LRSOutput` carries this signal.

2. **Risk narrative.** The operational stakes — fire risk, bodily injury, property damage from defective transformers — are not in `LRSInput`. A legal reviewer seeing "6.1 deleted" without context might not immediately understand why this is critical. Vincent would need to add this manually.

3. **Legal sign-off requirement.** "Legal will not approve signature without this clause" is Vincent's explicit operational constraint. This is not represented anywhere in the data model. There is no `legal_sign_off_required: bool` or equivalent field that would appear in the LRS without it being part of `LRSInput`.

**Category: Cat 1** — add `signature_blockers: list[str]` to `LRSInput` (list of clause references that are hard blockers to signature). **Cat 1** — add `risk_summary: Optional[str]` as an operator-supplied field in `LRSInput`.

---

## Consolidated Finding Summary

### Agent 4 — Structural Diff

| Finding | Category | Notes |
|---|---|---|
| Hybrid modification invisible if parser assigns new reference to insertion | Cat 4 (parser) / Cat 1 (DiffEntry schema) | `related_clause_refs: list[str]` on DiffEntry would allow parsers to express sub-clause relationships |
| No cross-clause semantic linking | Cat 1 | `surrounding_context` is reference strings only; no semantic adjacency |
| No clause renaming detection | Cat 1 | Fuzzy match pass; `likely_renamed_from: Optional[str]` on DiffEntry |
| No clause criticality awareness | Cat 3 | Agent 4 is deterministic; criticality is a playbook concern — correctly out of scope |

### Agent 5 — Redline Analysis

| Finding | Category | Notes |
|---|---|---|
| `round_number` not passed to `analyze_clause` | Cat 2 | Present in event, never forwarded to the LLM callable — straightforward fix |
| No prior round context parameter | Cat 2 | Signature needs `prior_round_context: Optional[str]`; pipeline needs a data source for it (Cat 3 dependency) |
| No per-clause criticality input | Cat 2 | Static `playbook_context` string cannot reliably encode per-clause metadata; needs structure |
| No severity field beyond `requires_legal_review` bool | Cat 1 | Add `severity: str` and `is_signature_blocker: bool` to `ClauseRecommendation` |
| No intentionality disambiguation for deletions | Cat 1 | Add `intentionality_flag: Optional[str]` to `ClauseRecommendation` |
| Cross-clause context absent for Scenario A (2.9) | Cat 3 | Requires DiffEntry schema change + pipeline changes to propagate relationships |

### Agent 6 — Counter-Proposal Drafting

| Finding | Category | Notes |
|---|---|---|
| No "restore verbatim" mechanism for rejections | Cat 2 | LLM-generated paraphrase of original text is a risk for legally precise clauses; needs a `restore_original: bool` hint |
| No structured sub-positions per clause | Cat 1 | `counter_text` is a single string; add `sub_positions: list[str]` to `CounterProposalDraft` |
| No operator tone input | Cat 4 | Tone is LLM-determined; Layer C playbook context can guide it |
| No round context | Cat 2 | Same as Agent 5: round number and prior round context need to flow through |

### Agent 7 — LRS Generator

| Finding | Category | Notes |
|---|---|---|
| No prior round summary in `LRSInput` | Cat 1 / Cat 3 | Schema gap is Cat 1; getting prior round data into the pipeline is Cat 3 |
| No operator position statement in `LRSInput` | Cat 1 | `operator_position: Optional[str]` and `operator_notes: Optional[str]` fields needed |
| `counterparty_profile_ref` not forwarded from NegotiationRow | Cat 1 | Already in NegotiationRow; needs to pass through SM enrichment to event payload and into `LRSInput` |
| No signature blocker field | Cat 1 | `signature_blockers: list[str]` — clause references that are hard blockers |
| No risk narrative field | Cat 1 | `risk_summary: Optional[str]` — operator-supplied stakes context |
| NegotiationRow metadata (priority, estimated_value) absent | Cat 1 | Renderer cannot tailor LRS to deal size or priority without these |
| `requires_legal_review` is a bool, not a severity | Cat 1 | Superseded by severity finding in Agent 5 — should flow through |

---

## Critical Path Findings (ordered by Phase 2 priority)

1. **`round_number` not passed to `analyze_clause`** (Cat 2) — This is a straightforward code bug relative to design intent. The event has the round number; the callable doesn't receive it. Fix before Layer C wiring.

2. **`restore_original: bool` missing from drafter signature** (Cat 2) — LLM paraphrasing of precise legal clauses is a real correctness risk. For any "reject" on a deletion, the counter-text should be the verbatim original. This is the highest-stakes Cat 2 finding.

3. **`severity` and `is_signature_blocker` missing from `ClauseRecommendation`** (Cat 1) — `requires_legal_review` bool is insufficient. Legal reviewers need severity and blocker status as structured fields. Small addition, high impact.

4. **`prior_round_summary` and `operator_position` missing from `LRSInput`** (Cat 1 + Cat 3) — The schema gap is small; the pipeline gap (how prior round data flows into Agent 7) requires design work. Without this, the LRS is incomplete for any negotiation past round 1.

5. **Static `playbook_context` string** (Cat 2) — Not blocking for Layer C wiring, but the flat string cannot support per-clause criticality metadata reliably. Should evolve toward a structured dict before scaling past a few negotiations.

---

## Bottom Line

**If Phase 1 were wired to real LLMs and run against this TTE negotiation today, would the output be useful to Vincent?**

**Directionally yes. Operationally no.**

For the two clearest cases — Clause 4.5 (replacement with deferral) and Clause 6.1 (critical clause deleted) — a capable LLM in Agent 5 would produce correct recommendations, and Agent 6 would produce counter-language that is a usable starting point. The LRS would capture the essential fact of each problem. Vincent could use the output as a first draft.

For Clause 2.9 (hybrid modification), the outcome depends on how the document parser structures the clause. If the insertion folds into clause 2.9 as a single modified clause (Scenario B), the analysis would likely be correct. If the parser assigns the insertion a new reference (Scenario A), the analysis would miss the "accepted-then-contradicted" relationship. This is unknowable without a real python-docx parse of TTE's actual document.

**The gaps that would make the output incomplete regardless of LLM quality:**

- The LRS for any round ≥ 2 would be missing prior-round context. Vincent's most important point on Clause 2.9 ("we rejected this before") would not appear anywhere in the document.
- Vincent's articulated positions are not a pipeline input. The LRS would contain Agent 5's analytical reasoning, which is not the same as Vincent's negotiating position.
- For Clause 6.1, the LRS would correctly flag legal review but would not state that this is a signature blocker or explain the operational stakes (fire, injury, property damage from transformer defects).
- Counter-language on legally sensitive clauses would be LLM-generated rather than verbatim-restored, introducing paraphrase risk on precise language.

**Assessment:** Phase 1 produces a useful first-pass triage and draft layer. It would reduce Vincent's time on a standard redline round, but would require meaningful manual completion before any document could be sent to legal or to TTE. The gaps are real but fixable in Phase 2 without rethinking the underlying architecture. Nothing in the three test cases exposes a Cat 5 problem — the pipeline model is sound for this negotiation type.

The two changes most worth making before first live use are the `round_number` pass-through (Cat 2, small fix) and the `is_signature_blocker` field on `ClauseRecommendation` (Cat 1, small fix with high legal impact).

---

## Post-Phase-A findings (from dry-run harness)

### Finding F — original_text plumbing gap (Layer C wiring decision)

The dry-run harness verified four of the five Phase A fixes propagate end-to-end (signature blocker propagation, accepted_with_addition detection, signature blocker flagging in LRS, counterparty_profile_ref auto-slugging). The fifth — Fix D's restore_strategy="verbatim" path — does not fire in the dry run because original_text is a DiffEntry field (Agent 4's output) but is not carried forward into ClauseRecommendation (Agent 5's output). Agent 6's _draft_one check rec.get("original_text", "") therefore returns empty for signature-blocker clauses with deleted original text (like Clause 6.1 indemnity deletion), causing the strategy to fall through to "redraft" instead of "verbatim".

**Category:** 2 (abstraction mismatch — data flow gap).
**Layer:** This is a Layer C wiring decision, not a Layer B defect. The architectural seam (restore_strategy auto-selection on is_signature_blocker + original_text presence) is correctly built. The choice of how to thread original_text through the pipeline — either (A) extend ClauseRecommendation schema to include original_text, or (B) have State Manager's _handle_counter_proposals_ready cross-reference the diff JSON to enrich the payload with original_text — depends on real LLM behavior and prompt design.

**Recommended resolution:** Defer until Layer C implementation. When wiring real LLMs to analyze_clause, decide whether the prompt should produce original_text in its output (option A, simpler) or whether SM enrichment should cross-reference diff JSON (option B, lower duplication). Either approach is non-breaking.

**Discovery method:** Dry-run harness smoke test (Phase B). Without the harness, this would not have been caught until Layer C wiring.
