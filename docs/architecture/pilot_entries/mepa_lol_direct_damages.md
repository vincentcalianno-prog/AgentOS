# Pilot: MEPA Limitation of Liability — Direct Damages Clarification

**Status:** Draft, pending Sandelin review
**Created:** 2026-05-29
**Author context:** First Layer C content drafted against Step 2b locked schemas. Schema validation exercise; not a locked Antora position. Sandelin meeting will validate, edit, or replace fields as needed.

## Why this clause was chosen for the first pilot

The Direct Damages Clarification is the explicit Antora protection against the MCM cross-document attack pattern (April 2026). It is substantively important (signature-blocker level), the MEPA template language is concrete and quotable, and it has a clear cross-clause dependency with the consequential damages exclusion. All of which made it a good stress test for the 13-entity schema model.

## The MEPA template language (Antora's preferred baseline)

> **Direct Damages Clarification**. For clarity, damages arising from or relating to impacts to Antora's business, including production interruption, loss of production output, reduced throughput, scrap, rework, line downtime, and related impacts to Antora's customers (including customer claims, chargebacks, offsets, penalties, and cover costs), will be treated as direct damages and not indirect, special, incidental, or consequential damages for purposes of this Agreement.

— Antora MEPA template, §8.3

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
    version: current  # TODO: establish version convention (see schema refinement #3)
  guidance: >
    Defend this clause verbatim. It carves out production-related damages
    (production interruption, loss of output, reduced throughput, scrap,
    rework, line downtime, customer claims, chargebacks, offsets, penalties,
    cover costs to Antora's customers) as DIRECT damages, not consequential.
    This is Antora's critical protection against the MCM-style cross-document
    attack: without this clarification, the consequential damages exclusion in
    §8.2 would eliminate production-loss recovery if supplier equipment fails.
    The enumerated list is exhaustive of Antora's main production-stage harms
    and should not be narrowed. Suppliers will commonly try to delete this
    section entirely (claiming it's an "unusual" provision) or weaken it
    by removing enumerated items. Both are signature-blocker level rejects.

accept_modifications:
  - id: narrower_customer_impact_scope
    description: >
      Supplier proposes limiting customer-impact damages to specific named
      customer categories (e.g., "Tier 1 customers only") rather than
      "Antora's customers" generally.
    example_language: >
      "...related impacts to Antora's Tier 1 customers (as defined in
      Antora's customer tier policy)..."
    rationale: >
      Acceptable if Antora's Tier 1 customer designation is clear and the
      bulk of production-loss risk is concentrated there. Slightly narrower
      but preserves core protection.

  - id: exclude_speculative_cover_costs
    description: >
      Supplier proposes excluding "speculative" or "consequential" cover
      costs while preserving direct cover costs (i.e., actual replacement
      procurement at market rates).
    example_language: >
      "...penalties, and direct cover costs (excluding speculative or
      consequential cover costs)..."
    rationale: >
      Acceptable. The clarification is that direct cover costs are direct
      damages; speculative cover costs being indirect doesn't undermine
      Antora's protection on real procurement losses.

  - id: mutual_clarification_extension
    description: >
      Supplier proposes that the direct damages clarification apply mutually
      to supplier-side direct damages of equivalent type.
    example_language: >
      "...will be treated as direct damages for both Parties..."
    rationale: >
      Acceptable. Mutuality doesn't weaken Antora's protection and may
      strengthen supplier's willingness to accept the clause. Verify with
      legal that no asymmetric exposure is created.

reject_thresholds:
  - id: deletion_of_clause
    description: >
      Supplier removes the Direct Damages Clarification entirely.
    example_language: |
      [section deleted from supplier markup]
    rationale: >
      Without this clarification, the consequential damages exclusion in
      §8.2 eliminates Antora's recovery on production-loss harms. This is
      the MCM-finding pattern that triggered formal Antora protection.
      Hard reject, signature-blocker.

  - id: narrowing_to_no_customer_impacts
    description: >
      Supplier removes the customer-impact clause (chargebacks, offsets,
      penalties, cover costs to Antora's customers) while keeping the
      production-impact clause.
    example_language: >
      "...will be treated as direct damages..." [customer-impact portion
      removed]
    rationale: >
      Antora's largest financial exposure on supplier failures is downstream
      customer impacts, not just internal production loss. Removing the
      customer-impact carve-out leaves the bulk of risk unprotected.

  - id: limiting_to_named_dollar_threshold
    description: >
      Supplier proposes a hard dollar cap on direct damages even when
      production impacts exceed that cap.
    example_language: >
      "...will be treated as direct damages up to $X..."
    rationale: >
      Defeats the purpose of the clarification. Production interruption
      from grid-critical equipment can exceed any reasonable threshold.
      The point of designating these as direct damages is to recover
      under the overall LoL cap (not under a separate sub-cap).

  - id: reclassification_as_consequential
    description: >
      Supplier proposes language that explicitly classifies any of the
      enumerated items as "consequential" or "indirect" damages.
    example_language: >
      "...such impacts shall be treated as consequential damages..."
    rationale: >
      Direct contradiction of the clause's intent. Hard reject.

negotiability: signature_blocker
is_signature_blocker: true  # TODO: redundant with negotiability (see refinement #1)

constraints: {}

metadata:
  created_date: 2026-05-29
  last_revised: 2026-05-29
  notes: >
    Pilot entry — first drafted during Step 2c schema validation exercise.
    Sandelin review pending for all fields. The mutual_clarification_extension
    accept pattern should be explicitly Sandelin-validated before deployment.
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
```

## Schema validation findings from this pilot

The 13-entity schema model held up. The four-field Pattern structure was sufficient (didn't reach for match_criteria once). CrossClauseDependency as a separate entity was clearly correct — modeling this on either PlaybookEntry alone would have been awkward. Four minor refinements surfaced (see `docs/architecture/pilot_entries/README.md` for details).

## Open items for Sandelin review

The following content fields are draft and require Sandelin validation:

- All three accept_modifications patterns (especially `mutual_clarification_extension`)
- All four reject_thresholds rationale statements
- `negotiability: signature_blocker` designation
- `metadata.notes` framing of the MCM context
