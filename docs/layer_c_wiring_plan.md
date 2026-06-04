# Layer C Wiring Plan — ACP against Antora's Real Systems

**Status:** Planning document (pre-implementation)
**Branch:** feature/acp-phase1-migration
**Layer B baseline:** 407 tests passing, discipline check clean

---

## 1. Purpose and Scope

Layer C is the Antora-specific deployment shell that wires Layer B's injectable interfaces to real external systems. Layer B agents contain zero provider SDK imports; all external dependencies are injected as typed callables or adapter instances at construction time. Layer C owns those callables.

**In scope for Layer C wiring:**
- Gmail OAuth — injected as `InboxAdapter` for Agent 1 (Email Watcher)
- Google Drive OAuth — injected as `StorageAdapter` for Agent 2 (Document Extraction)
- Anthropic SDK calls — injected as `AnalyzeClauseFn`, `DraftCounterProposalFn`, `RenderLRSFn` for Agents 5, 6, 7
- Notification delivery — injected via `WorkflowOrchestratorConfig.credentials` + `route_notification` wiring for Agent 8
- `WorkflowOrchestratorConfig` populated with Antora's real operational values (SLAs, playbook refs, org chart)
- `TenantContext` provisioning — Antora's user → tenant mapping

**Not in scope for Layer C (deferred):**
- Multi-tenant admin UI
- Workflow #2 (RFQ analysis, supplier risk)
- Per-user preference overrides (Phase 4 peer pilot)

**The Layer B/C seam contract:**
Layer C may only interact with Layer B through:
1. Constructor injection of typed callables and adapter instances
2. Calling `agent.process_event(context, event)` or `agent.poll(...)` (Email Watcher)
3. Subscribing to agent output via `agent.subscribe(callback)`
4. Reading `StateEvent`, `NegotiationRow`, `AuditEvent`, and output dataclasses (frozen; read-only from Layer C)

**Layer C directory naming convention:**
Layer C directories follow the pattern `layer_c_<deployment_name>/`. This plan covers the Antora deployment specifically: `acp/layer_c_antora/`. A future deployment for another organization would create `acp/layer_c_<other_org>/` alongside it, sharing the same Layer B agents without modification.

---

## 2. Knowledge Architecture

Three distinct knowledge artifact types feed the LLM calls in Layer C. They are different in form and purpose and must not be conflated.

### 2a. Playbook

The playbook is **structured config data** — Antora's negotiation doctrine expressed as Python dataclasses or YAML. It encodes positions, fallback positions, and red-line thresholds for each clause category. This is not prose; it is machine-readable structured data that flows into prompt templates at call time.

**Lives in:** `acp/layer_c_antora/playbook/`

**Example structure:**
```yaml
# acp/layer_c_antora/playbook/payment_terms.yaml
clause_ref_pattern: "^(2\\.\\d+|3\\.\\d+)"
operator_position: "Net-30 from invoice date. Late fee 1.5%/month."
fallback_position: "Net-45 acceptable only with early-pay discount of ≥1%."
red_line: "Net > 60 days is a signature blocker."
```

**Design decision required:** Choose storage format:

| Option | Description | Tradeoffs |
|---|---|---|
| A. YAML files in private config repo | Checked in; loaded at startup | Simple; version-controlled; no runtime dependency |
| B. Drive-hosted doc | Playbook in a specific Drive doc; fetched at startup | Always current; editable without a deploy |
| C. Python dataclasses in `layer_c_antora/playbook/` | Typed; IDE-navigable | Requires a code change for every playbook edit |

**Recommendation:** Option A for Phase 2 (simple, auditable); Option B for Phase 3+ once the playbook content stabilizes.

**Minimum playbook content needed before Layer C launch:**
- Standard position on payment terms (net-N, late fees, early-pay discounts)
- Standard position on indemnification (mutual vs. unilateral)
- Standard termination notice period
- Standard force majeure definition scope
- Absolute red lines (clauses that are always signature blockers regardless of LLM output)

### 2b. Skills

Skills are **LLM-consumable knowledge modules** following the Anthropic SKILL.md standard: a YAML frontmatter block (`name`, `description`) followed by a Markdown body that the model reads as reference material during a task. Skills are not prompt templates — they are knowledge the model consults. They are cross-AI-tool portable (not tied to a specific SDK call structure).

**Lives in:** `acp/layer_c_antora/skills/`

**Initial skills:**

| File | Purpose |
|---|---|
| `clause-analysis-liability.md` | Explains how to evaluate indemnification, limitation-of-liability, and insurance clause redlines against Antora's risk posture |
| `clause-analysis-payment-terms.md` | Explains how to evaluate payment, milestone, and late-fee clause redlines |
| `counter-language-drafting.md` | Explains how to draft compromise counter-language that preserves Antora's core position |
| `counter-language-restoration.md` | Explains how to restore deleted or impaired clauses verbatim vs. when to paraphrase |

**SKILL.md format:**
```markdown
---
name: clause-analysis-liability
description: How to evaluate liability clause redlines against Antora Energy's risk posture
---

## Background
Antora Energy operates as an operator in long-term energy purchase agreements.
Mutual indemnification is a baseline requirement...

## Evaluation criteria
1. Is indemnification still mutual after the redline?
...
```

Skills are loaded by the Layer C LLM callable and passed to the model as reference context (e.g., in the `user` turn or as a prefill block), not hardcoded into the system prompt.

### 2c. Prompt Templates

Prompt templates are the **system prompt constants** in each Layer C LLM Python file — the `SYSTEM_PROMPT` string that orchestrates the SDK call. They instruct the model on output format, JSON schema, and how to use the playbook data and skills that are injected at call time. Prompt templates are agent-specific; skills and playbook are shared knowledge.

**Lives in:** Each file in `acp/layer_c_antora/llm/` (e.g., `analyze_clause.py`'s `SYSTEM_PROMPT`, `draft_counter.py`'s `SYSTEM_PROMPT`).

**Guidance per agent:**

**Agent 5 (`AnalyzeClauseFn`) prompt template:**
- Instructs the model to apply `playbook_context` strictly and consult the clause-analysis skill
- Must produce structured JSON parseable to `ClauseRecommendation` dataclass fields
- Must set `is_signature_blocker=True` for clauses matching the playbook's red-line conditions
- Must set `requires_legal_review=True` for clauses outside standard playbook coverage
- Must include `round_number` context: note if a clause has appeared in multiple rounds without resolution

**Agent 6 (`DraftCounterProposalFn`) prompt template:**
- When `restore_strategy="verbatim"`, instructs the model to return `original_text` unchanged — no paraphrasing; Layer C post-call asserts `draft.counter_text == original_text`
- When `restore_strategy="redraft"`, instructs the model to draft compromise language anchored to `playbook_context` and consulting the counter-language skill
- Must produce structured JSON parseable to `CounterProposalDraft` fields

**Agent 7 (`RenderLRSFn`) prompt template:**
- Must produce an Executive Summary section (Finding G)
- Must include a Recommended Next Actions section (Finding H)
- Counter-proposal section must include the clause's original text and counterparty modification for context (Finding I)
- `signature_blockers` list must be prominently placed near the top of the document
- Output is Markdown; no preamble or postamble

**Summary of distinctions:**

| Artifact | What it is | Where it lives | Who edits it |
|---|---|---|---|
| Playbook | Structured positions/red-lines (YAML/dataclass) | `layer_c_antora/playbook/` | Vincent / ops |
| Skills | LLM-readable knowledge modules (SKILL.md) | `layer_c_antora/skills/` | Vincent / Sandelin |
| Prompt templates | Python system prompt strings per agent | `layer_c_antora/llm/*.py` | Developer |

---

## 2.5 Platform-level support for deployment content

While playbooks, skills, and prompt templates are deployment-specific content (Section 2), the platform provides shared infrastructure for loading and using them uniformly across any deployment. This infrastructure lives in Layer B and Layer A respectively.

### Layer B: Loaders and frameworks (built in Phase 2a)

Platform code that reads any deployment's Layer C content uniformly. Lives in `acp/layer_b/loaders/`:

- **`skill_loader.py`** — reads SKILL.md files from any `layer_c_<deployment_name>/skills/` directory; parses YAML frontmatter; surfaces skills as structured objects to LLM-driven agents
- **`playbook_loader.py`** — reads YAML files from any `layer_c_<deployment_name>/playbook/` directory; parses into structured Python objects; surfaces playbook context strings to agents
- **`prompt_registry.py`** — base classes for prompt templates; ensures consistent variable injection and output schema validation across deployments

These are platform plumbing — they contain no deployment-specific content. They get built in Phase 2a as part of wiring Antora's Layer C content, so they're battle-tested by real content from day one. Future deployments (`layer_c_<other_org>/`) point the same loaders at their own directories.

### Layer A: Authoring guides (deferred to Phase 2a-post)

Documentation that future deployments will reference when authoring their own Layer C content. Lives in `docs/authoring/`:

- **`playbook_authoring_guide.md`** — playbook schema specification, YAML structure, required vs. optional fields
- **`skills_authoring_guide.md`** — SKILL.md format conventions, how to write effective skills for ACP agents
- **`prompt_template_guide.md`** — prompt template patterns, variable injection conventions, output schema requirements

These are deliberately deferred until after Phase 2a is working end-to-end. Patterns documented before being validated by real content tend to be wrong in ways that aren't obvious until they're tested. The guides will be written in Phase 2a-post, informed by what actually worked when authoring Antora's content.

---

## 3. Anthropic SDK Integration

**SDK:** `anthropic` Python library (install via `pip install anthropic`). Import only in Layer C modules.

**Model selection:**
- Default: `claude-sonnet-4-6` (fast, cost-effective for per-clause analysis and counter-proposal drafting)
- Override for high-stakes analysis (large clause sets, round 3+): `claude-opus-4-7`
- Agent 1 `ClassifyFn`: use `claude-haiku-4-5-20251001` — email classification is a simple binary task; Haiku is substantially cheaper and fast enough for inbox polling latency
- Never import or reference model IDs in Layer B

**Layer C module structure (proposed):**

```
acp/
  layer_b/
    loaders/              # Platform loaders (Section 2.5) — no deployment-specific content
      skill_loader.py
      playbook_loader.py
      prompt_registry.py
  layer_c_antora/
    __init__.py
    llm/
      __init__.py
      client.py           # constructs anthropic.Anthropic(); shared client singleton
      classify.py         # ClassifyFn implementation (uses Haiku)
      extract_metadata.py # ExtractMetadataFn implementation
      analyze_clause.py   # AnalyzeClauseFn implementation (uses Sonnet; Opus override available)
      draft_counter.py    # DraftCounterProposalFn implementation
      render_lrs.py       # RenderLRSFn implementation
    adapters/
      gmail_inbox.py      # InboxAdapter implementation
      drive_storage.py    # StorageAdapter implementation
    playbook/             # YAML playbook files (Section 2a)
    skills/               # SKILL.md knowledge modules (Section 2b)
    config/
      antora_config.py    # WorkflowOrchestratorConfig values
    wiring/
      pipeline.py         # Top-level wiring: construct all agents, wire subscriptions
      notification.py     # Route EVENT_NOTIFICATION_REQUIRED to real delivery channels
```

**`client.py` pattern:**
```python
# acp/layer_c_antora/llm/client.py
import anthropic
import os

_client: anthropic.Anthropic | None = None

def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client
```

**`analyze_clause.py` skeleton:**
```python
from acp.layer_b.agents.redline_analysis import ClauseRecommendation, AnalyzeClauseFn
from acp.layer_b.loaders.playbook_loader import PlaybookLoader
from acp.layer_b.loaders.skill_loader import SkillLoader
from acp.layer_c_antora.llm.client import get_client
import json

SYSTEM_PROMPT = """..."""  # Antora's analysis doctrine (prompt template; see Section 2c)

def make_analyze_clause_fn(model: str = "claude-sonnet-4-6") -> AnalyzeClauseFn:
    def analyze(clause_reference, change_type, original_text, counterparty_text,
                playbook_context, round_number) -> ClauseRecommendation:
        client = get_client()
        response = client.messages.create(
            model=model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": _build_prompt(
                clause_reference, change_type, original_text,
                counterparty_text, playbook_context, round_number
            )}],
        )
        raw = json.loads(response.content[0].text)
        return ClauseRecommendation(**raw)
    return analyze
```

**Error handling contract for LLM callables:**
- On `anthropic.APIError` or `anthropic.APIConnectionError`: raise — Layer B agents' caller (`process_event`) will catch and emit the appropriate retry or escalation event
- On JSON parse failure: raise `ValueError` with the raw response attached — triggers same escalation path
- Do NOT swallow errors silently in Layer C — Layer B's retry machinery needs to see them

**Rate limiting:**
- Agent 5 and Agent 6 each make one API call per clause. A 20-clause redline = 40 calls.
- Add optional `asyncio` concurrency or `tenacity` retry decorator at the Layer C callable level, not in Layer B
- Recommended: `tenacity.retry(wait=tenacity.wait_exponential(min=1, max=10), stop=tenacity.stop_after_attempt(3))`

---

## 4. Gmail OAuth Integration

Agent 1 (`EmailWatcher`) depends on an `InboxAdapter` with two methods:
- `poll(context, since, active_thread_ids) -> list[InboundMessage]`
- `mark_processed(context, message_id) -> None`

And an injectable `ClassifyFn(subject: str, body: str) -> str`.

Config keys the agent reads from its config dict:
- `label_filter` — Gmail label to restrict polling to (e.g. `"ACP/Inbound"`)
- `automation_active_statuses` — list of `NegotiationRow.automation_status` values that mean "active" for dedup

**Gmail OAuth setup steps:**
1. Create a Google Cloud project (or use an existing Antora project)
2. Enable the Gmail API
3. Create OAuth 2.0 credentials (type: Desktop or Service Account depending on Antora's auth posture)
4. Scopes required: `https://www.googleapis.com/auth/gmail.readonly`, `https://www.googleapis.com/auth/gmail.modify` (for marking messages processed via label)
5. Store credentials in environment: `GOOGLE_OAUTH_CREDENTIALS_JSON` (path to credentials file) or equivalent secret manager entry

**`GmailInboxAdapter` implementation notes:**
- Use `google-api-python-client` + `google-auth-oauthlib`
- `poll()`: call `users.messages.list` with `labelIds=[label_filter]`, filter by `internalDate >= since.timestamp()`, fetch message bodies, deserialize to `InboundMessage`
- `mark_processed()`: apply a "ACP/Processed" label (do not delete — preserve audit trail in Gmail)
- Thread dedup: `active_thread_ids` comes from SM's `list_rows()` on the ledger — the adapter returns only messages whose thread ID is not already in the set

**`InboundMessage` fields (from Layer B contract):**
- `message_id: str`
- `thread_id: str`
- `sender: str`
- `subject: str`
- `body_text: str`
- `attachments: list[Attachment]` (each has `filename`, `content_type`, `data: bytes`)
- `received_at: datetime`

**ClassifyFn deployment note:**
- The dry-run harness uses a rule-based classifier (subject line keyword matching)
- Layer C replaces this with `acp.layer_c_antora.llm.classify.make_classify_fn()`, backed by `claude-haiku-4-5-20251001` — fast and cheap for a binary classification task
- Fallback: if LLM call fails, fall back to rule-based classifier — a classify failure should not block polling

---

## 5. Google Drive OAuth Integration

Agent 2 (`DocumentExtractor`) depends on a `StorageAdapter` and an `ExtractMetadataFn`.

Config keys:
- `storage_root` (required) — root path/Drive folder ID where documents are stored

Storage path schema used by Layer B:
```
{storage_root}/{contract_type}/{counterparty_ref}/round_{N}/{timestamp}_{attachment_id}.bin
```

**Drive OAuth setup steps:**
1. Enable Google Drive API in same Cloud project as Gmail
2. Add scope: `https://www.googleapis.com/auth/drive.file` (create/read files the app created) or `https://www.googleapis.com/auth/drive` if reading pre-existing contracts is needed
3. `storage_root` in Antora's deployment = a specific Drive folder ID (the "ACP Contracts" folder)

**`DriveStorageAdapter` implementation notes:**
- Lives in `acp/layer_c_antora/adapters/drive_storage.py`
- `write(path: str, data: bytes) -> None`: use `files.create` with `parents=[folder_id]`; path becomes the file name
- `read(path: str) -> bytes`: use `files.get` with `alt=media`
- Path handling: convert the Layer B path format (`{storage_root}/{contract_type}/...`) to Drive's folder hierarchy — either flatten to a single folder with a long filename, or create a real folder tree
- **Recommendation:** Flatten for Phase 2 (simpler); migrate to folder tree in Phase 3

**`ExtractMetadataFn` deployment note:**
- Signature: `Callable[[bytes], tuple[int, int, int]]` → `(page_count, clause_count, word_count)`
- For PDF attachments: use `PyMuPDF` (fitz) for page count; heuristic for clause count (count `### N.N` or `\d+\.\d+` headings)
- For DOCX: use `python-docx`
- Layer C must detect content type from the attachment's `content_type` field (from Gmail) before choosing the extractor

**Structural diff dependency:**
Agent 4 (`StructuralDiff`) reads the stored document via `StorageAdapter.read()`. The path is passed through in the `EVENT_DOCUMENT_EXTRACTED` payload as `storage_path`. Layer C does not need to do anything special here — SM already propagates `storage_path` in its re-emit handlers.

---

## 6. Notification Delivery

Agent 8's `route_notification()` method matches an incoming `EVENT_NOTIFICATION_REQUIRED` event against the `WorkflowOrchestratorConfig.playbook.notification_routes` list (each route has an `event_pattern` and `workflow_id` matcher). It returns a `NotificationRoute` object telling Layer C: which channel to use, which template to render, and who to address.

**Layer C responsibility:** After calling `orchestrator.route_notification(event)`, Layer C sends the notification. Layer C is responsible for delivery only — not for emitting platform lifecycle events (see `EVENT_NEGOTIATION_FAILED` note below).

**Channels required for Phase 2 (Antora solo pilot):**
1. Email (Gmail send) — for LRS-ready notifications to Vincent
2. Slack — for degraded-mode alerts and retry-exhaustion escalations

**Gmail send:**
- Additional scope: `https://www.googleapis.com/auth/gmail.send`
- Use `users.messages.send` with an RFC 2822 message body
- Template: `LRS_READY` → "A new Legal Review Summary is ready for negotiation {negotiation_id} with {counterparty_description}. [Link to Drive document]"

**Slack:**
- Use Slack webhook URL (Incoming Webhooks app) — simpler than full Bot OAuth for Phase 2
- Store webhook URL in environment: `SLACK_ACP_WEBHOOK_URL`
- Template: `RETRY_EXHAUSTED` → "@vincent — ACP event retry exhausted for negotiation {negotiation_id}, clause batch {round_number}. Manual intervention required."
- Template: `DEGRADED_MODE_ENTERED` → "ACP pipeline paused (degraded mode). Reason: {reason}. All new redline processing is halted until resumed."

**Wiring pattern:**
```python
# In acp/layer_c_antora/wiring/notification.py
from acp.layer_b.agents.workflow_orchestrator import WorkflowOrchestratorAgent

def wire_notification_handler(orchestrator: WorkflowOrchestratorAgent, notifier):
    orchestrator.subscribe(lambda event: _handle_notification_event(event, orchestrator, notifier))

def _handle_notification_event(event, orchestrator, notifier):
    if event.event_type == "EVENT_NOTIFICATION_REQUIRED":
        route = orchestrator.route_notification(event)
        if route:
            notifier.send(route, event)
```

**`EVENT_NEGOTIATION_FAILED` emission — belongs in Layer B, not Layer C:**
The original plan placed `EVENT_NEGOTIATION_FAILED` emission in Layer C's notification handler. This is wrong: different deployments would each need to duplicate the same platform lifecycle logic. This is a Layer B platform responsibility.

**Recommended resolution (Option B — SM passthrough):** State Manager's `_handle_platform_passthrough`, which already handles `EVENT_RETRY_EXHAUSTED` from Agent 8, should emit `EVENT_NEGOTIATION_FAILED` as a side effect when retry exhaustion is confirmed. This is consistent with SM's existing re-emit pattern and keeps the `automation_status → "Failed"` transition inside Layer B where it belongs.

This requires a small Layer B change (add the `EVENT_NEGOTIATION_FAILED` emit to `_handle_platform_passthrough` in `state_manager.py`). **Flag as a Phase 2-pre prerequisite alongside Finding F** — must land before Phase 2a starts.

---

## 7. Deployment Contract — Antora's Values

`WorkflowOrchestratorConfig` has 5 frozen sub-configs. These are the Antora-specific values that fill them:

### 7a. CredentialsConfig

| Field | Antora value source |
|---|---|
| `anthropic_api_key_env` | `ANTHROPIC_API_KEY` (env var; set in deployment environment) |
| `gmail_credentials_path_env` | `GOOGLE_OAUTH_CREDENTIALS_JSON` (env var; path to credentials JSON) |
| `drive_credentials_path_env` | Same credentials file as Gmail (scopes combined) |
| `slack_webhook_url_env` | `SLACK_ACP_WEBHOOK_URL` (env var; Incoming Webhooks URL) |
| `notification_email_from` | TBD — Antora's ops email address |

### 7b. OperationalConfig

| Field | Antora value |
|---|---|
| `sla_analysis_hours` | 4 (Vincent reviews within a business half-day) |
| `sla_counter_proposal_hours` | 8 (within a business day) |
| `sla_lrs_hours` | 24 (legal review can take a full day) |
| `max_retry_attempts` | 3 |
| `retry_backoff_seconds` | 60 |
| `poll_interval_seconds` | 300 (5 min; runs as a cron or daemon) |
| `inbox_label_filter` | `"ACP/Inbound"` (Gmail label Vincent applies to counterparty emails) |
| `automation_active_statuses` | `["Active", "UnderReview", "AwaitingCounterparty"]` |

### 7c. KnowledgeConfig

| Field | Antora value |
|---|---|
| `playbook_path` | Path to the `layer_c_antora/playbook/` directory (or Drive folder ID if Drive-hosted) |
| `default_contract_type` | `"master-energy-purchase-agreement"` |
| `notification_routes` | See Section 6 above — at minimum: LRS_READY → email, RETRY_EXHAUSTED → Slack, DEGRADED_MODE → Slack |
| `lookup_failure_policy` | `"warn"` (if a message can't be matched to a negotiation_id, log and continue; do not crash) |

### 7d. OrganizationConfig

| Field | Antora value |
|---|---|
| `tenant_id` | `"antora"` (Phase 2 is single-tenant; will extend when peer pilot adds more operators) |
| `operator_name` | `"Antora Energy"` |
| `operator_contact_email` | Vincent's email (for notification routing) |
| `legal_reviewer_email` | TBD — Sandelin or Antora's legal counsel |
| `escalation_contact` | TBD — for retry-exhausted escalation |

### 7e. ExtensionsConfig

| Field | Antora value |
|---|---|
| `storage_root` | Drive folder ID for "ACP Contracts" folder |
| `lrs_output_folder` | Drive folder ID for "ACP Legal Review Packages" folder |
| `audit_log_sink` | Phase 2: SQLite file. Phase 3+: consider Cloud SQL or BigQuery for multi-tenant audit |
| `dry_run_mode` | `False` in production; `True` for harness runs |

---

## 8. Migration Plan: Dry-Run Harness → Layer C

The dry-run harness in `scripts/real_redline_dry_run/` is the starting point for Layer C wiring. Each phase below replaces one set of stubs with a real implementation.

### Phase 2-pre — Prerequisites (must complete before Phase 2a)

Two Layer B changes are required before the first real SDK wiring can land cleanly:

**1. Finding F — `original_text` plumbing**

`original_text` lives in `DiffEntry` (Agent 4 output) but is not carried into `ClauseRecommendation` (Agent 5 output). Agent 6's `_draft_one` checks `rec.get("original_text", "")` and always gets an empty string, so `restore_strategy` falls through to `"redraft"` even for `is_signature_blocker=True` clauses.

Resolution (Option A — recommended): add `original_text: str = ""` to `ClauseRecommendation` in `redline_analysis.py`; pass it through in `_analyze_entry`. Small Layer B change; backward-compatible.

Steps:
1. Add `original_text: str = ""` to `ClauseRecommendation`
2. In `_analyze_entry`, read `original_text` from the diff entry dict and pass to the constructor
3. Update `_null_analyzer` to accept and ignore the passthrough
4. Add 2 tests: (a) `original_text` carried from diff entry into recommendation, (b) `_draft_one` uses verbatim path when `is_signature_blocker=True` and `original_text` non-empty
5. Run discipline check and full test suite before committing

**2. `EVENT_NEGOTIATION_FAILED` — SM passthrough**

Add `EVENT_NEGOTIATION_FAILED` emission to SM's `_handle_platform_passthrough` when processing `EVENT_RETRY_EXHAUSTED`. This keeps the `automation_status → "Failed"` lifecycle transition in Layer B and removes any need for Layer C to emit platform events.

Steps:
1. In `state_manager.py`, extend `_handle_platform_passthrough` to emit `EVENT_NEGOTIATION_FAILED` for `EVENT_RETRY_EXHAUSTED` events
2. Add 1 integration test: exhausted retry → SM emits `EVENT_NEGOTIATION_FAILED` → `NegotiationRow.automation_status == "Failed"`
3. Update `discipline_check.py` if needed; run full test suite

**Exit criteria for Phase 2-pre:** All tests pass; discipline check clean; harness smoke test still passes.

---

### Phase 2a — Anthropic SDK + Layer B loaders (Agents 5, 6, 7)

**Goal:** Build the platform loader infrastructure, author Antora's deployment content (playbook YAML, skill files, prompt templates), and replace the three stub LLM callables with real SDK calls.

**Entry criteria:** Phase 2-pre complete; API key available in environment; Sandelin's confidentiality questions answered (Section 9, questions 5 and 6).

**Steps:**

*Layer B loader infrastructure (no Antora-specific content):*

0a. Write `acp/layer_b/loaders/playbook_loader.py` — abstract loader interface; reads YAML files from a configurable deployment directory; parses into structured Python objects. Test against Antora's playbook YAML files. Aim for ~10 tests.

0b. Write `acp/layer_b/loaders/skill_loader.py` — abstract loader interface; reads SKILL.md files with YAML frontmatter from a configurable deployment directory; surfaces skills as structured objects. Test against Antora's skill files. Aim for ~10 tests.

0c. Write `acp/layer_b/loaders/prompt_registry.py` — base classes for prompt templates with variable injection and output schema validation. Test against Antora's prompt templates. Aim for ~8 tests.

*Antora Layer C deployment content:*

1. Write `acp/layer_c_antora/llm/analyze_clause.py` — implement `AnalyzeClauseFn` using `PlaybookLoader` and `SkillLoader`; write the `SYSTEM_PROMPT` template
2. Write `acp/layer_c_antora/llm/draft_counter.py` — implement `DraftCounterProposalFn`; handle `restore_strategy="verbatim"` with a post-call assertion (`assert draft.counter_text == original_text`)
3. Write `acp/layer_c_antora/llm/render_lrs.py` — implement `RenderLRSFn`; ensure Executive Summary, Recommended Actions, and clause context are rendered (Findings G, H, I)
4. Create `acp/layer_c_antora/tests/test_llm_integration.py` — calls real SDK with a known clause sample and asserts output parses to the correct dataclass; mark `@pytest.mark.integration` so it's skipped in CI by default
5. Run the full dry-run harness with SDK stubs replaced by real callables; verify all 8 artifacts still produce

**Exit criteria:** All 407+ Layer B tests still pass; ~28 new tests for the loaders; loaders contain no Antora-specific content; harness smoke test passes with real LLM output; `discipline_check.py` clean.

---

### Phase 2b — Google Drive StorageAdapter

**Goal:** Replace `_HarnessStorageAdapter` (file-backed) with `DriveStorageAdapter`.

**Entry criteria:** Drive OAuth credentials configured; "ACP Contracts" folder created in Drive.

**Steps:**
1. Write `acp/layer_c_antora/adapters/drive_storage.py`
2. Configure `storage_root` = Drive folder ID in `ExtensionsConfig`
3. Wire `DriveStorageAdapter` into `pipeline.py` in place of file adapter
4. Run harness with Drive adapter; verify attachments read/write correctly
5. Test with a real MEPA PDF or DOCX attachment

**Exit criteria:** All 8 harness artifacts produced; documents readable in Drive.

---

### Phase 2c — Gmail InboxAdapter + ClassifyFn

**Goal:** Replace harness's direct document injection with real Gmail polling.

**Entry criteria:** Gmail OAuth credentials configured; "ACP/Inbound" label created; at least one test redline email available.

**Steps:**
1. Write `acp/layer_c_antora/adapters/gmail_inbox.py`
2. Write `acp/layer_c_antora/llm/classify.py` (Haiku-backed classification with rule-based fallback)
3. Wire `GmailInboxAdapter` and `make_classify_fn()` into Agent 1 constructor
4. Run Agent 1 in isolation: `email_watcher.poll(ctx, since=datetime.now()-timedelta(hours=24), active_thread_ids=set())`
5. Verify `EVENT_INBOUND_REDLINE_RECEIVED` emits for a real redline email and is ignored for a non-redline email

**Exit criteria:** Agent 1 correctly classifies a sample redline email; harness can be extended to use live inbox in a "live poll" mode.

---

### Phase 2d — End-to-End Live Run

**Goal:** Full pipeline run with all real integrations, one real negotiation.

**Entry criteria:** Phases 2a–2c complete; counterparty sends a real redlined MEPA to Vincent's inbox (or a synthetic test email is planted manually).

**Steps:**
1. Configure all 5 sub-configs with Antora's real values
2. Run `pipeline.py` (the top-level wiring module) as a one-shot process (not daemon) to process one email
3. Verify all 8 artifacts in Drive
4. Verify LRS document is readable and covers the redlined clauses accurately
5. Verify notification is delivered (email or Slack)
6. Verify audit log records all events with correct `workflow_id`, `tenant_id`, `negotiation_id`
7. Check that no Layer B agent imports anything from `acp.layer_c_antora.*`

**Exit criteria:** Full audit trail; LRS readable by Sandelin; discipline check still clean.

---

### Phase 2a-post — Authoring guides (Layer A documentation)

**Goal:** Extract patterns from the working Antora deployment into authoring guides that future deployments can reference when building their own `layer_c_<deployment_name>/` content.

**Entry criteria:** Phase 2d complete; Antora's Layer C content has been validated against at least one real negotiation; the live run produced a usable LRS.

**Steps:**
1. Write `docs/authoring/playbook_authoring_guide.md` — document the playbook YAML schema that proved necessary, with examples from Antora's playbook. Include a "Common mistakes" section based on what went wrong during Phase 2a authoring.
2. Write `docs/authoring/skills_authoring_guide.md` — document the SKILL.md patterns that produced effective LLM reasoning, with examples from Antora's four initial skills. Include guidance on description-field crafting (Anthropic's trigger-routing concern) and the process-vs-context separation.
3. Write `docs/authoring/prompt_template_guide.md` — document the prompt template patterns that produced reliable structured output, with examples from Antora's `analyze_clause`, `draft_counter`, and `render_lrs` templates.
4. Each guide must include: (a) the schema/format spec, (b) at least 2 working examples drawn from Antora's deployment, (c) a "Common mistakes" section, (d) a "When this is the wrong choice" section to help future authors recognize when they need a different approach.

**Exit criteria:** A hypothetical second deployment could author their Layer C content using only these guides plus their own domain expertise. No knowledge of Antora's specific content should be required to follow the patterns.

---

## 9. Questions for Sandelin

Sandelin is Antora's legal counterpart for the ACP pilot. Before writing the LRS rendering prompt (Phase 2a, step 3) and the playbook (Section 2a), the following questions need answers:

1. **Signature blocker definition:** What is Antora's precise threshold for calling a clause a "signature blocker"? Is it purely about indemnification and liability, or does it include payment terms beyond a threshold? Should the model ever override `is_signature_blocker=True` set by Agents 5/6?

2. **Legal review trigger:** Which clause categories always require `requires_legal_review=True`, regardless of the model's analysis? (e.g., governing law, dispute resolution, IP ownership)

3. **LRS structure:** What structure does Sandelin prefer for the Legal Review Summary? Specifically:
   - Is the proposed Executive Summary → Clause-by-Clause → Recommended Actions ordering correct?
   - What level of detail is needed in the counter-proposal section — just the language, or also the reasoning?
   - Should the LRS include a plain-English risk rating (High/Medium/Low)?

4. **Counterparty profile:** Should the `counterparty_profile_ref` slug link to an internal Antora record (counterparty database), or is it sufficient as a human-readable identifier in the LRS?

5. **IP boundary:** Are the clause-level negotiation positions in the playbook considered confidential work product? If so, they must not be included in prompts that hit external APIs without data processing agreements. This affects the design of `AnalyzeClauseFn` — the playbook text goes to Anthropic's API.

6. **Confidentiality:** Are counterparty contract texts subject to any NDA or confidentiality agreement that would restrict sending them to Anthropic's API? If yes, need to review Anthropic's data privacy terms and/or use Anthropic API with zero-data-retention agreement before Phase 2a.

7. **Revision rounds:** How many negotiation rounds are typical before escalation or abandonment? This sets the `max_retry_attempts` and SLA config values.

---

## 10. Open Questions / Unresolved Items

**Finding F — `original_text` plumbing (resolved in Phase 2-pre):**
See Section 8, Phase 2-pre. Resolution: Option A (Layer B change to `ClauseRecommendation`). Must land before Phase 2a.

**`EVENT_NEGOTIATION_FAILED` emission (resolved in Phase 2-pre):**
SM's `_handle_platform_passthrough` will emit `EVENT_NEGOTIATION_FAILED` on `EVENT_RETRY_EXHAUSTED`. Layer C is responsible only for delivering the notification, not for emitting platform lifecycle events. Must land before Phase 2a.

**StorageAdapter path strategy for Drive:**
Layer B's path format includes slashes (`/`). Drive has no native folder hierarchy for programmatic file paths. Decision needed: flatten all paths to a single folder with encoded filenames, or create real Drive subfolders. Flattening is simpler for Phase 2; folder tree is more navigable for Phase 3+.

**Daemon vs. cron:**
The harness runs as a one-shot process. Production Agent 1 needs to poll on a schedule. Options: (a) deploy as a long-running daemon with `time.sleep(poll_interval_seconds)` loop, or (b) invoke via cron (simpler for Phase 2). Cron recommended for Phase 2; daemon for Phase 3+ when SLA monitoring needs continuous `scan_sla_violations()` sweeps.

**Tenant provisioning:**
Phase 2 is single-tenant (`tenant_id="antora"`). `TenantContext` is constructed with a hardcoded tenant ID. If Phase 3 adds a second operator for the peer pilot, the provisioning mechanism (mapping a Gmail sender to a tenant ID) needs to be designed. Not a blocker for Phase 2.

**LRS output storage:**
The harness writes `lrs_v1.md` to a local output directory. Layer C must write the LRS to Drive. The Drive folder for LRS documents should be separate from the raw document storage folder. Configured in `ExtensionsConfig.lrs_output_folder`.

**Agent 7 LRS filename convention:**
Layer B emits `lrs_path` in the `EVENT_LRS_READY` payload. The path format is not currently specified by Layer B — it's whatever the renderer sets. Layer C should establish a convention: `lrs_{negotiation_id}_round_{N}_{timestamp}.md`.

**Multi-round support:**
`round_number` is threaded through Agents 5, 6, and 7. But the `NegotiationRow` schema does not currently track `round_number` as a column — it's derived from the event payload chain. For Phase 2 (single round per negotiation), this is fine. For Phase 3+ (multi-round), the ledger should persist `current_round_number` on `NegotiationRow`.

---

## 11. Out of Scope (Deferred)

The following are explicitly not part of Layer C Phase 2 or Phase 2a-post:

- **Real-time UI / dashboard** — Portfolio Aggregator (Agent 9) provides data; a read-only dashboard can be built in Phase 3 against that API
- **Workflow #2** (RFQ analysis, supplier risk) — infrastructure is forward-compatible; second workflow plugs into same SM/Orchestrator/Portfolio stack
- **Per-user preferences** — Phase 4 peer pilot concern
- **Cloud database** — Phase 2 uses SQLite ledger; migration to Cloud SQL is a Phase 3 concern
- **End-to-end encryption of attachments** — stored as `.bin` in Drive; Drive's own encryption applies. Enhanced encryption is a Phase 3+ security hardening item.
- **Metrics / observability** — Audit log provides the event trail; a Grafana or Datadog integration is Phase 3+
- **Webhook receiver** (replacing Gmail polling) — Some counterparties may support webhook-based document delivery; this is a Phase 4 integration
- **Authoring guides for deployments beyond Antora** — Phase 2a-post produces the guides; applying them to a second deployment is Phase 3+

---

## Recommended Next Steps (in order)

1. **Phase 2-pre — Finding F + EVENT_NEGOTIATION_FAILED** (Layer B changes): Both are small, backward-compatible. Add tests; run discipline check; commit. These unlock Phase 2a.

2. **Answer Sandelin's questions** (Section 9): IP/confidentiality questions (5 and 6) are hard blockers before any contract text goes to Anthropic's API. Schedule a 30-minute call.

3. **Draft the playbook** (Section 2a): Write Antora's standard positions as YAML files in `layer_c_antora/playbook/`. This is the structured data input to the analysis prompt templates.

4. **Draft the initial skills** (Section 2b): Write the four SKILL.md files in `layer_c_antora/skills/`. Sandelin's input on liability and payment term posture is the primary input here.

5. **Phase 2a — Anthropic SDK + Layer B loaders** (Agents 5, 6, 7): Build `acp/layer_b/loaders/` (steps 0a–0c), then wire the three Layer C LLM callables. Run the harness with real LLM output. Verify LRS structure satisfies Findings G, H, I.

6. **Phase 2b — Drive StorageAdapter**: Create Drive folders; implement adapter; run harness.

7. **Phase 2c — Gmail InboxAdapter**: Configure Gmail label; implement adapter and Haiku-backed classifier; test with a planted email.

8. **Phase 2d — End-to-end live run**: One real negotiation through the full pipeline. Have Sandelin review the output LRS.

9. **Phase 2a-post — Authoring guides**: Extract what worked into `docs/authoring/`. Three guides; written against real Antora content that's been validated end-to-end.

10. **Harden and iterate**: Address gaps surfaced by the live run and guide-writing. Adjust SLA thresholds, playbook content, and LRS structure based on Sandelin's feedback.
