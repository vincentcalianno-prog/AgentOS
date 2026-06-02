# Standing HTML refresh — run in Claude Code
Brings the ACP HTML reference docs current. EDIT-FORWARD, never regenerate.
Current: docs/architecture/  ·  Prior: docs/architecture/archive/  ·
History: docs/architecture/CHANGELOG.md

STEP 0 — PRECHECK
- mkdir -p docs/architecture/archive
- git log --oneline -6  → record current HEAD.
- Find the single acp_architecture_v*.html and single
  acp_layer_c_team_overview_v*.html in docs/architecture/ top level.
  If either has !=1 match, STOP AND ASK.

STEP 1 — REFRESH NEEDED?
- Open the architecture doc; read the HEAD it is pinned to (meta "HEAD" line).
- git log <pinnedHEAD>..HEAD --oneline
- If empty → "already current," change nothing, skip to STEP 4.
- Else that commit list is THE DELTA.

STEP 2 — ARCHITECTURE DOC: EDIT FORWARD (text only)
No changes to HTML structure, CSS, classes, colors, diagram markup, layout.
a. Copy current file into docs/architecture/archive/ (keep its filename).
b. In the top-level file apply ONLY:
   - Bump version v(N)->v(N+1) in eyebrow, <title>, footer; date = today.
   - Update CURRENT-STATE refs to live values: meta HEAD line, "Where we sit"
     HEAD + test count (run `python3 -m pytest acp/layer_b/tests/ -q`).
   - PRESERVE HISTORICAL refs unchanged: any SHA beside a past-event
     description (e.g. "wired @ <sha>", commit-trail rows). If unsure, STOP.
   - Per delta commit: flip statuses it changed (pending->committed, etc.);
     fill any placeholder SHA now known. NEVER invent a SHA.
   - Replace "Delta from snapshot v(N-1)" cards with a fresh
     "Delta from snapshot v(N)" set (reuse card markup; change text).
   - Keep the "unverified against repo" banner.
c. Rename top-level file to acp_architecture_v(N+1)_<today>.html.

STEP 3 — TEAM OVERVIEW DOC
Bump ONLY if the delta changed something team-facing (workflow step, gate,
savings story). Else leave as-is. If bumped: same edit-forward + archive +
rename; non-technical (no SHAs, no _PILOT_ANTORA_RESPONSES).

STEP 4 — REGISTER + LOG + COMMIT
- Verify one-version-per-doc in docs/architecture/ (priors in archive/).
- Update current-filename line(s) in PROJECT_CONTEXT.md "HTML reference docs".
- Prepend an entry to docs/architecture/CHANGELOG.md (newest first):
    ## v(N+1) — <today>
    - File: <new filename>   (prior archived: archive/<old filename>)
    - Architecture pinned HEAD: <newHEAD>
    - Delta folded in: <git log oldHEAD..newHEAD --oneline, one line each>
    - Team overview: <"bumped: <what>" or "unchanged">
    - Retract: restore archive/<old filename>, or
      `git checkout <commit-before-this> -- docs/architecture/<new filename>`
- git add docs/architecture docs/PROJECT_CONTEXT.md
- PRE-COMMIT:
  1. HTML guard — curly quotes inside tags must be zero:
       python3 -c "
       import re, sys
       text = open('docs/architecture/acp_architecture_v<N+1>_<today>.html', encoding='utf-8').read()
       hits = [m.group()[:80] for m in re.finditer(r'<[^>]+>', text, re.DOTALL)
               if any(ch in m.group() for ch in '\u201c\u201d\u2018\u2019')]
       sys.exit('\n'.join(hits) or None)
       "
     Fail → fix the smart-quoted attribute before committing.
  2. Eyeball check — open the file in a browser (or Quick Look) and confirm
     the intro paragraph and section headers render with their styled fonts/colors.
     If the intro is unstyled plain text, a curly-quoted class attribute broke it.
  3. python3 acp/discipline_check.py   (4/4)
  4. python3 -m pytest acp/layer_b/tests/ -q
- COMMIT: docs: refresh HTML reference doc(s) to current state (prior archived)

DO NOT TOUCH: legal templates, inputs/, pilot_entries/, agent code, ontology.md.
STOP AND ASK IF: !=1 version per doc, a ref is ambiguous, layout would need
restructuring, discipline fails, or a test breaks.
