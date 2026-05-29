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

## Schema refinements queued

Pilot entry creation surfaced four minor schema refinements to address before
full Step 2c content authoring begins:

1. Drop `is_signature_blocker` boolean from PlaybookEntry; let `negotiability`
   enum be the source of truth.
2. Add `review_status` field to PlaybookEntry for provisional/draft content
   that hasn't been Sandelin-validated.
3. Establish `template_ref.version` convention (or switch to template tags/hashes).
4. Restructure `metadata.notes` or split it into additional structured fields.

These are polish, not redesigns. The 13-entity schema model fundamentally held
under real content.
