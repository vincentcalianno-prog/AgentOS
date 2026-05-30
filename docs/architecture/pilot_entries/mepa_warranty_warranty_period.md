# Pilot: MEPA Warranty — Warranty Period

**Status:** Draft, pending Sandelin review
**Created:** 2026-05-29
**Author context:** Second Layer C pilot drafted against Step 2b locked schemas (refined in commit 454b7ec). Validates schema surfaces the first pilot (MEPA LoL Direct Damages) did not exercise: parametric negotiability, populated numeric constraints, accept-modifications-heavy content. Schema validation exercise; not a locked Antora position. Sandelin meeting will validate, edit, or replace fields as needed.

## Why this clause was chosen for the second pilot

The first pilot exercised `negotiability: signature_blocker` with empty `constraints: {}` and reject-heavy patterns. The second pilot deliberately targets the opposite: `negotiability: parametric` (the middle enum value, untested), populated `constraints` (numeric floor as overlay-tightening surface), and accept-modifications-heavy content (four substantive accept patterns vs four reject thresholds). This covers schema surface that single-pilot validation could not.

Warranty Period also has a cascading cross-clause structure (Service Period anchors on it, Spare Parts availability anchors on it, Repairs/Remedies obligation extends only during it) — different shape than the first pilot's MCM-style cross-document gap.

## The MEPA template language (Antora's preferred baseline)

> **Supplier Warranties.** Supplier warrants that ... (vi) for a period of three (3) years from Purchaser's Acceptance of the Products ("Warranty Period"), the Products and any System delivered under this Agreement will materially conform to the specifications, functional requirements, and performance requirements set forth in the applicable SOW or Purchase Order.

— Antora MEPA template, §6.1(vi)

## PlaybookEntry (draft)

```yaml
id: mepa.warranty.warranty_period
contract_type_id: mepa
category_id: warranty
sub_clause_id: warranty_period

defend_baseline:
  template_ref:
    document_id: antora_mepa_template
    section_id: "6.1(vi)"
    version: v1.0
  guidance: >
    Defend three (3) years from Purchaser's Acceptance as the baseline
    Warranty Period. This duration anchors several downstream clauses:
    Service Period (two years following Warranty Period), Spare Parts
    availability (seven years following Warranty Period expiration),
    and Repairs/Remedies (only obligated during Warranty Period at no
    cost). Shortening the Warranty Period cascades into all of these.

    The "from Purchaser's Acceptance" trigger is as important as the
    duration itself. Suppliers will commonly propose shipment-based or
    delivery-based triggers, which start the clock before Antora has
    validated the equipment functions. This shifts risk to Antora
    during commissioning. Acceptance-based triggers ensure Antora has
    a working system before the warranty clock starts.

    Parametric negotiability: the structure (duration from event) is
    fixed; the specific values and event references are the negotiation
    surface. Acceptable variants are documented in accept_modifications.
    Floor for duration is documented in constraints.

accept_modifications:
  - id: dual_anchor_with_acceptance_priority
    description: >
      Supplier proposes warranty duration anchored to two events with
      the later date controlling, as long as Acceptance is one of the
      two anchors and the duration from Acceptance is at least 24 months.
    example_language: >
      "for a period of twenty-four (24) months from Purchaser's Acceptance
      or thirty (30) months from shipment, whichever is later, ..."
    rationale: >
      Acceptable when supplier needs commercial certainty on outer bound
      (the shipment-based clock prevents indefinite Acceptance delays
      pushing warranty too far out). The Acceptance-or-later structure
      preserves Antora's protection during commissioning while giving
      supplier a ceiling. Used in MCM PDC negotiation (April 2026) as
      the negotiated landing.

  - id: commissioning_based_anchor
    description: >
      Supplier proposes anchoring to "commissioning" or "successful
      commissioning" rather than "Acceptance" as the start trigger,
      with duration of at least 30 months.
    example_language: >
      "for a period of thirty (30) months from successful commissioning..."
    rationale: >
      Acceptable if "commissioning" is defined in the SOW and references
      a verifiable milestone (commissioning report, SAT completion,
      or similar). The extended duration compensates for the slightly
      earlier trigger.

  - id: tiered_warranty_by_component
    description: >
      Supplier proposes different warranty durations for different
      component categories (e.g., mechanical components 36 months,
      electronic components 24 months, consumables 12 months).
    example_language: >
      "Mechanical Components: three (3) years from Acceptance; Electronic
      Components: two (2) years from Acceptance; Consumables: one (1)
      year from Acceptance."
    rationale: >
      Acceptable for systems with clear component categories and
      well-understood differential failure rates. Requires SOW to
      specify which components fall into each category. Antora should
      negotiate that any component not explicitly categorized defaults
      to the longest-tier duration.

  - id: extended_warranty_for_strategic_pricing
    description: >
      Supplier proposes shorter base warranty (24 months) with the
      option for Antora to purchase extended warranty coverage at
      defined pricing terms.
    example_language: >
      "Base Warranty Period: twenty-four (24) months from Acceptance.
      Extended Warranty available at $X per additional twelve (12)
      months, exercisable at Antora's option prior to expiration of
      the Base Warranty Period."
    rationale: >
      Acceptable when the per-month extended price is reasonable
      (rough target: under 2% of equipment cost per additional year)
      and Antora retains unilateral right to extend. Base warranty
      must still meet the 24-month floor.

reject_thresholds:
  - id: warranty_under_floor
    description: >
      Supplier proposes any Warranty Period shorter than 24 months
      from any qualifying trigger.
    example_language: >
      "for a period of twelve (12) months from delivery..."
    rationale: >
      24 months is the absolute floor. Antora's equipment typically
      requires at least one full operating cycle (often a year or more)
      to surface latent defects. Anything shorter exposes Antora to
      defects discovered after warranty expiration with no recourse.

  - id: shipment_only_trigger
    description: >
      Supplier proposes anchoring Warranty Period solely to shipment
      or delivery (no Acceptance-based component).
    example_language: >
      "for a period of thirty (30) months from shipment..."
    rationale: >
      Pure shipment-based triggers transfer commissioning risk to
      Antora. If commissioning takes six months (not unusual for
      complex equipment), Antora burns 20% of warranty coverage
      before the equipment is even operational.

  - id: vague_or_undefined_trigger
    description: >
      Supplier proposes language with no defined start event ("from
      installation," "from project start," "from agreement effective
      date" without further specification).
    example_language: >
      "for a period of thirty-six (36) months from installation..."
    rationale: >
      Undefined triggers create disputes at warranty expiration.
      "Installation" without further definition can mean physical
      placement, energization, or first run — each potentially months
      apart. The trigger must be tied to a documented, verifiable
      milestone.

  - id: warranty_voidable_by_normal_operations
    description: >
      Supplier proposes voiding warranty based on conditions that
      are part of normal industrial operation (e.g., "warranty voids
      if equipment is used continuously," "warranty voids if equipment
      is operated outside specified hours").
    example_language: >
      "Warranty void if equipment is operated more than sixteen (16)
      hours per day..."
    rationale: >
      Antora operates production equipment continuously. Conditions
      that void warranty based on normal industrial use are not
      warranty terms — they're warranty disclaimers. Reject.

negotiability: parametric

constraints:
  min_warranty_months: 24

pending_items:
  - "Sandelin confirmation that 24-month floor is correct (not 18 or 30)"
  - "Sandelin review of extended_warranty_for_strategic_pricing pattern — is 2% per year the right rough target?"
  - "Confirmation that tiered_warranty_by_component is acceptable in principle (some legal teams resist any tiering)"
  - "Should warranty_voidable_by_normal_operations be split into multiple reject_thresholds by void condition type?"
  - "First executed MEPA upgrades to verified"

examples:
  - "MCM Engineering (April 2026): Antora landed on 24-month-from-Acceptance / 30-month-from-shipment whichever-later structure (dual_anchor_with_acceptance_priority pattern). Documented in PO Round 3 redlines."
  - "Texas Transformers (April 2026): defended baseline 3-year-from-Acceptance during MEPA redlines; supplier accepted."

related_entries:
  - "mepa.warranty.service_period"
  - "mepa.warranty.repairs_remedies"
  - "mepa.warranty.spare_parts_availability"

metadata:
  created_date: 2026-05-29
  last_revised: 2026-05-30
  provenance: "MEPA template baseline + Antora standard warranty position. Baseline = 3 years from Purchaser's Acceptance per §6.1(vi). MCM's 24-month-from-commissioning / 30-month-from-shipment figure is counterparty-specific and is NOT the template baseline."
  notes: >
    Second pilot entry updated to confirm template baseline and populate
    antora_response (Step 0b, 2026-05-30). Originally drafted 2026-05-29
    during Step 2c schema validation. Sandelin review pending for all
    content fields including the 24-month floor.

review_status: draft
last_reviewed_by: null
last_reviewed_date: null

antora_response:
  rejection_response:
    rationale: >
      Any warranty period shorter than 24 months from any qualifying trigger,
      or anchored solely to shipment or delivery without an Acceptance-based
      component, is unacceptable. Pure shipment-based triggers start the clock
      before Antora has validated that the equipment functions — effectively
      transferring commissioning risk to Antora. For complex equipment,
      commissioning can take six months or more; a shipment-only anchor burns
      a significant fraction of the warranty period before the system is
      operational. Warranty conditions that void coverage based on normal
      industrial operation (continuous use, daily operating hours) are
      similarly unacceptable — these are warranty disclaimers, not warranty
      terms. The template baseline is 3 years from Purchaser's Acceptance;
      MCM's 24-month-from-commissioning / 30-month-from-shipment is
      counterparty-specific and is not the baseline to defend from.
    counter_proposal: >
      Restore §6.1(vi) to the template baseline:

      "...for a period of three (3) years from Purchaser's Acceptance of the
      Products ('Warranty Period'), the Products and any System delivered under
      this Agreement will materially conform to the specifications, functional
      requirements, and performance requirements set forth in the applicable
      SOW or Purchase Order."
  compromise_response:
    conditions: >
      If counterparty cannot accept 3 years from Acceptance, Antora may
      negotiate down to 24 months from Acceptance (the floor), subject to:
      (a) the trigger remains Purchaser's Acceptance — not shipment or
      delivery; commissioning-based triggers are acceptable only if
      "commissioning" is defined in the SOW against a documented, verifiable
      milestone (commissioning report, SAT completion); (b) downstream
      clauses (Service Period, Spare Parts availability, Repairs/Remedies)
      are either anchored independently or extended to compensate for the
      shorter Warranty Period base — silent cascade must be explicitly
      addressed; (c) Sandelin sign-off is required before accepting any
      duration below 30 months. A dual-anchor structure (Acceptance-or-N-
      months-from-shipment, whichever is later) may be acceptable if the
      Acceptance-based duration is at least 24 months and supplier's need
      for commercial certainty on the outer bound is documented.
    revised_language: >
      For a 24-month-from-Acceptance compromise:

      "...for a period of twenty-four (24) months from Purchaser's Acceptance
      of the Products ('Warranty Period'), the Products and any System
      delivered under this Agreement will materially conform to the
      specifications, functional requirements, and performance requirements
      set forth in the applicable SOW or Purchase Order."

      For a dual-anchor compromise (24-month Acceptance floor):

      "...for a period of twenty-four (24) months from Purchaser's Acceptance,
      or thirty (30) months from the date of shipment, whichever is later
      ('Warranty Period'), the Products and any System delivered under this
      Agreement will materially conform..."
  acceptance_response:
    rationale: >
      Accept without counter when all of the following are met: (a) the
      trigger is Purchaser's Acceptance — not shipment, delivery, or an
      undefined event; (b) the Warranty Period is at least 36 months (3
      years) from Acceptance; (c) no void conditions based on normal
      industrial operation (continuous use, operating hours, duty cycles)
      are present. If the counterparty proposes a dual-anchor structure
      where the Acceptance-based duration is 36 months or greater and the
      shipment-based outer bound does not materially shorten the effective
      period, accept. If all three conditions are met, the template baseline
      is intact and no counter is needed.

outcome_log: []

evidence_tier: provisional
```

## CrossClauseDependency (draft)

```yaml
id: warranty_period_anchors_downstream_obligations
description: >
  The Warranty Period duration anchors several downstream Antora
  protections: Service Period (defined as "two years following
  Warranty Period"), Spare Parts availability (seven years following
  Warranty Period expiration), and Repairs/Remedies (no-cost remedies
  available only during Warranty Period). Shortening Warranty Period
  cascades into all of these, often without supplier or Antora
  fully appreciating the downstream impact.

involved_entries:
  - mepa.warranty.warranty_period
  - mepa.warranty.service_period
  - mepa.warranty.repairs_remedies
  - mepa.warranty.spare_parts_availability

interaction_type: requires_consistency

risk_if_violated: >
  If Warranty Period is negotiated shorter than baseline (e.g.,
  supplier accepts 24 months instead of defended 36 months) without
  separately renegotiating the Service Period and Spare Parts language
  to either anchor independently or compensate for the shortened
  base, Antora silently loses:
    - 12 months of Service Period (the "two years following" clock
      moves earlier)
    - 12 months of Spare Parts availability (the "seven years
      following Warranty Period expiration" clock moves earlier)
    - 12 months of no-cost remedy coverage
  None of these losses are visible at the moment Warranty Period
  is negotiated. They surface 5+ years later when spare parts run
  out or service obligations end.

example: >
  Hypothetical: supplier accepts the Acceptance-based trigger but
  pushes Warranty Period from 36 months to 24 months. Antora accepts.
  Five years later, Antora needs spare parts for a unit. Supplier
  notes that the seven-year spare parts window expired two years
  early because it was anchored to the shortened Warranty Period.
  Antora's options narrow significantly.

metadata:
  created_date: 2026-05-29
  last_revised: 2026-05-29
  notes: >
    Second pilot dependency. Three of the involved entries (service_period,
    repairs_remedies, spare_parts_availability) have not yet been
    drafted as their own PlaybookEntries. References will resolve
    when those entries are authored in Step 2c.

review_status: draft
last_reviewed_by: null
last_reviewed_date: null
```

## Schema validation findings from this pilot

The 14-entity schema (post-refinement, commit 454b7ec) held cleanly. Specific surfaces newly exercised:

- `negotiability: parametric` — the middle enum value, untested by first pilot. Captures "structure fixed, values flex" naturally.
- Populated `constraints` field (`min_warranty_months: 24`) — numeric floor that future overlays could tighten via most-restrictive-wins. First pilot had empty constraints.
- `accept_modifications` heavier than `reject_thresholds` — opposite weight distribution from first pilot. Schema is symmetric; both directions work equally well.
- Cascading cross-clause structure — different shape than first pilot's MCM-style cross-document gap. CrossClauseDependency's `risk_if_violated` field captured the downstream cascade naturally.

One observation worth flagging (not a refinement, a Phase 2a loader requirement): this CrossClauseDependency references three PlaybookEntries that don't yet exist (`service_period`, `repairs_remedies`, `spare_parts_availability`). Incremental authoring produces dangling references. The playbook_loader should validate and warn on these but not block — they resolve naturally as Step 2c progresses.

**Schema refinements queued from this pilot: none.** Two pilots, no further schema changes needed. The schema is stable enough to start full Step 2c authoring.

## Open items for Sandelin review

The following content fields are draft and require Sandelin validation:

- The 24-month floor on `min_warranty_months` (is this correct, or is it 18 or 30?)
- The `extended_warranty_for_strategic_pricing` pattern's "rough target: under 2% per year" — invented from intuition, needs confirmation
- The `tiered_warranty_by_component` pattern as acceptable in principle
- Whether `warranty_voidable_by_normal_operations` should be one reject or split into multiple
- The cascading risk framing in the CrossClauseDependency (assumes Antora's negotiation history confirms the cascade pattern matters in practice)
