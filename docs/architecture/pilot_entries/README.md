# ACP playbook pilot entries

Drafts of Layer C playbook content created during Step 2b/2c transition for
schema validation and Sandelin meeting preparation. These are NOT locked Antora
positions — they are working drafts that will be validated, edited, or replaced
when real Step 2c content authoring lands in `acp/layer_c_antora/playbook/`
during Phase 2a.

## Purpose

Pilot entries serve three functions:

1. **Schema validation.** Each pilot stress-tests the locked schemas
   (see `docs/architecture/playbook_schemas.md`) against real Antora content
   to surface gaps before full content authoring.

2. **Sandelin meeting prep.** Pilots become concrete examples Sandelin can
   react to rather than abstract questions she has to answer cold.

3. **Future Layer C content seed.** When Phase 2a content authoring begins,
   pilot entries can be promoted (with Sandelin edits) to real Layer C
   content in `acp/layer_c_antora/playbook/`.

## Index

| Pilot | (ContractType, Category, SubClause) | Created | Status |
|-------|-------------------------------------|---------|--------|
| `mepa_lol_direct_damages.md` | (MEPA, Limitation of Liability, Direct Damages Clarification) | 2026-05-29 | Draft, pending Sandelin review |

## Schema refinements applied 2026-05-29

Pilot entry creation surfaced four minor refinements. All four have been applied to
`docs/architecture/playbook_schemas.md` and to the pilot entry in the same commit:

1. Dropped `is_signature_blocker` boolean; `negotiability: signature_blocker` is the source of truth.
2. Added three-value review tracking (`review_status` / `last_reviewed_by` / `last_reviewed_date`) to PlaybookEntry, Overlay, and CrossClauseDependency.
3. Established `template_ref.version` as semantic versions (e.g., `v1.0`) resolved via new TemplateRegistry entity (Entity 14).
4. Added `pending_items`, `examples`, and `related_entries` as structured top-level fields on PlaybookEntry; `metadata.notes` remains freeform.

The 14-entity schema model held under real content.
