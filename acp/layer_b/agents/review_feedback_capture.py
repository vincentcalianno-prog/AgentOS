"""Gate 1 / Gate 2 review feedback capture.

Writes RecommendationReview records from human review actions into
PlaybookEntry.recommendation_reviews. This is the wiring that connects
human review decisions to the structured learning record.

Records written here become Tier-2 playbook evidence processed by
Agent 9 (Portfolio Aggregator) in Phase 3.

Pure except for audit log writes and date.today() calls.
Callers are responsible for persisting the returned updated entry.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import date, datetime, timezone
from typing import Optional

from acp.layer_b.core.adapters.audit_adapter import AuditEvent, AuditLogAdapter
from acp.schemas.playbook_schemas import (
    AbstractionStatus,
    PlaybookEntry,
    RecommendationReview,
    ReviewerReaction,
)

_AGENT_NAME = "review_feedback_capture"
_WORKFLOW_ID = "contract_review"


class ReviewFeedbackCapture:
    """Captures structured feedback from Gate 1 (owner) and Gate 2 (legal)
    reviews into RecommendationReview records on the relevant PlaybookEntry.

    This is the wiring that makes human review actions visible to the
    learning loop. Records written here become Tier-2 playbook evidence
    processed by Agent 9 (Portfolio Aggregator) in Phase 3.
    """

    def __init__(self, audit_log: AuditLogAdapter) -> None:
        self._audit = audit_log

    def capture_owner_feedback(
        self,
        entry: PlaybookEntry,
        clause_reference: str,
        reviewer_name: str,
        original_recommendation: str,
        # The disposition Agent 5 proposed: "accept" | "counter" | "reject"
        reaction: ReviewerReaction,
        # ReviewerReaction.ACCEPTED — owner agreed with agent
        # ReviewerReaction.EDITED   — owner changed the disposition or language
        # ReviewerReaction.REJECTED — owner rejected the recommendation entirely
        revised_disposition: Optional[str] = None,
        # Required when reaction=EDITED. The corrected disposition.
        rationale: str = "",
        # Why the owner changed it. Free text. Becomes learning signal.
    ) -> PlaybookEntry:
        """Gate 1: Record owner review feedback on an agent recommendation.

        Returns updated PlaybookEntry with the new RecommendationReview
        appended to recommendation_reviews. Caller is responsible for
        persisting the updated entry.

        Pure except for audit log write and date.today() call.
        """
        review = RecommendationReview(
            date=date.today().isoformat(),
            proposed_counter=original_recommendation,
            reviewer_role=f"owner:{reviewer_name}",
            reaction=reaction,
            revised_language=revised_disposition or "",
            rationale=rationale,
            abstraction_status=AbstractionStatus.PENDING,
            notes=f"Gate 1 owner review · clause: {clause_reference}",
        )
        updated_entry = replace(
            entry,
            recommendation_reviews=[*entry.recommendation_reviews, review],
        )
        self._audit.record(AuditEvent(
            event_id=str(uuid.uuid4()),
            tenant_id="",
            negotiation_id=entry.id or None,
            workflow_id=_WORKFLOW_ID,
            agent_name=_AGENT_NAME,
            event_type="owner_review_feedback_captured",
            timestamp=datetime.now(timezone.utc),
            payload={
                "clause_reference": clause_reference,
                "reviewer": reviewer_name,
                "reaction": reaction.value,
                "had_revision": revised_disposition is not None,
            },
        ))
        return updated_entry

    def capture_legal_feedback(
        self,
        entry: PlaybookEntry,
        clause_reference: str,
        reviewer_name: str,
        # "sandelin" | "jeff" | other
        agent_drafted_language: str,
        # The exact counter-proposal text Agent 6 generated
        reaction: ReviewerReaction,
        revised_language: str = "",
        # Required when reaction=EDITED. What legal changed it to.
        rationale: str = "",
        # Why legal changed it. This is the highest-value learning signal.
    ) -> PlaybookEntry:
        """Gate 2: Record legal review feedback on agent counter-language.

        The revised_language and rationale fields become Tier-2 playbook
        evidence. Accumulated legal edits on the same clause type surface
        as proposed playbook updates via Agent 9 in Phase 3.

        Returns updated PlaybookEntry. Caller persists.
        """
        review = RecommendationReview(
            date=date.today().isoformat(),
            proposed_counter=agent_drafted_language,
            reviewer_role=f"legal:{reviewer_name}",
            reaction=reaction,
            revised_language=revised_language,
            rationale=rationale,
            abstraction_status=AbstractionStatus.PENDING,
            notes=f"Gate 2 legal review · clause: {clause_reference}",
        )
        updated_entry = replace(
            entry,
            recommendation_reviews=[*entry.recommendation_reviews, review],
        )
        self._audit.record(AuditEvent(
            event_id=str(uuid.uuid4()),
            tenant_id="",
            negotiation_id=entry.id or None,
            workflow_id=_WORKFLOW_ID,
            agent_name=_AGENT_NAME,
            event_type="legal_review_feedback_captured",
            timestamp=datetime.now(timezone.utc),
            payload={
                "clause_reference": clause_reference,
                "reviewer": reviewer_name,
                "reaction": reaction.value,
                "had_revision": bool(revised_language),
                "rationale_provided": bool(rationale),
            },
        ))
        return updated_entry
