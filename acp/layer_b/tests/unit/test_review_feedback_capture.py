"""Unit tests: ReviewFeedbackCapture (Gate 1 / Gate 2 learning signals).

Per Implementation Guide Section 7.1: synthetic fixtures only.
    Tenants: alice, bob, carol
    Counterparties: Acme Industrial, Beta Manufacturing, Gamma Components

Tests confirm that:
  - capture_owner_feedback() and capture_legal_feedback() append a correctly
    formed RecommendationReview to the returned PlaybookEntry
  - The original entry is never mutated (replace() immutability contract)
  - Audit events are emitted with the correct event_type and payload fields
  - detect_playbook_update_candidates() surfaces entries with 2+ legal EDITED
    reviews and ignores entries that do not meet the threshold
"""

from __future__ import annotations

import unittest

from acp.layer_b.agents.portfolio_aggregator import PortfolioAggregatorAgent
from acp.layer_b.agents.review_feedback_capture import ReviewFeedbackCapture
from acp.layer_b.core.adapters.in_memory_audit import InMemoryAuditLog
from acp.schemas.playbook_schemas import (
    AbstractionStatus,
    PlaybookEntry,
    RecommendationReview,
    ReviewerReaction,
)


# ------------------------------------------------------------------ #
# Fixtures                                                            #
# ------------------------------------------------------------------ #

def _entry(entry_id: str = "jst-8-lol") -> PlaybookEntry:
    """Minimal PlaybookEntry with no prior recommendation_reviews."""
    return PlaybookEntry(id=entry_id)


def _entry_with_reviews(
    entry_id: str,
    reviews: list[RecommendationReview],
) -> PlaybookEntry:
    return PlaybookEntry(id=entry_id, recommendation_reviews=reviews)


def _legal_edited_review(rationale: str = "") -> RecommendationReview:
    return RecommendationReview(
        reviewer_role="legal:sandelin",
        reaction=ReviewerReaction.EDITED,
        rationale=rationale,
    )


def _make_capture() -> tuple[ReviewFeedbackCapture, InMemoryAuditLog]:
    audit = InMemoryAuditLog()
    return ReviewFeedbackCapture(audit_log=audit), audit


# ------------------------------------------------------------------ #
# Gate 1 — Owner review feedback                                      #
# ------------------------------------------------------------------ #

class TestCaptureOwnerFeedback(unittest.TestCase):

    def test_accepted_reaction_appends_review(self):
        """ACCEPTED: review appended; role prefixed with owner:; status=PENDING."""
        capture, audit = _make_capture()
        entry = _entry()

        result = capture.capture_owner_feedback(
            entry=entry,
            clause_reference="JST-§8.3",
            reviewer_name="vincent",
            original_recommendation="accept",
            reaction=ReviewerReaction.ACCEPTED,
        )

        self.assertEqual(len(result.recommendation_reviews), 1)
        review = result.recommendation_reviews[0]
        self.assertTrue(review.reviewer_role.startswith("owner:"))
        self.assertEqual(review.abstraction_status, AbstractionStatus.PENDING)
        self.assertEqual(review.reaction, ReviewerReaction.ACCEPTED)

    def test_accepted_audit_event_emitted(self):
        """ACCEPTED: single audit event with correct event_type."""
        capture, audit = _make_capture()
        capture.capture_owner_feedback(
            entry=_entry(),
            clause_reference="JST-§8.3",
            reviewer_name="vincent",
            original_recommendation="accept",
            reaction=ReviewerReaction.ACCEPTED,
        )

        events = audit.query()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "owner_review_feedback_captured")
        self.assertEqual(events[0].payload["reaction"], "accepted")
        self.assertFalse(events[0].payload["had_revision"])

    def test_edited_reaction_stores_revised_disposition_and_rationale(self):
        """EDITED: revised_language and rationale written to review record."""
        capture, audit = _make_capture()
        result = capture.capture_owner_feedback(
            entry=_entry(),
            clause_reference="JST-§8.3",
            reviewer_name="vincent",
            original_recommendation="counter",
            reaction=ReviewerReaction.EDITED,
            revised_disposition="reject",
            rationale="Clause shifts unlimited liability to us.",
        )

        review = result.recommendation_reviews[0]
        self.assertEqual(review.revised_language, "reject")
        self.assertEqual(review.rationale, "Clause shifts unlimited liability to us.")

    def test_edited_audit_payload_had_revision_true(self):
        """EDITED: audit payload had_revision=True when revised_disposition provided."""
        capture, audit = _make_capture()
        capture.capture_owner_feedback(
            entry=_entry(),
            clause_reference="JST-§8.3",
            reviewer_name="vincent",
            original_recommendation="counter",
            reaction=ReviewerReaction.EDITED,
            revised_disposition="reject",
        )

        events = audit.query()
        self.assertTrue(events[0].payload["had_revision"])


# ------------------------------------------------------------------ #
# Gate 2 — Legal feedback                                             #
# ------------------------------------------------------------------ #

class TestCaptureLegalFeedback(unittest.TestCase):

    def test_edited_reaction_stores_all_fields(self):
        """EDITED: proposed_counter, revised_language, reviewer_role, audit event."""
        capture, audit = _make_capture()
        drafted = "Counterparty shall indemnify operator for all losses."
        revised = "Counterparty shall indemnify operator for direct losses only."

        result = capture.capture_legal_feedback(
            entry=_entry("jst-8-lol"),
            clause_reference="JST-§8.3",
            reviewer_name="sandelin",
            agent_drafted_language=drafted,
            reaction=ReviewerReaction.EDITED,
            revised_language=revised,
            rationale="Avoid unlimited indemnity exposure.",
        )

        review = result.recommendation_reviews[0]
        self.assertEqual(review.proposed_counter, drafted)
        self.assertEqual(review.revised_language, revised)
        self.assertTrue(review.reviewer_role.startswith("legal:"))
        self.assertEqual(review.reaction, ReviewerReaction.EDITED)

    def test_edited_audit_event(self):
        """EDITED: audit event_type and had_revision payload correct."""
        capture, audit = _make_capture()
        capture.capture_legal_feedback(
            entry=_entry(),
            clause_reference="JST-§8.3",
            reviewer_name="sandelin",
            agent_drafted_language="draft text",
            reaction=ReviewerReaction.EDITED,
            revised_language="revised text",
            rationale="reason",
        )

        events = audit.query()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "legal_review_feedback_captured")
        self.assertTrue(events[0].payload["had_revision"])
        self.assertTrue(events[0].payload["rationale_provided"])

    def test_accepted_reaction_had_revision_false(self):
        """ACCEPTED: audit had_revision=False; review.revised_language=""."""
        capture, audit = _make_capture()
        result = capture.capture_legal_feedback(
            entry=_entry(),
            clause_reference="JST-§8.3",
            reviewer_name="jeff",
            agent_drafted_language="agent draft",
            reaction=ReviewerReaction.ACCEPTED,
        )

        review = result.recommendation_reviews[0]
        self.assertEqual(review.revised_language, "")

        events = audit.query()
        self.assertFalse(events[0].payload["had_revision"])


# ------------------------------------------------------------------ #
# Immutability                                                        #
# ------------------------------------------------------------------ #

class TestImmutability(unittest.TestCase):

    def test_owner_feedback_does_not_mutate_original_entry(self):
        """capture_owner_feedback() returns a new entry; original unchanged."""
        capture, _ = _make_capture()
        original = _entry()
        original_reviews = list(original.recommendation_reviews)

        result = capture.capture_owner_feedback(
            entry=original,
            clause_reference="JST-§8.3",
            reviewer_name="vincent",
            original_recommendation="accept",
            reaction=ReviewerReaction.ACCEPTED,
        )

        self.assertIsNot(result, original)
        self.assertEqual(original.recommendation_reviews, original_reviews)
        self.assertEqual(len(result.recommendation_reviews), 1)

    def test_legal_feedback_does_not_mutate_original_entry(self):
        """capture_legal_feedback() returns a new entry; original unchanged."""
        capture, _ = _make_capture()
        original = _entry()
        original_reviews = list(original.recommendation_reviews)

        result = capture.capture_legal_feedback(
            entry=original,
            clause_reference="JST-§8.3",
            reviewer_name="sandelin",
            agent_drafted_language="draft",
            reaction=ReviewerReaction.EDITED,
            revised_language="revised",
        )

        self.assertIsNot(result, original)
        self.assertEqual(original.recommendation_reviews, original_reviews)
        self.assertEqual(len(result.recommendation_reviews), 1)


# ------------------------------------------------------------------ #
# Agent 9 — detect_playbook_update_candidates stub                   #
# ------------------------------------------------------------------ #

class TestDetectPlaybookUpdateCandidates(unittest.TestCase):

    def _make_agent(self) -> PortfolioAggregatorAgent:
        return PortfolioAggregatorAgent(sources=[], audit=InMemoryAuditLog())

    def test_returns_empty_when_no_entries_have_two_legal_edits(self):
        """No candidates when entries have fewer than 2 legal EDITED reviews."""
        agent = self._make_agent()

        # Zero reviews
        no_reviews = _entry("entry-a")

        # One legal EDITED review (below threshold)
        one_edit = _entry_with_reviews("entry-b", [_legal_edited_review()])

        # Two legal reviews but only one is EDITED
        mixed = _entry_with_reviews("entry-c", [
            _legal_edited_review(),
            RecommendationReview(
                reviewer_role="legal:jeff",
                reaction=ReviewerReaction.ACCEPTED,
            ),
        ])

        # Two EDITED reviews but from owner, not legal
        owner_edits = _entry_with_reviews("entry-d", [
            RecommendationReview(reviewer_role="owner:vincent", reaction=ReviewerReaction.EDITED),
            RecommendationReview(reviewer_role="owner:vincent", reaction=ReviewerReaction.EDITED),
        ])

        result = agent.detect_playbook_update_candidates(
            [no_reviews, one_edit, mixed, owner_edits]
        )
        self.assertEqual(result, [])

    def test_returns_entry_id_when_two_legal_edits_present(self):
        """Entry with 2+ legal EDITED reviews surfaced as candidate."""
        agent = self._make_agent()

        candidate = _entry_with_reviews("jst-8-lol", [
            _legal_edited_review(rationale="Shifts liability."),
            _legal_edited_review(rationale="Unlimited exposure."),
        ])

        result = agent.detect_playbook_update_candidates([candidate])

        self.assertEqual(len(result), 1)
        entry_id, edit_count, sample_rationale = result[0]
        self.assertEqual(entry_id, "jst-8-lol")
        self.assertEqual(edit_count, 2)
        self.assertEqual(sample_rationale, "Shifts liability.")

    def test_returns_multiple_candidates(self):
        """Multiple qualifying entries all returned."""
        agent = self._make_agent()

        alpha = _entry_with_reviews("alpha", [
            _legal_edited_review(), _legal_edited_review(),
        ])
        beta = _entry_with_reviews("beta", [
            _legal_edited_review(), _legal_edited_review(), _legal_edited_review(),
        ])
        gamma = _entry("gamma")  # no reviews — not a candidate

        result = agent.detect_playbook_update_candidates([alpha, beta, gamma])

        ids = [r[0] for r in result]
        self.assertIn("alpha", ids)
        self.assertIn("beta", ids)
        self.assertNotIn("gamma", ids)

        beta_result = next(r for r in result if r[0] == "beta")
        self.assertEqual(beta_result[1], 3)


if __name__ == "__main__":
    unittest.main()
