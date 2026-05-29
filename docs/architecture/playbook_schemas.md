# ACP Playbook Schemas (Step 2b Locked Design)

This document archives the schema decisions locked during Step 2b of the ACP playbook
architecture session (2026-05-29). It covers 14 schema entities that define the structural
skeleton of the ACP playbook: how contract types relate to one another, how clauses are
organized and positioned, how overlays tighten those positions for specific counterparties or
projects, and how runtime concessions are authorized and logged.

This is a reference document for Layer A substrate — the data shapes that both Layer B agents
and Layer C content depend on. It is not an implementation. Python dataclasses, validators,
and serialization logic will be written in a future phase after Step 2c content authoring
validates these schemas against real Antora playbook content. No code of any kind belongs in
this file.

These schemas explicitly do not contain Layer C content. Antora's actual PlaybookEntry
positions, Pattern libraries, Overlay instances, and CrossClauseDependency examples are
Step 2c deliverables and are deliberately absent here. Similarly, the authorization workflow
mechanism — how Slack approvals, email confirmations, or UI buttons are wired — is a Layer C
deployment decision not addressed by these schemas. What this document captures is the shape
of the data, the constraints baked into that shape, and the design decisions behind each
choice.

One cross-cutting principle worth stating at the top: signature-blocker designation and
negotiability live on PlaybookEntry, not on Category or ContractType. These are per-deployment
judgments about a specific (ContractType, Category, SubClause) combination. A given SubClause
may be boilerplate in an MPA but a signature blocker in a MEPA. Placing these fields higher in
the hierarchy would force a false uniformity that doesn't match how contract risk actually works.

---

## Design principles applied throughout

- **Schema lives in Layer A; content lives in Layer C.** The entities here define the shapes.
  The PlaybookEntry positions, Pattern libraries, and Overlay instances that fill those shapes
  are Layer C content and are not included in this document.

- **Hardcoded 3-axis overlay system (counterparty, project, commodity), designed for cheap
  extension to a fourth when evidence demands.** The axis enum is the extension point. Adding a
  fourth axis (e.g., geography, regulatory tier) requires adding one enum value and populating
  overlay instances — it does not require schema changes elsewhere.

- **Most-restrictive-wins resolution for overlay precedence.** When multiple overlays apply to
  the same PlaybookEntry, the resolved position is the most restrictive combination. This is a
  deliberate risk-management choice: in overlapping-overlay situations, err toward Antora's
  hardest position.

- **Overlays are static and risk-driven (tightening only); concessions handle runtime
  loosening with human authorization.** Overlays capture known standing risk postures (e.g.,
  "MCM always gets tighter indemnity terms"). They cannot loosen a baseline position.
  RuntimeConcession is the mechanism for loosening, and it always requires human authorization.

- **Provenance computed at resolution time, stored in audit log per ClauseRecommendation.**
  ResolutionResult is a computed artifact, not a stored entity. Every ClauseRecommendation
  emitted by a Layer B agent carries its provenance trace into the audit log for legal
  auditability.

- **Hierarchical Category → SubClause with two-level convention, optional third level
  permitted for future deployers.** The schema supports three levels via the `sub_sub_clauses`
  field on SubClause. Antora's convention is two levels. Future deployers may use three without
  a schema change.

---

## Entity 1: ContractType

ContractType represents a distinct category of legal agreement that Antora enters into with
counterparties. Each type carries its own set of applicable categories, mandatory sections, and
overlay axes. ContractType is primarily a classification and routing vehicle: it tells the
system which clauses are relevant for a given negotiation and which overlay axes apply.

```yaml
ContractType:
  id: str                              # canonical identifier, e.g., "mepa"
  display_name: str                    # human-readable, e.g., "Master Equipment Purchase Agreement"
  description: str                     # one-paragraph what-this-is
  applicable_categories: List[str]     # which Category ids apply to this type
  required_sections: List[str]         # mandatory top-level sections for this type
  applicable_overlay_axes: List[str]   # subset of [counterparty, project, commodity]
  metadata:
    created_date: date
    last_revised: date
    notes: str
```

Notes:
- Signature-blocker designation and negotiability are deliberately NOT on ContractType.
  Those live on PlaybookEntry (per-deployment judgment).
- Initial Antora contract types: NDA, MPA, MEPA, MSA, SOW, PO, MOU/LOI.
  MOU/LOI is standalone (no parent/child relationships); custom binding situations are
  handled as exceptions rather than requiring a new ContractType.

---

## Entity 2: ContractRelationship

ContractRelationship is a separate entity for parent/child relationships between contract
types. This was chosen over a list field on ContractType to support richer relationship
semantics — cardinality, relationship type, notes — without bloating ContractType, and to
avoid circular dependency problems that arise when types reference each other during loading.
Relationships are loaded after types; no type needs to know about its children at parse time.

```yaml
ContractRelationship:
  parent_type: str                     # ContractType id
  child_type: str                      # ContractType id
  relationship_type: enum              # operates_under | references
  cardinality: enum                    # one_to_one | one_to_many | many_to_one
  notes: Optional[str]
```

Notes:
- Only two relationship_type values: `operates_under` (PO/SOW operate under master
  agreements) and `references` (NDA is referenced by master agreements). The value
  `precedes` was considered for MOU/LOI but rejected — MOU/LOI is standalone and does
  not have a formal predecessor relationship to any master agreement.
- Initial Antora relationship instances (9 total; populated as Layer C content in Step 2c):

| Parent | Child | Type           | Cardinality  |
|--------|-------|----------------|--------------|
| MPA    | PO    | operates_under | one_to_many  |
| MEPA   | PO    | operates_under | one_to_many  |
| MSA    | PO    | operates_under | one_to_many  |
| MPA    | SOW   | operates_under | one_to_many  |
| MEPA   | SOW   | operates_under | one_to_many  |
| MSA    | SOW   | operates_under | one_to_many  |
| NDA    | MPA   | references     | one_to_many  |
| NDA    | MEPA  | references     | one_to_many  |
| NDA    | MSA   | references     | one_to_many  |

---

## Entity 3: Category

Category is the top-level grouping of related clauses within the playbook — for example,
Indemnification, Warranty, Limitation of Liability, Intellectual Property. Categories
provide the organizational spine that both humans and agents use to navigate clause analysis.
Each Category contains an ordered list of SubClauses.

```yaml
Category:
  id: str
  display_name: str
  description: str
  sub_clauses: List[SubClause]
  metadata:
    created_date: date
    last_revised: date
    notes: str
```

---

## Entity 4: SubClause

SubClause is the leaf-level clause within a Category. Two-level hierarchy (Category →
SubClause) is the Antora convention. The `sub_sub_clauses` field exists to permit a third
level for future deployers without requiring a schema change; it will be empty for all
Antora-authored SubClauses.

SubClauses have shared identity across ContractTypes. A SubClause like
`indemnification.general_indemnity` appears in both MPA and MEPA; it is the same entity in
both contexts. Where contract-type-specific variations exist, PlaybookEntry overrides on that
(ContractType, Category, SubClause) combination handle the difference rather than duplicating
the SubClause definition.

```yaml
SubClause:
  id: str
  display_name: str
  description: str
  parent_category: str                 # Category id
  applicable_contract_types: List[str] # which ContractType ids this SubClause appears in
  sub_sub_clauses: Optional[List[SubClause]]   # convention: empty for Antora
  metadata:
    created_date: date
    last_revised: date
    notes: str
```

Notes:
- Shared SubClause identity with per-(ContractType, Category, SubClause) override
  mechanism (Option C from design session). Most SubClauses are referenced from multiple
  ContractTypes; PlaybookEntry overrides handle the cases where contract-type-specific
  variations exist.

---

## Entity 5: PlaybookEntry

PlaybookEntry is the per-(ContractType, Category, SubClause) record that holds Antora's
defend/accept/reject judgment for a specific clause in a specific contract type. This is the
entity a Layer B agent looks up during clause analysis to determine what position to assert,
what counter-language patterns to accept, and what patterns to reject as non-starters.

The composite id convention (`mepa.indemnification.general_indemnity`) provides human
readability while remaining stable as a lookup key. This is also the entity where
`negotiability` lives — a per-deployment judgment about a specific clause in a specific
contract type context, not a property of the clause or contract type in isolation.
`negotiability: signature_blocker` is the source of truth for signature-blocker designation;
there is no separate boolean.

```yaml
PlaybookEntry:
  id: str                              # composite: "mepa.indemnification.general_indemnity"
  contract_type_id: str
  category_id: str
  sub_clause_id: str

  defend_baseline:
    template_ref:                      # semantic version, e.g., "v1.0" — resolved via TemplateRegistry
      document_id: str
      section_id: str
      version: str
    guidance: str                      # freeform judgment

  accept_modifications: List[Pattern]  # acceptable counterparty counter-language patterns
  reject_thresholds: List[Pattern]     # unacceptable counterparty counter-language patterns

  negotiability: enum                  # boilerplate | parametric | negotiable | signature_blocker

  constraints: Dict[str, value]        # ordered numeric fields only (e.g., min_cap_multiplier)

  pending_items: List[str]             # explicit "needs attention" list
  examples: List[str]                  # concrete examples illustrating this entry's application
  related_entries: List[entry_ref]     # informational pointers to related PlaybookEntries

  metadata:
    created_date: date
    last_revised: date
    notes: str

  review_status: enum                  # draft | approved | deprecated
  last_reviewed_by: Optional[str]      # identity of reviewer, e.g., "sandelin.sikes"
  last_reviewed_date: Optional[date]
```

Notes:
- `negotiability: signature_blocker` is the sole source of truth for signature-blocker
  designation. The former `is_signature_blocker` boolean was redundant and has been removed
  (it was always derivable from `negotiability == "signature_blocker"`).
- `pending_items`, `examples`, and `related_entries` are top-level structured fields
  alongside `metadata.notes`, not inside it. `pending_items` captures items needing
  attention (e.g., "awaiting Sandelin review on mutual_clarification_extension pattern").
  `examples` captures concrete illustrative instances. `related_entries` points to related
  PlaybookEntries for informational cross-reference; it is distinct from
  CrossClauseDependency, which is structural and drives cross-clause risk analysis.
- `review_status` (draft | approved | deprecated), `last_reviewed_by`, and
  `last_reviewed_date` support content quality tracking. Three values only — in-flight
  states like "pending_review" are project-management metadata that do not change how the
  agent uses the entry and therefore do not belong in Layer A substrate.

---

## Entity 6: Pattern

Pattern is used in `accept_modifications` and `reject_thresholds` on PlaybookEntry, and as
the unit of addition/removal in Overlay modifications. A Pattern represents a class of
counter-language — not a specific string, but a recognizable type of contractual move —
described well enough for an LLM to match against redline text.

```yaml
Pattern:
  id: str                              # used in overlay add/remove targeting and provenance
  description: str                     # what kind of counter-language this represents
  example_language: str                # concrete sample for LLM matching
  rationale: str                       # why this is acceptable / unacceptable
```

Notes:
- `match_criteria` field deliberately not included. Build with four fields; add a fifth
  only if `description` + `example_language` prove insufficient for reliable LLM matching
  in practice. Keeping four fields avoids premature specification of a matching algorithm
  before empirical evidence exists.

---

## Entity 7: Overlay

Overlay captures a standing tightening modification to one or more PlaybookEntries that
applies when a specific counterparty, project, or commodity is in scope. Overlays are
risk-driven and static — they represent known risk postures (e.g., "for counterparty MCM,
tighten indemnification terms") rather than negotiation-time decisions.

When multiple overlays apply to the same PlaybookEntry in a given context, resolution uses
most-restrictive-wins: the set of accepted modifications is the intersection (accept only
what all applicable overlays accept), and the set of reject thresholds is the union (reject
anything that any applicable overlay rejects).

```yaml
Overlay:
  id: str
  axis: enum                           # counterparty | project | commodity
  scope_value: str                     # e.g., "mcm", "pratt", "pdc"
  applies_to: List[entry_ref]          # which PlaybookEntries this overlay modifies

  modifications:
    add_to_accept_modifications: List[Pattern]
    remove_from_accept_modifications: List[str]   # by Pattern id
    add_to_reject_thresholds: List[Pattern]
    remove_from_reject_thresholds: List[str]      # by Pattern id
    constraints: Dict[str, value]                  # numeric tightening
    guidance_override: Optional[str]               # overrides defend_baseline.guidance

  rationale: str                       # why this overlay exists
  metadata:
    created_date: date
    last_revised: date
    notes: str

  review_status: enum                  # draft | approved | deprecated
  last_reviewed_by: Optional[str]      # identity of reviewer, e.g., "sandelin.sikes"
  last_reviewed_date: Optional[date]
```

Notes:
- Overlays are always risk-driven tightening. Loosening at negotiation time is handled
  via RuntimeConcession with human authorization, not via overlay modifications.
- `constraints` is limited to ordered numeric fields where most-restrictive-wins is a
  well-defined operation (e.g., a higher floor is more restrictive than a lower floor).
- Initial overlay content is deferred to Step 2c authoring. Overlays are authored when
  the first negotiation surfaces the need; speculating about overlays before real
  counterparty patterns emerge is premature.
- `review_status`, `last_reviewed_by`, `last_reviewed_date`: same three-value review
  tracking as PlaybookEntry. Overlays are authored by humans and require the same approval
  discipline before being applied in production.

---

## Entity 8: CrossClauseDependency

CrossClauseDependency captures interactions between PlaybookEntries where a concession on
one clause creates or destroys risk in another. The canonical example from Antora's history
is the MCM consequential-damages finding: a counterparty's consequential-damages exclusion
clause and its deleted direct-damages clarification, taken individually, each seemed
manageable — but the combination eliminated production-loss recovery entirely. Neither clause
alone flagged the risk; the interaction did.

```yaml
CrossClauseDependency:
  id: str
  description: str
  involved_entries: List[entry_ref]    # PlaybookEntry ids
  interaction_type: enum               # mutual_dependency | mutual_exclusion | requires_consistency
  risk_if_violated: str
  example: str                         # concrete instance (e.g., MCM finding)
  metadata:
    created_date: date
    last_revised: date
    notes: str

  review_status: enum                  # draft | approved | deprecated
  last_reviewed_by: Optional[str]      # identity of reviewer, e.g., "sandelin.sikes"
  last_reviewed_date: Optional[date]
```

Notes:
- `detection_pattern` field deliberately omitted. The agent triggers dependency analysis
  whenever any involved entry is touched in a redline, and lets the LLM do semantic
  interpretation rather than attempting regex or structural matching. Bias toward catching
  dependencies (accepting false positives) over missing them.
- Three `interaction_type` values: `mutual_dependency` (both entries must be present or
  absent together), `mutual_exclusion` (accepting one makes the other untenable),
  `requires_consistency` (the two entries must align to avoid a gap like MCM).
- `review_status`, `last_reviewed_by`, `last_reviewed_date`: same three-value review
  tracking as PlaybookEntry. Cross-clause dependencies are modeled by humans and benefit
  from the same approval discipline.

---

## Entity 9: ResolutionResult

ResolutionResult is the computed output of the Layer B resolver when determining the
effective playbook position for a specific (ContractType, Category, SubClause, context)
combination. It is not stored on the PlaybookEntry or any other persistent entity — it is
computed fresh at query time by applying overlays to the baseline PlaybookEntry via
most-restrictive-wins resolution.

The provenance trace in ResolutionResult is what gets written to the audit log alongside
each ClauseRecommendation. This trace answers the question: "why did the agent take this
position?" with full attribution to the specific baseline, override, and overlay sources
that contributed.

```yaml
ResolutionResult:
  query:
    contract_type_id: str
    category_id: str
    sub_clause_id: str
    context:
      counterparty: Optional[str]
      project: Optional[str]
      commodity: Optional[str]
  effective_entry: PlaybookEntry       # the merged result
  provenance:
    - source: enum                     # baseline | contract_type_override | overlay | resolution_rule
      source_ref: str                  # id of the source entity
      applied_modifications: List[Modification]
      note: Optional[str]
```

---

## Entity 10: RuntimeConcession

RuntimeConcession captures when Antora's team accepts a counterparty counter-proposal that
is less restrictive than the resolved PlaybookEntry position. This is the mechanism for
runtime loosening — the only legitimate way to deviate from a resolved position during an
active negotiation — and it always requires human authorization before the agent can treat
the concession as authorized.

RuntimeConcession is scoped to `this_negotiation` only. It does not modify the underlying
PlaybookEntry or create a new Overlay. Promotion to a permanent Overlay is a separate,
deliberate act captured by ConcessionPromotion.

```yaml
RuntimeConcession:
  id: str
  negotiation_id: str
  diff_entry_ref: str
  effective_entry_at_decision: PlaybookEntry   # snapshot at decision time
  supplier_counter_language: str
  authorizations: List[AuthorizationEvent]
  required_authorization: RequiredAuthorization
  authorization_complete: bool
  rationale: str
  scope: enum                          # always "this_negotiation"
  metadata:
    created_date: datetime
    notes: str
```

Storage: RuntimeConcession instances live in ConcessionLog (a separate queryable entity).
AuthorizationEvent instances live in the audit log. Cross-referenced via `concession_id`.
ConcessionLog storage implementation is deferred to Phase 2a alongside other Layer C wiring.

---

## Entity 11: AuthorizationEvent

AuthorizationEvent records a single authorization action taken by a specific person on a
specific RuntimeConcession. Multiple AuthorizationEvents may be required to satisfy a
RequiredAuthorization policy (e.g., both supply chain lead and legal counsel must approve
before a signature-blocker concession is authorized).

```yaml
AuthorizationEvent:
  id: str
  identity: str                        # user identity (email, employee id, etc.)
  role: str                            # supply_chain_lead, legal_counsel, etc.
  action: enum                         # approved | requested_changes | rejected
  timestamp: datetime
  context: Optional[str]
```

Notes:
- The authorization workflow mechanism — how Slack approvals, email confirmations, or web
  UI buttons are wired to produce AuthorizationEvents — is a Layer C deployment decision.
  This schema defines the event structure; Layer C implements the collection mechanism.
  That decision is deferred until after the Sandelin call clarifies authorization
  requirements.

---

## Entity 12: RequiredAuthorization

RequiredAuthorization defines the policy for what authorizations are needed before a given
RuntimeConcession is considered complete. The policy is evaluated against the set of
AuthorizationEvents on the concession.

```yaml
RequiredAuthorization:
  scope_trigger: enum                  # signature_blocker | dollar_threshold | always | etc.
  required_roles: List[str]
  required_count: int                  # usually len(required_roles)
```

---

## Entity 13: ConcessionPromotion

ConcessionPromotion is a separate entity capturing when humans deliberately promote a pattern
of repeated concessions to a permanent Overlay. Agent 9 (Portfolio Aggregator) surfaces
patterns where the same concession type has been accepted multiple times across negotiations.
ConcessionPromotion records the decision to institutionalize that concession as standing
policy.

Promotion is always a deliberate human act with explicit authorization. It is never automatic.
The resulting Overlay becomes a first-class citizen of the playbook substrate, subject to all
the same audit and versioning disciplines as any other Overlay.

```yaml
ConcessionPromotion:
  id: str
  promoted_concessions: List[str]      # RuntimeConcession ids that formed the pattern
  resulting_overlay_id: str            # the new or modified Overlay
  promoted_by: AuthorizationEvent
  rationale: str
  timestamp: datetime
```

---

## Entity 14: TemplateRegistry

TemplateRegistry provides versioned resolution for `template_ref` fields on PlaybookEntry.
When a PlaybookEntry references `document_id: antora_mepa_template, version: v1.0`, the
playbook loader looks up the TemplateRegistry to get the canonical document at that version.

The key design principle is deliberate opt-in: when Antora's legal team updates a template
(e.g., new standard language for §8.3 in response to a court decision), existing PlaybookEntry
references at `v1.0` continue pointing to the prior template until each entry is deliberately
updated to the new version. No silent invalidation. A new template version never automatically
propagates to playbook entries — entries opt in by updating their `template_ref.version`
field explicitly.

TemplateRegistry is Layer C content — each deployment has its own set of templates — but the
schema is Layer A substrate.

```yaml
TemplateRegistry:
  id: str                              # e.g., "antora_mepa_template"
  display_name: str                    # e.g., "Antora MEPA Template"
  versions: List[TemplateVersion]
  metadata:
    created_date: date
    last_revised: date
    notes: str

TemplateVersion:
  version: str                         # semantic version, e.g., "v1.0"
  effective_date: date
  document_ref: str                    # pointer to actual document (file path, doc id, URL)
  notes: Optional[str]                 # what changed in this version
```

---

## Open items for Step 2c

The following were deliberately left open at the end of Step 2b. Step 2c does not begin
until these are resolved or the relevant decisions are deferred to Phase 2.

- **Antora's actual PlaybookEntry content.** The positions, Patterns, constraints, and
  template references for each (ContractType, Category, SubClause) combination are the
  primary deliverable of Step 2c. This document provides the shape; Step 2c provides
  the substance.

- **Sandelin's input on signature_blocker designations, always-require-legal-review
  categories, and LRS structure.** Several PlaybookEntry judgment calls — which SubClauses
  are signature blockers, which Categories require legal review on any concession — depend
  on input from Sandelin (Antora's legal counsel). Sandelin meeting is pending.

- **Initial Overlay content.** Deferred by design. Overlays are authored when the first
  negotiation surfaces the need for a standing tightening posture on a specific
  counterparty/project/commodity. Speculating about overlays before real patterns emerge
  produces noise, not signal.

- **ConcessionLog storage implementation.** RuntimeConcession instances need a queryable
  store. Implementation is deferred to Phase 2a alongside other Layer C wiring decisions.

- **Authorization workflow mechanism.** How AuthorizationEvents are actually collected —
  Slack approval bot, email confirmation, web UI — is a Layer C deployment decision
  deferred until after the Sandelin call and Phase 2 infrastructure planning.

---

## Schema design decisions deliberately deferred

The following were explicitly considered and put aside during Step 2b. They are recorded here
so that future-Vincent knows these are not oversights.

Four minor refinements identified during pilot entry validation (2026-05-29) have been applied
to this document and are no longer listed as deferred: dropping `is_signature_blocker` boolean,
adding three-value review tracking, establishing `template_ref.version` semantic versioning
via TemplateRegistry, and adding `pending_items` / `examples` / `related_entries` as
structured top-level fields on PlaybookEntry.

- **Fourth overlay axis (geography, regulatory tier, value tier).** The axis enum is the
  extension point. Add a fourth value when authoring real overlays reveals that none of the
  three baseline axes (counterparty, project, commodity) fits the risk pattern. Do not add
  speculatively.

- **`match_criteria` field on Pattern.** Four fields (id, description, example_language,
  rationale) are sufficient for LLM-based matching in the first implementation. Add a fifth
  field only if empirical testing shows description + example_language are insufficient for
  reliable clause matching in practice.

- **`detection_pattern` field on CrossClauseDependency.** Dependency analysis is triggered
  by entry lookup (any involved PlaybookEntry touched in a redline), not by pattern matching.
  The LLM interprets interactions semantically. This avoids the premature formalization of
  what is inherently a semantic judgment.

- **`sub_sub_clauses` content for Antora.** The field exists; the convention is to leave it
  empty. Third-level SubClauses are permitted for future deployers. Antora does not need them
  for the initial playbook.

- **Promotion automation.** ConcessionPromotion is always a deliberate human act with
  explicit authorization. Agent 9 surfaces patterns; humans decide. No automatic promotion
  path will be added.
