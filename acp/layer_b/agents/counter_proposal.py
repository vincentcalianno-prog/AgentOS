"""Agent 6: Counter-Proposal Drafting.

Per Architecture Spec v2.4 Section 5.6:
"For each clause where Agent 5 recommended 'negotiate' or 'reject', draft
counter-proposal language using the configured playbook and LLM. Persist
the structured result to the negotiation's storage folder and emit
EVENT_COUNTER_PROPOSALS_READY."

Triggered by EVENT_ANALYSIS_COMPLETE from State Manager.
LLM-backed (Sonnet-tier) — draft_counter_proposal is injected so tests
use deterministic stubs.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

from acp.layer_b.core.adapters.audit_adapter import AuditEvent, AuditLogAdapter
from acp.layer_b.core.adapters.storage_adapter import StorageAdapter
from acp.layer_b.core.types import (
    EVENT_ANALYSIS_COMPLETE,
    EVENT_COUNTER_PROPOSALS_READY,
    StateEvent,
    TenantContext,
)

# Recommendations that trigger drafting. Accept needs no counter; escalate goes to legal.
_DRAFTABLE_RECOMMENDATIONS = frozenset({"negotiate", "reject"})

# Type alias: injectable LLM call.
# (clause_reference, recommendation, reasoning_from_analysis, original_text,
#  counterparty_text, playbook_context, restore_strategy) → CounterProposalDraft
# In production: Sonnet-tier LLM in layer_c_antora. In tests: deterministic stub.
DraftCounterProposalFn = Callable[[str, str, str, str, str, str, str], "CounterProposalDraft"]

EventHandler = Callable[[StateEvent], None]

PROPOSALS_FILENAME = "counter_proposals.json"


@dataclass(frozen=True)
class CounterProposalDraft:
    """Drafted counter-proposal for a single clause."""
    clause_reference: str
    based_on_recommendation: str     # "negotiate" | "reject"
    original_text: str               # text from outbound version
    counterparty_text: str           # text from counterparty version
    counter_text: str                # drafted counter-proposal language; "" on failure
    reasoning: str                   # why this counter was drafted (or failure message)
    tone: str                        # "firm" | "collaborative" | "neutral"
    playbook_reference: Optional[str]
    requires_legal_review: bool


def _null_drafter(
    clause_reference: str,
    recommendation: str,
    reasoning_from_analysis: str,
    original_text: str,
    counterparty_text: str,
    playbook_context: str,
    restore_strategy: str = "redraft",
) -> CounterProposalDraft:
    """Default stub: returns empty draft. Swap in LLM-backed impl in production."""
    return CounterProposalDraft(
        clause_reference=clause_reference,
        based_on_recommendation=recommendation,
        original_text=original_text,
        counterparty_text=counterparty_text,
        counter_text="",
        reasoning="No drafter configured.",
        tone="neutral",
        playbook_reference=None,
        requires_legal_review=False,
    )


class CounterProposalAgent:
    """Reads redline_analysis.json, drafts counter-proposal text for each
    negotiate/reject clause via injected LLM call, persists
    counter_proposals.json, and emits EVENT_COUNTER_PROPOSALS_READY.

    Stateless across calls. Each process_event() call is self-contained.
    """

    AGENT_NAME = "counter_proposal_agent"

    def __init__(
        self,
        storage: StorageAdapter,
        audit: AuditLogAdapter,
        config: dict,
        draft_counter_proposal: DraftCounterProposalFn = _null_drafter,
    ):
        """
        Args:
            storage: Provider-neutral storage adapter. Analysis JSON is read
                and proposals JSON is written here.
            audit: Append-only audit log.
            config: Agent configuration dict. Recognised keys:
                - playbook_context (str): deployment-provided playbook text
                  passed to the LLM call. Defaults to empty string. Set in
                  Layer C.
            draft_counter_proposal: Injectable LLM callable. Defaults to a
                stub that returns empty drafts. Swap in a Sonnet-tier
                implementation in layer_c_antora.
        """
        self._storage = storage
        self._audit = audit
        self._playbook_context: str = config.get("playbook_context", "")
        self._draft_counter_proposal = draft_counter_proposal
        self._subscribers: list[EventHandler] = []

    def subscribe(self, handler: EventHandler) -> None:
        self._subscribers.append(handler)

    def process_event(self, context: TenantContext, event: StateEvent) -> None:
        """Process an analysis_complete event.

        Loads redline_analysis.json, drafts counter-proposals for all
        negotiate/reject clauses, persists counter_proposals.json alongside
        the analysis, and emits EVENT_COUNTER_PROPOSALS_READY.

        Non-analysis-complete events are silently ignored. Accept and escalate
        clauses are skipped — no counter-proposal is drafted for them.
        LLM failures produce an entry with counter_text="" and are non-fatal.
        """
        if event.event_type != EVENT_ANALYSIS_COMPLETE:
            return

        analysis_path: Optional[str] = event.payload.get("analysis_path")
        round_number: int = event.payload.get("round_number", 0)

        if not analysis_path:
            self._audit_write(
                context, event.negotiation_id,
                "drafting_skipped_missing_analysis_path",
                {"payload_keys": list(event.payload.keys())},
                severity="warning",
            )
            return

        # Step 1: Load analysis JSON
        try:
            raw = self._storage.retrieve(analysis_path)
            analysis_doc = json.loads(raw.decode())
        except Exception as exc:
            self._audit_write(
                context, event.negotiation_id,
                "drafting_analysis_load_failed",
                {"analysis_path": analysis_path, "error": str(exc)},
                severity="error",
            )
            return

        # Step 2: Draft counter-proposals for draftable recommendations
        recommendations = analysis_doc.get("recommendations", [])
        drafts: list[CounterProposalDraft] = []
        for rec in recommendations:
            if rec.get("recommendation") not in _DRAFTABLE_RECOMMENDATIONS:
                continue
            draft = self._draft_one(context, event.negotiation_id, rec)
            drafts.append(draft)

        # Collect signature blocker clause references for downstream LRS enrichment
        signature_blocker_refs = [
            rec["clause_reference"]
            for rec in recommendations
            if rec.get("is_signature_blocker", False)
        ]

        # Step 3: Build summary
        summary = _build_summary(drafts)

        # Step 4: Persist counter_proposals.json
        storage_folder = "/".join(analysis_path.split("/")[:-1])
        proposals_path = f"{storage_folder}/{PROPOSALS_FILENAME}"
        proposals_doc = {
            "negotiation_id": event.negotiation_id,
            "round_number": round_number,
            "analysis_path": analysis_path,
            "drafts": [asdict(d) for d in drafts],
            "summary": summary,
        }
        try:
            self._storage.store(proposals_path, json.dumps(proposals_doc).encode())
        except Exception as exc:
            self._audit_write(
                context, event.negotiation_id,
                "drafting_write_failed",
                {"path": proposals_path, "error": str(exc)},
                severity="error",
            )
            return

        # Step 5: Emit EVENT_COUNTER_PROPOSALS_READY
        self._emit(
            context,
            StateEvent(
                event_type=EVENT_COUNTER_PROPOSALS_READY,
                tenant_id=event.tenant_id,
                negotiation_id=event.negotiation_id,
                workflow_id="contract_redline",
                payload={
                    "proposals_path": proposals_path,
                    "round_number": round_number,
                    "summary": summary,
                    "signature_blockers": signature_blocker_refs,
                },
                emitted_at=datetime.now(timezone.utc),
                emitted_by=self.AGENT_NAME,
            ),
        )

        self._audit_write(
            context, event.negotiation_id,
            "drafting_completed",
            {
                "proposals_path": proposals_path,
                "round_number": round_number,
                "clauses_drafted": len(drafts),
                **summary,
            },
        )

    def _draft_one(
        self,
        context: TenantContext,
        negotiation_id: str,
        rec: dict,
    ) -> CounterProposalDraft:
        """Call draft_counter_proposal for one recommendation. On failure returns a placeholder."""
        clause_ref = rec.get("clause_reference", "")
        recommendation = rec.get("recommendation", "")
        reasoning_from_analysis = rec.get("reasoning", "")
        original_text = rec.get("original_text", "")
        counterparty_text = rec.get("counterparty_text", "")
        antora_response = rec.get("antora_response")  # dict or None after JSON round-trip

        # Auto-select restore_strategy: signature blockers with original text → verbatim restore
        # Finding F — DO NOT REMOVE: this logic must survive antora_response wiring.
        if rec.get("is_signature_blocker", False) and original_text:
            restore_strategy = "verbatim"
        else:
            restore_strategy = "redraft"

        # Playbook path: derive counter text directly from the antora_response block.
        # Skips the LLM drafter when a matched PlaybookEntry supplied structured responses.
        if antora_response is not None:
            draft = self._draft_from_antora_response(
                clause_ref, recommendation, original_text, counterparty_text,
                antora_response, restore_strategy,
            )
            self._audit_write(
                context, negotiation_id,
                "clause_drafted",
                {
                    "clause_reference": clause_ref,
                    "based_on_recommendation": recommendation,
                    "tone": draft.tone,
                    "requires_legal_review": draft.requires_legal_review,
                    "source": "antora_response",
                },
            )
            return draft

        # No playbook entry — fall through to the injected drafter (LLM or stub).
        try:
            draft = self._draft_counter_proposal(
                clause_ref,
                recommendation,
                reasoning_from_analysis,
                original_text,
                counterparty_text,
                self._playbook_context,
                restore_strategy,
            )
            self._audit_write(
                context, negotiation_id,
                "clause_drafted",
                {
                    "clause_reference": clause_ref,
                    "based_on_recommendation": recommendation,
                    "tone": draft.tone,
                    "requires_legal_review": draft.requires_legal_review,
                },
            )
            return draft
        except Exception as exc:
            self._audit_write(
                context, negotiation_id,
                "clause_draft_failed",
                {"clause_reference": clause_ref, "error": str(exc)},
                severity="error",
            )
            return CounterProposalDraft(
                clause_reference=clause_ref,
                based_on_recommendation=recommendation,
                original_text=original_text,
                counterparty_text=counterparty_text,
                counter_text="",
                reasoning=f"Draft failed: {exc}",
                tone="neutral",
                playbook_reference=None,
                requires_legal_review=True,
            )

    def _draft_from_antora_response(
        self,
        clause_ref: str,
        recommendation: str,
        original_text: str,
        counterparty_text: str,
        antora_response: dict,
        restore_strategy: str,
    ) -> CounterProposalDraft:
        """Derive a CounterProposalDraft from the playbook antora_response block.

        Called when rec["antora_response"] is non-None (a PlaybookEntry was matched).
        The injected LLM drafter is not invoked in this path.

        reject + is_signature_blocker (restore_strategy="verbatim"):
            Finding F preserved — verbatim restore of original_text as primary counter.
            Appends rejection_response.counter_proposal as supplementary language.
        reject (non-signature-blocker):
            Uses rejection_response.counter_proposal + rationale.
        negotiate:
            Uses compromise_response.revised_language + conditions.
        """
        rejection = antora_response.get("rejection_response") or {}
        compromise = antora_response.get("compromise_response") or {}

        if recommendation == "reject":
            counter_proposal_text = (rejection.get("counter_proposal") or "").strip()
            rationale = (rejection.get("rationale") or "").strip()
            if restore_strategy == "verbatim" and original_text:
                # Finding F: verbatim restore is the primary counter.
                # Append playbook counter_proposal as supplementary language if present.
                counter_text = original_text
                if counter_proposal_text:
                    counter_text = (
                        f"{original_text}\n\n"
                        f"[Playbook counter-proposal: {counter_proposal_text}]"
                    )
                return CounterProposalDraft(
                    clause_reference=clause_ref,
                    based_on_recommendation=recommendation,
                    original_text=original_text,
                    counterparty_text=counterparty_text,
                    counter_text=counter_text,
                    reasoning=rationale or f"Verbatim restore of {clause_ref}; playbook rejection response applied.",
                    tone="firm",
                    playbook_reference=None,
                    requires_legal_review=True,
                )
            # Non-signature-blocker reject: use rejection_response.counter_proposal.
            if not counter_proposal_text:
                counter_proposal_text = (
                    f"[Playbook: reject — counter_proposal not populated for {clause_ref}]"
                )
            return CounterProposalDraft(
                clause_reference=clause_ref,
                based_on_recommendation=recommendation,
                original_text=original_text,
                counterparty_text=counterparty_text,
                counter_text=counter_proposal_text,
                reasoning=rationale or f"Playbook rejection for {clause_ref}.",
                tone="firm",
                playbook_reference=None,
                requires_legal_review=True,
            )

        if recommendation == "negotiate":
            revised_language = (compromise.get("revised_language") or "").strip()
            conditions = (compromise.get("conditions") or "").strip()
            if revised_language and conditions:
                counter_text = f"{revised_language}\n\n[Conditions: {conditions}]"
            elif revised_language:
                counter_text = revised_language
            else:
                counter_text = (
                    f"[Playbook: negotiate — revised_language not populated for {clause_ref}]"
                )
            return CounterProposalDraft(
                clause_reference=clause_ref,
                based_on_recommendation=recommendation,
                original_text=original_text,
                counterparty_text=counterparty_text,
                counter_text=counter_text,
                reasoning=conditions or f"Playbook compromise for {clause_ref}.",
                tone="collaborative",
                playbook_reference=None,
                requires_legal_review=False,
            )

        # Fallback for any recommendation type not handled above.
        return CounterProposalDraft(
            clause_reference=clause_ref,
            based_on_recommendation=recommendation,
            original_text=original_text,
            counterparty_text=counterparty_text,
            counter_text=(
                f"[Playbook entry present but recommendation '{recommendation}' "
                f"not handled — legal review required.]"
            ),
            reasoning="Unhandled recommendation type with antora_response present.",
            tone="neutral",
            playbook_reference=None,
            requires_legal_review=True,
        )

    def _emit(self, context: TenantContext, event: StateEvent) -> None:
        for handler in self._subscribers:
            try:
                handler(event)
            except Exception as exc:
                self._audit_write(
                    context,
                    negotiation_id=event.negotiation_id,
                    event_type="subscriber_error",
                    payload={
                        "subscriber": getattr(handler, "__qualname__", str(handler)),
                        "error": str(exc),
                        "original_event_type": event.event_type,
                    },
                    severity="error",
                )

    def _audit_write(
        self,
        context: TenantContext,
        negotiation_id: Optional[str],
        event_type: str,
        payload: dict,
        severity: str = "info",
    ) -> None:
        self._audit.record(AuditEvent(
            event_id=str(uuid.uuid4()),
            tenant_id=context.tenant_id,
            negotiation_id=negotiation_id,
            workflow_id="contract_redline",
            agent_name=self.AGENT_NAME,
            event_type=event_type,
            timestamp=datetime.now(timezone.utc),
            payload=payload,
            severity=severity,
        ))


def _build_summary(drafts: list[CounterProposalDraft]) -> dict:
    negotiate_count = sum(1 for d in drafts if d.based_on_recommendation == "negotiate")
    reject_count = sum(1 for d in drafts if d.based_on_recommendation == "reject")
    draft_failed_count = sum(1 for d in drafts if d.counter_text == "")
    legal_review_count = sum(1 for d in drafts if d.requires_legal_review)
    return {
        "total_drafted": len(drafts),
        "negotiate_count": negotiate_count,
        "reject_count": reject_count,
        "draft_failed_count": draft_failed_count,
        "requires_legal_review": legal_review_count,
    }
