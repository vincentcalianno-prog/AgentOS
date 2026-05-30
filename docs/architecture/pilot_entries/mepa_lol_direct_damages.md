# Pilot: MEPA Limitation of Liability — Direct Damages Clarification

**Status:** Draft, pending Sandelin review
**Created:** 2026-05-29
**Author context:** First Layer C content drafted against Step 2b locked schemas. Schema validation exercise; not a locked Antora position. Sandelin meeting will validate, edit, or replace fields as needed.

## Why this clause was chosen for the first pilot

The Direct Damages Clarification is the explicit Antora protection against the MCM cross-document attack pattern (April 2026). It is substantively important (signature-blocker level), the MEPA template language is concrete and quotable, and it has a clear cross-clause dependency with the consequential damages exclusion. All of which made it a good stress test for the 13-entity schema model.

## The JST-calibrated baseline (§8.1 / §8.3 / §8.4, May 2026)

Provenance: Jeff/Sandelin MEPA redline feedback, May 2026. Supersedes the original §8.3 broad-list template language (which included production interruption, throughput loss, scrap, rework — these are NOT defended under the JST position).

**§8.1 — Limitation Amount (Antora outbound version):**
> Each Party's total aggregate liability shall not exceed [200%] of the total fees paid or payable under the applicable SOW or Purchase Order. Fallback: 150%. Floor: 100%. The following are not subject to the limitation of liability: (i) indemnification obligations; (ii) IP and confidentiality obligations; (iii) claims for bodily injury or property damage; (iv) claims arising from fraud or willful misconduct.

— Antora MEPA template, §8.1

**§8.3 — Direct Damages Clarification (three categories only):**
> Notwithstanding §8.1, the following categories of loss shall be treated as direct damages and shall not be deemed indirect, special, incidental, or consequential damages: (i) reasonable cover costs, including costs of re-procurement from an alternate source due to Supplier's failure to deliver conforming Products on time; (ii) BOP standby, idle, and remobilization costs caused by delayed or non-conforming delivery or performance by Supplier; and (iii) customer liquidated damages assessed against Purchaser under Purchaser's customer contracts as a direct result of Supplier's breach. For the avoidance of doubt, loss of production, loss of throughput, scrap losses, and rework costs shall not be deemed direct damages under this Agreement.

— Antora MEPA template, §8.3 (JST-calibrated)

**§8.4 — Sub-Cap on Restored Direct Damages (new section):**
> The aggregate liability of Supplier for all damages described in §8.3 shall not exceed three hundred percent (300%) of the total fees paid or payable under the applicable SOW or Purchase Order.

— Antora MEPA template, §8.4 (JST-calibrated)

## PlaybookEntry (draft)

```yaml
id: mepa.limitation_of_liability.direct_damages_clarification
contract_type_id: mepa
category_id: limitation_of_liability
sub_clause_id: direct_damages_clarification

defend_baseline:
  template_ref:
    document_id: antora_mepa_template
    section_id: "8.3"
    version: v1.0
  guidance: >
    §8 CAP: Defend 100% cap on aggregate liability per SOW/PO as the
    floor. Template baseline (Antora outbound version) is 200%; fallback
    is 150%; do not accept below 100%. Uncapped carve-outs: indemnity
    obligations, IP and confidentiality obligations, bodily injury /
    property damage claims, fraud, willful misconduct.

    §8.3 DIRECT DAMAGES — THREE CATEGORIES ONLY (JST-calibrated):
    Restore as direct damages exactly the following three categories,
    no more and no fewer: (1) reasonable cover costs, including costs
    of re-procurement from an alternate source due to counterparty
    failure to deliver conforming Products on time; (2) BOP standby,
    idle, and remobilization costs caused by delayed or non-conforming
    delivery or performance by counterparty; (3) customer liquidated
    damages assessed against Antora under Antora's customer contracts
    as a direct result of counterparty's breach.

    EXPLICITLY EXCLUDED from §8.3 restoration: loss of production,
    loss of throughput, scrap losses, rework costs. These remain
    consequential damages under the §8.2 exclusion. Do not accept
    counter-language that re-adds these categories, even framed as
    "clarifications" or "for avoidance of doubt" additions.

    §8.4 SUB-CAP (JST-calibrated, new section): Aggregate liability
    for all §8.3 restored categories capped at 300% of total fees
    paid/payable under the applicable SOW/PO. The 300% sub-cap is
    the ceiling specifically for §8.3 categories and is separate
    from the §8.1 general cap.

accept_modifications:
  - id: exclude_speculative_cover_costs
    description: >
      Counterparty proposes limiting cover costs to "direct and documented"
      re-procurement costs, excluding speculative or mark-up components.
    example_language: >
      "...(i) direct and documented cover costs, including actual costs
      of re-procurement from an alternate source..."
    rationale: >
      Acceptable. The JST position already defends verifiable cover
      costs; "direct and documented" aligns with that intent and does
      not materially narrow category (i).

  - id: mutual_clarification_extension
    description: >
      Counterparty proposes that the §8.3 direct damages clarification
      apply mutually to counterparty-side direct damages of equivalent type.
    example_language: >
      "...the categories in §8.3 shall be treated as direct damages
      for both Parties..."
    rationale: >
      Acceptable. Mutuality does not weaken Antora's §8.3 protection
      and may increase counterparty willingness to preserve the clause.
      Verify with legal that symmetrizing the three categories for an
      equipment supplier creates no asymmetric exposure.

  - id: sub_cap_reduction_to_150_pct
    description: >
      Counterparty proposes reducing the §8.4 sub-cap from 300% to
      150% of SOW/PO value, with all three §8.3 categories intact.
    example_language: >
      "§8.4 Sub-Cap. The aggregate liability of Supplier for all
      damages described in §8.3 shall not exceed one hundred fifty
      percent (150%) of the total fees paid or payable..."
    rationale: >
      Acceptable as a compromise position — 150% is the fallback floor
      for §8.4. All three §8.3 categories must remain intact. Requires
      Sandelin sign-off before accepting below 300%.

reject_thresholds:
  - id: deletion_of_clause
    description: >
      Counterparty removes §8.3 entirely.
    example_language: |
      [section deleted from counterparty markup]
    rationale: >
      Without §8.3, cover costs, BOP standby, and customer LDs are
      captured by the §8.2 consequential exclusion — the MCM
      cross-document attack pattern. Hard reject, signature-blocker.

  - id: re_expansion_to_broad_list
    description: >
      Counterparty proposes re-adding production loss, throughput loss,
      scrap, or rework to §8.3, reverting to the original broad-list
      template language.
    example_language: >
      "...including production interruption, loss of production output,
      reduced throughput, scrap, rework, line downtime..."
    rationale: >
      The JST position explicitly excludes these categories as contested
      and speculative. Accepting re-expansion undoes the JST calibration
      and reverts to a position counterparties will challenge as
      "unusual." Signature-blocker reject.

  - id: deletion_of_section_8_4_sub_cap
    description: >
      Counterparty deletes §8.4 or folds §8.3 back into the §8.1
      general cap (effectively removing the 300% sub-cap structure).
    example_language: >
      "§8.4 deleted." or "§8.3 damages shall be subject to the
      limitation in §8.1."
    rationale: >
      §8.4 is the structural counterpart to §8.3: it sets the ceiling
      on Antora's recoverable direct damages, making the §8.3 restoration
      commercially acceptable to counterparties. Deleting it either
      renders §8.3 recoveries unlimited (counterparty will refuse) or
      re-subjects them to the 100% general cap (Antora loses the benefit).
      Hard reject.

  - id: reclassification_as_consequential
    description: >
      Counterparty proposes language that explicitly classifies any of
      the three §8.3 categories as consequential or indirect damages.
    example_language: >
      "...BOP standby costs shall be treated as consequential damages
      for purposes of this Agreement..."
    rationale: >
      Direct contradiction of §8.3's intent. Hard reject.

negotiability: signature_blocker

constraints:
  lol_cap_min_pct: 100           # §8.1 floor — do not accept below 100% of SOW/PO value
  direct_damages_sub_cap_pct: 300  # §8.4 target — negotiate down to 150% at floor

pending_items:
  - "Sandelin confirmation of JST §8.3 three-category restriction vs. original broad-list language"
  - "Sandelin sign-off required before accepting §8.4 sub-cap below 300%"
  - "Sandelin review of mutual_clarification_extension for equipment supplier symmetry exposure"
  - "Legal review: does §8.4 sub-cap interact with uncapped carve-outs (BI/PD, indemnity)?"

examples:
  - "MCM Engineering (April 2026): attempted to delete §8.3 in MEPA redlines while accepting mutual consequential exclusion in PO. Cross-document analysis caught the pattern; Antora held the clause firm."

related_entries:
  - "mepa.limitation_of_liability.disclaimer_of_certain_damages"
  - "mepa.limitation_of_liability.lol_amount"

metadata:
  created_date: 2026-05-29
  last_revised: 2026-05-30
  provenance: "Jeff/Sandelin MEPA redline feedback, May 2026. §8.3 narrowed to three categories (cover costs, BOP standby/remobilization, customer LDs); §8.4 sub-cap at 300% added. Supersedes original broad-list §8.3 template language."
  notes: >
    Pilot updated to JST-calibrated §8 positions (Step 0b, 2026-05-30).
    Original pilot drafted 2026-05-29 during Step 2c schema validation.
    Sandelin review pending for all content fields.

review_status: draft
last_reviewed_by: null
last_reviewed_date: null

antora_response:
  rejection_response:
    rationale: >
      Deletion or expansion of §8.3 beyond the three named categories is
      unacceptable. Without §8.3, cover costs, BOP standby losses, and
      customer LD exposure are captured by the §8.2 consequential exclusion —
      exactly the MCM cross-document attack pattern. Attempts to re-add
      production loss, throughput, scrap, or rework to §8.3 are also rejected:
      the JST position narrows to three verifiable categories with clear causal
      proximity to counterparty breach; re-expansion introduces contested,
      speculative claims that will be litigated on causation grounds. Deletion
      of §8.4 is equally unacceptable: it is the structural counterpart to §8.3
      that defines the ceiling on restored damages; without it, §8.3 categories
      either become unlimited (counterparty will refuse to sign) or revert to
      the §8.1 general cap (Antora loses the higher sub-cap protection).
    counter_proposal: >
      Restore §8.3 to the three-category JST baseline with §8.4 sub-cap:

      "§8.3 Direct Damages. Notwithstanding the limitation of liability in
      §8.1, the following categories of loss shall be treated as direct damages
      and shall not be deemed indirect, special, incidental, or consequential
      damages: (i) reasonable cover costs, including costs of re-procurement
      from an alternate source due to Supplier's failure to deliver conforming
      Products on time; (ii) BOP standby, idle, and remobilization costs caused
      by delayed or non-conforming delivery or performance by Supplier; and
      (iii) customer liquidated damages assessed against Purchaser under
      Purchaser's customer contracts as a direct result of Supplier's breach.
      For the avoidance of doubt, loss of production, loss of throughput, scrap
      losses, and rework costs shall not be deemed direct damages under this
      Agreement.

      §8.4 Sub-Cap. The aggregate liability of Supplier for all damages
      described in §8.3 shall not exceed three hundred percent (300%) of the
      total fees paid or payable under the applicable SOW or Purchase Order."
  compromise_response:
    conditions: >
      If counterparty cannot accept the 200% overall LOL baseline, Antora
      may fall back to 100% (§8.1 floor) with §8.3 three categories and
      §8.4 300% sub-cap fully intact. If counterparty insists on reducing
      the §8.4 sub-cap below 300%, the floor is 150% of SOW/PO value —
      subject to Sandelin sign-off. Any compromise must preserve all three
      §8.3 categories intact; removing or narrowing any one category is a
      rejection trigger, not a compromise position.
    revised_language: >
      For a reduced §8.4 sub-cap compromise (150% floor):

      "§8.4 Sub-Cap. The aggregate liability of Supplier for all damages
      described in §8.3 shall not exceed one hundred fifty percent (150%) of
      the total fees paid or payable under the applicable SOW or Purchase Order."

      §8.3 language above remains unchanged from the counter-proposal.
  acceptance_response:
    rationale: >
      Accept without counter when all of the following are met: (a) §8.3
      restores exactly the three named categories — cover costs, BOP
      standby/remobilization, customer LDs — and does not add production
      loss, throughput, scrap, or rework; (b) §8.4 sub-cap is present at
      300% or higher of SOW/PO value; (c) §8.1 overall cap is at or above
      100% of SOW/PO value; (d) uncapped carve-outs for indemnity, IP,
      confidentiality, BI/PD, fraud, and willful misconduct are intact.
      If all four conditions are satisfied, Antora's JST baseline protection
      is intact and no counter is needed.

outcome_log: []

evidence_tier: provisional
```

## CrossClauseDependency (draft)

```yaml
id: consequential_exclusion_plus_direct_damages_clarification
description: >
  The Disclaimer of Certain Damages (consequential exclusion) and the
  Direct Damages Clarification are mutually dependent. The consequential
  exclusion alone, without the direct damages clarification, eliminates
  production-loss recovery — exactly the MCM cross-document attack pattern.

involved_entries:
  - mepa.limitation_of_liability.disclaimer_of_certain_damages
  - mepa.limitation_of_liability.direct_damages_clarification

interaction_type: requires_consistency

risk_if_violated: >
  If either clause is removed or weakened while the other is preserved
  intact, Antora loses production-loss recovery on supplier failures.
  The MCM negotiation (April 2026) attempted exactly this pattern —
  accepted mutual consequential exclusion in the PO while deleting the
  direct damages clarification in the MEPA.

example: >
  MCM Engineering attempted this in April 2026 redlines. Cross-document
  analysis caught it; Antora held both clauses firm.

metadata:
  created_date: 2026-05-29
  last_revised: 2026-05-29
  notes: >
    Pilot dependency — drafted alongside the Direct Damages Clarification
    pilot entry. References mepa.limitation_of_liability.disclaimer_of_certain_damages
    which has not yet been drafted as its own pilot entry.

review_status: draft
last_reviewed_by: null
last_reviewed_date: null
```

## Schema validation findings from this pilot

The 14-entity schema model held up. The four-field Pattern structure was sufficient (didn't reach for match_criteria once). CrossClauseDependency as a separate entity was clearly correct — modeling this on either PlaybookEntry alone would have been awkward. Four minor refinements surfaced during piloting and have been applied: `is_signature_blocker` boolean dropped, three-value review tracking added to PlaybookEntry/Overlay/CrossClauseDependency, `template_ref.version` established as semantic versions resolved via TemplateRegistry (Entity 14), and `pending_items` / `examples` / `related_entries` added as structured top-level fields.

## Open items for Sandelin review

The following content fields are draft and require Sandelin validation:

- All three accept_modifications patterns (especially `mutual_clarification_extension`)
- All four reject_thresholds rationale statements
- `negotiability: signature_blocker` designation
- `metadata.notes` framing of the MCM context
