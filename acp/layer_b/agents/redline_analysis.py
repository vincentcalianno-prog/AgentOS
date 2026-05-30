"""Agent 5: Redline Analysis.

Per Architecture Spec v2.4 Section 5.5:
"For each changed clause in the structural diff, invoke the configured
playbook and LLM to produce a recommendation. Persist the structured
result to the negotiation's storage folder and emit EVENT_ANALYSIS_COMPLETE."

Triggered by EVENT_DIFF_COMPLETE from State Manager.
LLM-backed — analyze_clause is injected so tests use deterministic stubs.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Optional

from acp.layer_b.core.adapters.audit_adapter import AuditEvent, AuditLogAdapter
from acp.layer_b.core.adapters.storage_adapter import StorageAdapter
from acp.layer_b.core.types import (
    EVENT_ANALYSIS_COMPLETE,
    EVENT_DIFF_COMPLETE,
    StateEvent,
    TenantContext,
)

# Type alias: injectable LLM call.
# (clause_reference, change_type, original_text, counterparty_text, playbook_context,
#  round_number) → ClauseRecommendation
# In production: backed by Anthropic SDK in layer_c_antora. In tests: deterministic lambda.
AnalyzeClauseFn = Callable[[str, str, str, str, str, int], "ClauseRecommendation"]

EventHandler = Callable[[StateEvent], None]

ANALYSIS_FILENAME = "redline_analysis.json"


@dataclass(frozen=True)
class RejectionResponse:
    """Antora's rejection state: rationale for rejecting + concrete counter-language."""
    rationale: str = ""
    counter_proposal: str = ""


@dataclass(frozen=True)
class CompromiseResponse:
    """Antora's compromise state: conditions for partial acceptance + revised language."""
    conditions: str = ""
    revised_language: str = ""


@dataclass(frozen=True)
class AcceptanceResponse:
    """Antora's acceptance state: rationale for why the position already protects Antora."""
    rationale: str = ""


@dataclass(frozen=True)
class AntoraResponse:
    """Three-state structured response block for a clause redline.

    Production analyzers MUST populate all three states for each clause:
      rejection_response  — rationale for rejecting + counter-language restoring Antora's position
      compromise_response — conditions under which partial acceptance is allowed + revised language
      acceptance_response — rationale for when the counterparty position already satisfies Antora

    Do NOT hardcode Antora-specific positions here. All content is injected via playbook_context
    at runtime in layer_c_antora. This dataclass defines the output contract shape only.
    """
    rejection_response: RejectionResponse = field(default_factory=RejectionResponse)
    compromise_response: CompromiseResponse = field(default_factory=CompromiseResponse)
    acceptance_response: AcceptanceResponse = field(default_factory=AcceptanceResponse)


class LrsConfidenceTier(Enum):
    PLAYBOOK_VERIFIED    = "playbook_verified"
    # Playbook hit + evidence_tier = verified (Tier 1 closed agreement)

    PLAYBOOK_PROVISIONAL = "playbook_provisional"
    # Playbook hit + evidence_tier = provisional (Tier 2 Jeff/Sandelin feedback)

    AGENT_REASONED       = "agent_reasoned"
    # No playbook entry; LLM-reasoned from general contract principles


@dataclass(frozen=True)
class ClauseRecommendation:
    """LLM recommendation for a single changed clause."""
    clause_reference: str
    recommendation: str          # "accept" | "reject" | "negotiate" | "escalate"
    reasoning: str
    playbook_reference: Optional[str]
    confidence: str              # "high" | "medium" | "low"
    requires_legal_review: bool
    is_signature_blocker: bool = False  # True if this clause must be resolved before signature
    playbook_grounded: bool = True
    # True  → Agent 5 matched a PlaybookEntry; counter sourced from antora_response
    # False → No PlaybookEntry exists for this clause; response is LLM-reasoned
    evidence_source: Optional[str] = None
    # Populated when playbook_grounded=True.
    # Format: "<entry_id> | <evidence_tier> | <source_description>"
    # Examples:
    #   "mepa.lol.direct_damages | verified | MCM PO T&Cs, May 6"
    #   "mepa.warranty.period | provisional | Jeff/Sandelin feedback"
    # Stays None when playbook_grounded=False (no entry to cite)
    original_text: str = ""             # Carried from DiffEntry; enables verbatim restore in Agent 6
    antora_response: Optional[AntoraResponse] = None  # populated by production analyzers; None in stubs


def resolve_confidence_tier(rec: ClauseRecommendation) -> LrsConfidenceTier:
    """Derive the LRS confidence tier from a ClauseRecommendation.

    Pure function — no side effects, no I/O. Called by Agent 7 during LRS rendering.
    """
    if not rec.playbook_grounded:
        return LrsConfidenceTier.AGENT_REASONED
    if rec.evidence_source and "verified" in rec.evidence_source:
        return LrsConfidenceTier.PLAYBOOK_VERIFIED
    return LrsConfidenceTier.PLAYBOOK_PROVISIONAL


def _null_analyzer(
    clause_reference: str,
    change_type: str,
    original_text: str,
    counterparty_text: str,
    playbook_context: str,
    round_number: int = 0,
) -> ClauseRecommendation:
    """Default stub: escalates everything. Swap in LLM-backed impl in production."""
    return ClauseRecommendation(
        clause_reference=clause_reference,
        recommendation="escalate",
        reasoning="No analyzer configured.",
        playbook_reference=None,
        confidence="low",
        requires_legal_review=True,
        playbook_grounded=False,
        evidence_source=None,
    )


class RedlineAnalyzer:
    """Reads structural_diff.json, analyzes each changed clause via injected LLM call,
    persists redline_analysis.json, and emits EVENT_ANALYSIS_COMPLETE.

    Stateless across calls. Each process_event() call is self-contained.
    """

    AGENT_NAME = "redline_analyzer"

    def __init__(
        self,
        storage: StorageAdapter,
        audit: AuditLogAdapter,
        config: dict,
        analyze_clause: AnalyzeClauseFn = _null_analyzer,
    ):
        """
        Args:
            storage: Provider-neutral storage adapter. Diff JSON is read and
                analysis JSON is written here.
            audit: Append-only audit log.
            config: Agent configuration dict. Recognised keys:
                - playbook_context (str): deployment-provided playbook text passed
                  to the LLM call. Defaults to empty string. Set in Layer C.
            analyze_clause: Injectable LLM callable. Defaults to a stub that
                escalates all clauses. Swap in a production-backed implementation
                in layer_c_antora.
        """
        self._storage = storage
        self._audit = audit
        self._playbook_context: str = config.get("playbook_context", "")
        self._analyze_clause = analyze_clause
        self._subscribers: list[EventHandler] = []

    def subscribe(self, handler: EventHandler) -> None:
        self._subscribers.append(handler)

    def process_event(self, context: TenantContext, event: StateEvent) -> None:
        """Process a diff_complete event.

        Loads structural_diff.json, analyzes all non-unchanged clauses, persists
        redline_analysis.json alongside the diff, and emits EVENT_ANALYSIS_COMPLETE.

        Non-diff-complete events are silently ignored.
        """
        if event.event_type != EVENT_DIFF_COMPLETE:
            return

        diff_path: Optional[str] = event.payload.get("diff_path")
        round_number: int = event.payload.get("round_number", 0)

        if not diff_path:
            self._audit_write(
                context, event.negotiation_id,
                "analysis_skipped_missing_diff_path",
                {"payload_keys": list(event.payload.keys())},
                severity="warning",
            )
            return

        # Step 1: Load structural diff
        try:
            raw = self._storage.retrieve(diff_path)
            diff_doc = json.loads(raw.decode())
        except Exception as exc:
            self._audit_write(
                context, event.negotiation_id,
                "analysis_diff_load_failed",
                {"diff_path": diff_path, "error": str(exc)},
                severity="error",
            )
            return

        # Step 2: Analyze each changed clause
        entries = diff_doc.get("entries", [])
        recommendations: list[ClauseRecommendation] = []
        for entry in entries:
            if entry.get("change_type") == "unchanged":
                continue
            rec = self._analyze_entry(context, event.negotiation_id, entry, round_number)
            if rec is not None:
                recommendations.append(rec)

        # Step 3: Build summary counts
        summary = _build_summary(recommendations)

        # Step 4: Persist analysis JSON
        storage_folder = "/".join(diff_path.split("/")[:-1])
        analysis_path = f"{storage_folder}/{ANALYSIS_FILENAME}"
        analysis_doc = {
            "negotiation_id": event.negotiation_id,
            "round_number": round_number,
            "diff_path": diff_path,
            "recommendations": [asdict(r) for r in recommendations],
            "summary": summary,
        }
        try:
            self._storage.store(analysis_path, json.dumps(analysis_doc).encode())
        except Exception as exc:
            self._audit_write(
                context, event.negotiation_id,
                "analysis_write_failed",
                {"path": analysis_path, "error": str(exc)},
                severity="error",
            )
            return

        # Step 5: Emit EVENT_ANALYSIS_COMPLETE
        self._emit(
            context,
            StateEvent(
                event_type=EVENT_ANALYSIS_COMPLETE,
                tenant_id=event.tenant_id,
                negotiation_id=event.negotiation_id,
                workflow_id="contract_redline",
                payload={
                    "analysis_path": analysis_path,
                    "round_number": round_number,
                    "summary": summary,
                },
                emitted_at=datetime.now(timezone.utc),
                emitted_by=self.AGENT_NAME,
            ),
        )

        self._audit_write(
            context, event.negotiation_id,
            "analysis_completed",
            {
                "analysis_path": analysis_path,
                "round_number": round_number,
                "clauses_analysed": len(recommendations),
                **summary,
            },
        )

    def _analyze_entry(
        self,
        context: TenantContext,
        negotiation_id: str,
        entry: dict,
        round_number: int = 0,
    ) -> Optional[ClauseRecommendation]:
        """Call analyze_clause for one diff entry. On failure returns a safe escalation."""
        clause_ref = entry.get("clause_reference", "")
        change_type = entry.get("change_type", "")
        original_text = entry.get("original_text", "")
        counterparty_text = entry.get("counterparty_text", "")
        try:
            rec = self._analyze_clause(
                clause_ref,
                change_type,
                original_text,
                counterparty_text,
                self._playbook_context,
                round_number,
            )
            # Always carry original_text forward from the diff entry; the injected
            # analyzer is not expected to populate it — the diff is the source of truth.
            if original_text:
                rec = replace(rec, original_text=original_text)
            self._audit_write(
                context, negotiation_id,
                "clause_analysed",
                {
                    "clause_reference": clause_ref,
                    "recommendation": rec.recommendation,
                    "confidence": rec.confidence,
                    "requires_legal_review": rec.requires_legal_review,
                },
            )
            return rec
        except Exception as exc:
            self._audit_write(
                context, negotiation_id,
                "clause_analysis_failed",
                {"clause_reference": clause_ref, "error": str(exc)},
                severity="error",
            )
            # Non-fatal: return a safe escalation recommendation
            return ClauseRecommendation(
                clause_reference=clause_ref,
                recommendation="escalate",
                reasoning=f"Analysis failed: {exc}",
                playbook_reference=None,
                confidence="low",
                requires_legal_review=True,
                playbook_grounded=False,
                evidence_source=None,
                original_text=original_text,
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


def _build_summary(recommendations: list[ClauseRecommendation]) -> dict:
    counts: dict[str, int] = {"accept": 0, "reject": 0, "negotiate": 0, "escalate": 0}
    legal_review_count = 0
    for rec in recommendations:
        if rec.recommendation in counts:
            counts[rec.recommendation] += 1
        if rec.requires_legal_review:
            legal_review_count += 1
    return {
        "total_analysed": len(recommendations),
        **counts,
        "requires_legal_review": legal_review_count,
    }
