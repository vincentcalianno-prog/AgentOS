# HTML reference docs — changelog
Newest first. Git history is the authoritative record; this is the readable
index. To retract a version, restore the archived file named in its entry or
`git checkout <sha> -- docs/architecture/<file>`.

## v6 — 2026-06-01
- File: acp_architecture_v6_2026-06-01.html   (prior archived: archive/acp_architecture_v5_2026-05-31.html)
- Architecture pinned HEAD: dc8eec8
- Delta folded in (4f90cff..dc8eec8):
  - 487920c docs: commit ACP HTML reference docs v5 + reproduction protocol
  - 4d3bee6 docs: add HTML changelog + refresh prompt; de-hardcode pointer (archive convention)
  - 5690c89 playbook: add risk_of_loss, inspection_acceptance, net_terms — Sprint 1 cluster A+B entries (provisional, draft)
  - cb86008 feat: Layer B loaders (playbook/skill/prompt) + overlay resolver — local, deployment-agnostic
  - dfbd1ca feat: wire Layer B loaders + resolver into analysis path; first Layer C dry-run (stub LLMs, synthetic fixture)
  - 1d45a3c fix: unify negotiability vocabulary to signature_blocker (schema/entries/analyzer)
  - dc8eec8 docs: define negotiability tiers in ontology.md (canonical source); cross-reference from loader/schema
- Team overview: unchanged (delta is internal/technical — no workflow step, gate, or savings story changed)
- Retract: restore archive/acp_architecture_v5_2026-05-31.html, or
  `git checkout <commit-before-this> -- docs/architecture/acp_architecture_v6_2026-06-01.html`

## v5 — 2026-05-31  (baseline)
- Files: acp_architecture_v5_2026-05-31.html, acp_layer_c_team_overview_v5.html
- Architecture pinned HEAD: 4f90cff  ·  committed to repo at 487920c
- Versions v1–v4 predate this changelog (shared in chat; not archived in-repo)
- Retract: n/a (baseline)
