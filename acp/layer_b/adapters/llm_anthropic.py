"""Real Anthropic SDK adapters implementing Layer B injectable LLM interfaces.

Drop-in replacements for the stub callables in the dry-run harness.
Deployment-agnostic: no content-specific literals; no Layer C imports.

Factory functions accept configuration from the caller (clause_ref_map, resolver,
and optional pilot_loader / pilot_antora_responses) rather than reading globals,
so they compose cleanly with any harness that has those objects in scope.

Model: ACP_LLM_MODEL env var (default: claude-sonnet-4-6).
API key: ANTHROPIC_API_KEY env var (standard Anthropic SDK default).
Auth errors or unknown model names raise RuntimeError immediately — no silent
fallback to stub behaviour.

Interfaces implemented:
    make_real_analyze_clause()       → AnalyzeClauseFn   (Agent 5)
    make_real_draft_counter_proposal() → DraftCounterProposalFn (Agent 6, fallback only)
    make_real_render_lrs()           → RenderLRSFn       (Agent 7)
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

_DEFAULT_MODEL = "claude-sonnet-4-6"

# Token limits — tunable per call type.
# Increase _MAX_TOKENS_LRS if the LRS document truncates (stop_reason == "max_tokens").
_MAX_TOKENS_ANALYZE = 1024
_MAX_TOKENS_DRAFT = 1024
_MAX_TOKENS_LRS = 8192


# ---------------------------------------------------------------------------
# SDK bootstrap (lazy so tests that import this module don't require the SDK)
# ---------------------------------------------------------------------------

def _get_client():
    """Return an initialised Anthropic client; raise RuntimeError on failure."""
    try:
        import anthropic  # type: ignore[import]
    except ImportError as exc:
        raise RuntimeError(
            "anthropic package not installed. Run: pip3 install anthropic"
        ) from exc
    try:
        return anthropic.Anthropic()
    except Exception as exc:
        raise RuntimeError(
            f"Failed to initialise Anthropic client: {exc}\n"
            "Ensure ANTHROPIC_API_KEY is set."
        ) from exc


def _get_model() -> str:
    return os.environ.get("ACP_LLM_MODEL", _DEFAULT_MODEL)


def _call_llm(client: Any, system: str, user: str, max_tokens: int = 1024) -> tuple[str, str]:
    """Single non-streaming call. Returns (text, stop_reason).

    stop_reason is the Anthropic API stop_reason string (e.g. "end_turn", "max_tokens").
    Callers that care about completeness should check stop_reason == "max_tokens".
    """
    import anthropic  # type: ignore[import]
    model = _get_model()
    try:
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
    except anthropic.AuthenticationError as exc:
        raise RuntimeError(f"Anthropic API authentication failed: {exc}") from exc
    except anthropic.NotFoundError as exc:
        raise RuntimeError(
            f"Model '{model}' not found. "
            f"Set ACP_LLM_MODEL to a valid model ID: {exc}"
        ) from exc
    return response.content[0].text, response.stop_reason


def _parse_json_response(text: str) -> dict:
    """Parse LLM output as JSON, stripping markdown fences if present."""
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        end = len(lines) - 1 if lines[-1].strip().startswith("```") else len(lines)
        stripped = "\n".join(lines[1:end]).strip()
    return json.loads(stripped)


# ---------------------------------------------------------------------------
# Agent 5: analyze_clause
# ---------------------------------------------------------------------------

_ANALYZE_SYSTEM = """\
You are a contract-clause analysis engine for an energy procurement platform.
Your role is to analyse a proposed change to a contract clause and produce a
structured recommendation for the negotiating operator.

Respond with a single valid JSON object — no preamble, no trailing explanation.

Required fields:
{
  "recommendation": "accept" | "reject" | "negotiate" | "escalate",
  "reasoning": "<2-4 sentences explaining the recommendation and its commercial/risk basis>",
  "confidence": "high" | "medium" | "low"
}

Decision rules:
- "accept"   : counterparty change is acceptable without modification
- "reject"   : change is unacceptable; operator must restore the original position
- "negotiate": change is partially acceptable; modified language could work
- "escalate" : insufficient context to decide; route to legal review
- If negotiability tier is "signature_blocker" you MUST output recommendation "reject"
- If negotiability tier is "boilerplate" and the change is cosmetic style-only → "accept"
- confidence "high" when the playbook position is clear; "medium" with some ambiguity;\
 "low" when speculative
- Focus reasoning on commercial risk and impact, not process; be specific about what changed"""


def _build_analyze_prompt(
    clause_reference: str,
    change_type: str,
    original_text: str,
    counterparty_text: str,
    negotiability: str,
    guidance: str,
    reject_thresholds: list[dict],
    accept_modifications: list[dict],
) -> str:
    parts = [
        "CLAUSE ANALYSIS REQUEST",
        "",
        f"Clause reference : {clause_reference}",
        f"Change type      : {change_type}",
        "",
        "--- OPERATOR VERSION (original) ---",
        original_text or "(not provided)",
        "",
        "--- COUNTERPARTY PROPOSED CHANGE ---",
        counterparty_text or "(not provided)",
        "",
        "--- PLAYBOOK POSITION ---",
        f"Negotiability: {negotiability or 'not specified'}",
    ]
    if guidance:
        parts += ["", f"Baseline guidance: {guidance}"]
    if reject_thresholds:
        parts += ["", "Reject if counterparty proposes any of:"]
        for t in reject_thresholds:
            desc = t.get("description", "")
            rat = t.get("rationale", "")
            parts.append(f"  • {desc}" + (f" — {rat}" if rat else ""))
    if accept_modifications:
        parts += ["", "These modifications may be negotiated:"]
        for m in accept_modifications:
            desc = m.get("description", "")
            rat = m.get("rationale", "")
            parts.append(f"  • {desc}" + (f" — {rat}" if rat else ""))
    return "\n".join(parts)


def make_real_analyze_clause(
    clause_ref_map: dict,
    resolver: Any,
    pilot_loader: Any = None,
    pilot_antora_responses: Optional[dict] = None,
):
    """Return an AnalyzeClauseFn backed by the Anthropic SDK.

    Mirrors the harness stub structure:
    1. PlaybookLoader lookup — real YAML entries; LLM supplies reasoning
    2. PilotEntryLoader fallback (if pilot_loader is provided)
    3. Agent-reasoned — full LLM analysis; playbook_grounded=False

    For signature_blocker entries the recommendation is forced to "reject"
    regardless of the LLM's output; the LLM only supplies reasoning.
    """
    from acp.layer_b.agents.redline_analysis import ClauseRecommendation

    client = _get_client()  # raises on auth failure — desired behaviour

    def real_analyze_clause(
        clause_reference: str,
        change_type: str,
        original_text: str,
        counterparty_text: str,
        playbook_context: str,
        round_number: int = 0,
    ) -> ClauseRecommendation:

        # --- 1. PlaybookLoader lookup ---
        playbook_entry = clause_ref_map.get(clause_reference)
        if playbook_entry is not None:
            resolved = resolver.resolve(playbook_entry, [])
            entry = resolved.resolved_entry
            is_signature_blocker = entry.negotiability == "signature_blocker"

            user_prompt = _build_analyze_prompt(
                clause_reference=clause_reference,
                change_type=change_type,
                original_text=original_text,
                counterparty_text=counterparty_text,
                negotiability=entry.negotiability,
                guidance=(
                    entry.defend_baseline.guidance
                    if entry.defend_baseline else ""
                ),
                reject_thresholds=[
                    {"description": t.description, "rationale": t.rationale}
                    for t in (entry.reject_thresholds or [])
                ],
                accept_modifications=[
                    {"description": m.description, "rationale": m.rationale}
                    for m in (entry.accept_modifications or [])
                ],
            )
            raw, _stop = _call_llm(client, _ANALYZE_SYSTEM, user_prompt, max_tokens=_MAX_TOKENS_ANALYZE)
            try:
                parsed = _parse_json_response(raw)
            except (json.JSONDecodeError, KeyError, IndexError):
                parsed = {
                    "recommendation": "reject" if is_signature_blocker else "escalate",
                    "reasoning": raw[:500],
                    "confidence": "low",
                }

            recommendation = parsed.get("recommendation", "negotiate")
            if is_signature_blocker:
                recommendation = "reject"

            return ClauseRecommendation(
                clause_reference=clause_reference,
                recommendation=recommendation,
                reasoning=parsed.get("reasoning", ""),
                playbook_reference=entry.id,
                confidence=parsed.get("confidence", "medium"),
                requires_legal_review=(
                    is_signature_blocker or recommendation in {"reject", "escalate"}
                ),
                is_signature_blocker=is_signature_blocker,
                playbook_grounded=True,
                evidence_source=f"{entry.id} | {entry.evidence_tier}",
                antora_response=entry.antora_response,
            )

        # --- 2. PilotEntryLoader fallback ---
        if pilot_loader is not None:
            pilot_ref = pilot_loader.lookup(clause_reference)
            if pilot_ref is not None:
                is_signature_blocker = (
                    pilot_ref.negotiability == "signature_blocker"
                )
                user_prompt = _build_analyze_prompt(
                    clause_reference=clause_reference,
                    change_type=change_type,
                    original_text=original_text,
                    counterparty_text=counterparty_text,
                    negotiability=pilot_ref.negotiability or "",
                    guidance=getattr(pilot_ref, "guidance", ""),
                    reject_thresholds=[],
                    accept_modifications=[],
                )
                raw, _stop = _call_llm(client, _ANALYZE_SYSTEM, user_prompt, max_tokens=_MAX_TOKENS_ANALYZE)
                try:
                    parsed = _parse_json_response(raw)
                except (json.JSONDecodeError, KeyError, IndexError):
                    parsed = {
                        "recommendation": "reject" if is_signature_blocker else "escalate",
                        "reasoning": raw[:500],
                        "confidence": "low",
                    }

                recommendation = parsed.get("recommendation", "escalate")
                if is_signature_blocker:
                    recommendation = "reject"

                return ClauseRecommendation(
                    clause_reference=clause_reference,
                    recommendation=recommendation,
                    reasoning=parsed.get("reasoning", ""),
                    playbook_reference=pilot_ref.entry_id,
                    confidence=parsed.get("confidence", "medium"),
                    requires_legal_review=recommendation in {"reject", "escalate"},
                    is_signature_blocker=is_signature_blocker,
                    playbook_grounded=True,
                    evidence_source=f"{pilot_ref.entry_id} | {pilot_ref.evidence_tier}",
                    antora_response=(
                        (pilot_antora_responses or {}).get(clause_reference)
                    ),
                )

        # --- 3. Agent-reasoned (no playbook entry) ---
        user_prompt = _build_analyze_prompt(
            clause_reference=clause_reference,
            change_type=change_type,
            original_text=original_text,
            counterparty_text=counterparty_text,
            negotiability="",
            guidance="",
            reject_thresholds=[],
            accept_modifications=[],
        )
        raw, _stop = _call_llm(client, _ANALYZE_SYSTEM, user_prompt, max_tokens=_MAX_TOKENS_ANALYZE)
        try:
            parsed = _parse_json_response(raw)
        except (json.JSONDecodeError, KeyError, IndexError):
            parsed = {
                "recommendation": "escalate",
                "reasoning": raw[:500],
                "confidence": "low",
            }

        recommendation = parsed.get("recommendation", "escalate")
        return ClauseRecommendation(
            clause_reference=clause_reference,
            recommendation=recommendation,
            reasoning=parsed.get("reasoning", ""),
            playbook_reference=None,
            confidence=parsed.get("confidence", "low"),
            requires_legal_review=True,
            is_signature_blocker=False,
            playbook_grounded=False,
            evidence_source=None,
        )

    return real_analyze_clause


# ---------------------------------------------------------------------------
# Agent 6: draft_counter_proposal (fallback — only called when antora_response
# is None, i.e. no playbook entry matched)
# ---------------------------------------------------------------------------

_DRAFT_SYSTEM = """\
You are a contract negotiation drafting engine for an energy procurement platform.
Draft counter-proposal language responding to a counterparty's proposed clause change.

Respond with a single valid JSON object — no preamble, no trailing explanation.

Required fields:
{
  "counter_text": "<complete, ready-to-use contract clause text>",
  "reasoning": "<1-2 sentences explaining the counter>",
  "tone": "firm" | "collaborative" | "neutral"
}

Rules:
- counter_text must be complete, standalone contract language — no [PLACEHOLDER] or\
 incomplete sentences
- For "reject" recommendations: restore the original position firmly
- For "negotiate" recommendations: propose a workable compromise
- tone "firm" for rejections, "collaborative" for negotiations, "neutral" when unclear
- Do not include surrounding section headers or clause numbers in counter_text"""


def make_real_draft_counter_proposal():
    """Return a DraftCounterProposalFn backed by the Anthropic SDK.

    Note: for playbook-matched clauses this function is not invoked — Agent 6
    uses CounterProposalAgent._draft_from_antora_response instead. This callable
    handles the agent-reasoned fallback path (no PlaybookEntry, antora_response=None).
    """
    from acp.layer_b.agents.counter_proposal import CounterProposalDraft

    client = _get_client()

    def real_draft_counter_proposal(
        clause_reference: str,
        recommendation: str,
        reasoning_from_analysis: str,
        original_text: str,
        counterparty_text: str,
        playbook_context: str,
        restore_strategy: str = "redraft",
    ) -> CounterProposalDraft:
        # Verbatim-restore path (Finding F) — same as stub, no LLM needed
        if restore_strategy == "verbatim" and original_text:
            return CounterProposalDraft(
                clause_reference=clause_reference,
                based_on_recommendation=recommendation,
                original_text=original_text,
                counterparty_text=counterparty_text,
                counter_text=original_text,
                reasoning=(
                    f"Verbatim restore of clause {clause_reference} "
                    f"per restore_strategy=verbatim."
                ),
                tone="firm",
                playbook_reference=None,
                requires_legal_review=True,
            )

        user_prompt = "\n".join([
            "COUNTER-PROPOSAL DRAFT REQUEST",
            "",
            f"Clause reference   : {clause_reference}",
            f"Recommendation     : {recommendation}",
            f"Analysis reasoning : {reasoning_from_analysis}",
            "",
            "--- OPERATOR VERSION (original) ---",
            original_text or "(not provided)",
            "",
            "--- COUNTERPARTY PROPOSED CHANGE ---",
            counterparty_text or "(not provided)",
        ])

        raw, _stop = _call_llm(client, _DRAFT_SYSTEM, user_prompt, max_tokens=_MAX_TOKENS_DRAFT)
        try:
            parsed = _parse_json_response(raw)
        except (json.JSONDecodeError, KeyError, IndexError):
            return CounterProposalDraft(
                clause_reference=clause_reference,
                based_on_recommendation=recommendation,
                original_text=original_text,
                counterparty_text=counterparty_text,
                counter_text="[LLM parse error — legal review required]",
                reasoning=f"Parse error: {raw[:200]}",
                tone="neutral",
                playbook_reference=None,
                requires_legal_review=True,
            )

        return CounterProposalDraft(
            clause_reference=clause_reference,
            based_on_recommendation=recommendation,
            original_text=original_text,
            counterparty_text=counterparty_text,
            counter_text=parsed.get("counter_text", "[empty — legal review required]"),
            reasoning=parsed.get("reasoning", ""),
            tone=parsed.get("tone", "neutral"),
            playbook_reference=None,
            requires_legal_review=recommendation in {"reject", "escalate"},
        )

    return real_draft_counter_proposal


# ---------------------------------------------------------------------------
# Agent 7: render_lrs
# ---------------------------------------------------------------------------

_LRS_SYSTEM = """\
You are a legal review summary generator for a contract negotiation platform.
Produce a professional Markdown document for review by legal counsel.

Structure:
1. **Executive Summary** — 2-3 action sentences; state urgency level and key asks
2. **Signature Blockers** — bullet list of clauses that must resolve before signing;\
 omit section if none
3. **Clause-by-Clause Analysis** — for each changed clause: what changed,\
 recommendation, and reasoning
4. **Counter-Proposal Drafts** — complete proposed language for each clause requiring\
 a counter
5. **Risk Notes & Next Steps** — key risks and recommended next actions

Tone: professional and precise; suitable for attorney review.
Do not invent facts not present in the input. Use standard Markdown."""


def make_real_render_lrs():
    """Return a RenderLRSFn backed by the Anthropic SDK."""
    from acp.layer_b.agents.lrs_generator import LRSInput, LRSOutput

    client = _get_client()

    def real_render_lrs(lrs_input: LRSInput) -> LRSOutput:
        entries = lrs_input.diff.get("entries", [])
        recs = lrs_input.analysis.get("recommendations", [])
        drafts = lrs_input.counter_proposals.get("drafts", [])

        rec_by_ref = {r["clause_reference"]: r for r in recs}
        draft_by_ref = {d["clause_reference"]: d for d in drafts}
        changed = [e for e in entries if e.get("change_type") != "unchanged"]

        user_lines = [
            "LEGAL REVIEW SUMMARY REQUEST",
            "",
            f"Negotiation ID  : {lrs_input.negotiation_id}",
            f"Contract type   : {lrs_input.contract_type}",
            f"Counterparty    : {lrs_input.counterparty_name}",
            f"Round           : {lrs_input.round_number}",
        ]
        if lrs_input.signature_blockers:
            user_lines.append(
                f"Signature blockers: {', '.join(lrs_input.signature_blockers)}"
            )
        if lrs_input.risk_summary:
            user_lines.append(f"Risk summary: {lrs_input.risk_summary}")

        user_lines += ["", "--- CHANGED CLAUSES ---"]
        for e in changed:
            ref = e["clause_reference"]
            ct = e.get("change_type", "?")
            user_lines.append(f"\nClause {ref} [{ct}]:")
            user_lines.append(
                f"  Original    : {(e.get('original_text') or '')[:300]}"
            )
            user_lines.append(
                f"  Counterparty: {(e.get('counterparty_text') or '')[:300]}"
            )
            rec = rec_by_ref.get(ref, {})
            if rec:
                blocker = " ⚠ SIGNATURE BLOCKER" if rec.get("is_signature_blocker") else ""
                user_lines.append(
                    f"  Recommendation: {rec.get('recommendation')} "
                    f"({rec.get('confidence')} confidence){blocker}"
                )
                user_lines.append(f"  Reasoning: {rec.get('reasoning', '')}")
            draft = draft_by_ref.get(ref, {})
            if draft:
                user_lines.append(
                    f"  Counter-proposal: {(draft.get('counter_text') or '')[:400]}"
                )

        raw, stop_reason = _call_llm(
            client, _LRS_SYSTEM, "\n".join(user_lines), max_tokens=_MAX_TOKENS_LRS
        )
        if stop_reason == "max_tokens":
            raise RuntimeError(
                f"LRS document truncated (stop_reason=max_tokens, limit={_MAX_TOKENS_LRS}). "
                "Raise _MAX_TOKENS_LRS in llm_anthropic.py or render the LRS in sections."
            )

        return LRSOutput(
            document_bytes=raw.encode(),
            document_format="md",
            metadata={
                "renderer": "real-llm",
                "model": _get_model(),
                "clause_count": len(changed),
                "stop_reason": stop_reason,
                "truncated": stop_reason == "max_tokens",
            },
        )

    return real_render_lrs
