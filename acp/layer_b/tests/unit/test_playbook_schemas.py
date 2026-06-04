"""Unit tests for playbook schema dataclasses.

Per Implementation Guide Section 7.1: synthetic fixtures only.
    Counterparties: Acme Industrial, Beta Manufacturing, Gamma Components
    Tenant owners: alice, bob, carol
"""

from __future__ import annotations

import unittest

from acp.schemas.playbook_schemas import (
    AbstractionStatus,
    AcceptModification,
    AcceptanceResponse,
    AntoraResponse,
    CompromiseResponse,
    OutcomeRecord,
    PlaybookEntry,
    RecommendationReview,
    RejectThreshold,
    RejectionResponse,
    ReviewerReaction,
)


class OutcomeRecordDefaultsTests(unittest.TestCase):
    """OutcomeRecord fields default to safe, processable values."""

    def test_abstraction_status_defaults_to_pending(self):
        rec = OutcomeRecord()
        self.assertEqual(rec.abstraction_status, AbstractionStatus.PENDING)

    def test_sandelin_override_defaults_to_false(self):
        rec = OutcomeRecord()
        self.assertFalse(rec.sandelin_override)

    def test_rounds_to_close_defaults_to_zero(self):
        rec = OutcomeRecord()
        self.assertEqual(rec.rounds_to_close, 0)

    def test_all_string_fields_default_to_empty(self):
        rec = OutcomeRecord()
        for field_name in ("date", "counterparty", "agent_recommendation",
                           "actual_outcome", "notes"):
            self.assertEqual(getattr(rec, field_name), "",
                             f"{field_name} should default to empty string")

    def test_explicit_construction(self):
        rec = OutcomeRecord(
            date="2026-05-30",
            counterparty="Acme Industrial",
            agent_recommendation="counter",
            actual_outcome="accepted",
            rounds_to_close=2,
            sandelin_override=True,
            abstraction_status=AbstractionStatus.EXTRACTED,
            notes="Accepted on second round.",
        )
        self.assertEqual(rec.date, "2026-05-30")
        self.assertTrue(rec.sandelin_override)
        self.assertEqual(rec.abstraction_status, AbstractionStatus.EXTRACTED)

    def test_abstraction_status_all_values_valid(self):
        for status in AbstractionStatus:
            rec = OutcomeRecord(abstraction_status=status)
            self.assertEqual(rec.abstraction_status, status)


class RecommendationReviewDefaultsTests(unittest.TestCase):
    """RecommendationReview fields default to safe values."""

    def test_reaction_defaults_to_none(self):
        rev = RecommendationReview()
        self.assertIsNone(rev.reaction)

    def test_abstraction_status_defaults_to_pending(self):
        rev = RecommendationReview()
        self.assertEqual(rev.abstraction_status, AbstractionStatus.PENDING)

    def test_all_string_fields_default_to_empty(self):
        rev = RecommendationReview()
        for field_name in ("date", "proposed_counter", "reviewer_role",
                           "revised_language", "rationale", "notes"):
            self.assertEqual(getattr(rev, field_name), "",
                             f"{field_name} should default to empty string")

    def test_explicit_construction_accepted(self):
        rev = RecommendationReview(
            date="2026-05-30",
            proposed_counter="Counter text.",
            reviewer_role="owner",
            reaction=ReviewerReaction.ACCEPTED,
            revised_language="",
            rationale="Position is correct.",
            abstraction_status=AbstractionStatus.PENDING,
        )
        self.assertEqual(rev.reaction, ReviewerReaction.ACCEPTED)
        self.assertEqual(rev.reviewer_role, "owner")

    def test_explicit_construction_edited(self):
        rev = RecommendationReview(
            reaction=ReviewerReaction.EDITED,
            revised_language="Revised counter text.",
        )
        self.assertEqual(rev.reaction, ReviewerReaction.EDITED)
        self.assertFalse(rev.revised_language == "")

    def test_reviewer_reaction_all_values_valid(self):
        for reaction in ReviewerReaction:
            rev = RecommendationReview(reaction=reaction)
            self.assertEqual(rev.reaction, reaction)


class AntoraResponseOnPlaybookEntryTests(unittest.TestCase):
    """AntoraResponse coexists with accept_modifications and reject_thresholds."""

    def test_playbook_entry_default_has_antora_response(self):
        entry = PlaybookEntry()
        self.assertIsNotNone(entry.antora_response)
        self.assertIsInstance(entry.antora_response, AntoraResponse)

    def test_antora_response_coexists_with_accept_modifications(self):
        entry = PlaybookEntry(
            id="generic.clause.payment_terms",
            accept_modifications=[
                AcceptModification(
                    id="net_45_acceptable",
                    description="Net-45 payment terms acceptable.",
                    example_language="payment due within 45 days",
                    rationale="Within policy tolerance.",
                ),
            ],
            antora_response=AntoraResponse(
                rejection_response=RejectionResponse(
                    rationale="Net-60 exceeds policy.",
                    counter_proposal="Payment due within 30 days.",
                ),
                compromise_response=CompromiseResponse(
                    conditions="Net-45 acceptable with discount.",
                    revised_language="Payment due within 45 days.",
                ),
                acceptance_response=AcceptanceResponse(
                    rationale="Net-30 or better already protects operator.",
                ),
            ),
        )
        self.assertEqual(len(entry.accept_modifications), 1)
        self.assertIsNotNone(entry.antora_response)
        self.assertEqual(
            entry.antora_response.rejection_response.rationale,
            "Net-60 exceeds policy.",
        )

    def test_antora_response_coexists_with_reject_thresholds(self):
        entry = PlaybookEntry(
            id="generic.clause.indemnity",
            reject_thresholds=[
                RejectThreshold(
                    id="mutual_indemnity_removal",
                    description="Counterparty removes mutual indemnity.",
                    example_language="[section deleted]",
                    rationale="Hard reject.",
                ),
            ],
            antora_response=AntoraResponse(),
        )
        self.assertEqual(len(entry.reject_thresholds), 1)
        self.assertIsNotNone(entry.antora_response)

    def test_playbook_entry_outcome_log_defaults_to_empty_list(self):
        entry = PlaybookEntry()
        self.assertEqual(entry.outcome_log, [])

    def test_playbook_entry_recommendation_reviews_defaults_to_empty_list(self):
        entry = PlaybookEntry()
        self.assertEqual(entry.recommendation_reviews, [])

    def test_playbook_entry_outcome_log_accepts_records(self):
        entry = PlaybookEntry(
            id="generic.clause.warranty",
            outcome_log=[
                OutcomeRecord(
                    date="2026-05-30",
                    counterparty="Beta Manufacturing",
                    agent_recommendation="counter",
                    actual_outcome="compromised",
                    rounds_to_close=3,
                ),
            ],
        )
        self.assertEqual(len(entry.outcome_log), 1)
        self.assertEqual(entry.outcome_log[0].counterparty, "Beta Manufacturing")

    def test_playbook_entry_recommendation_reviews_accepts_reviews(self):
        entry = PlaybookEntry(
            id="generic.clause.warranty",
            recommendation_reviews=[
                RecommendationReview(
                    date="2026-05-30",
                    reviewer_role="owner",
                    reaction=ReviewerReaction.EDITED,
                    revised_language="Modified counter text.",
                ),
            ],
        )
        self.assertEqual(len(entry.recommendation_reviews), 1)
        self.assertEqual(
            entry.recommendation_reviews[0].reaction,
            ReviewerReaction.EDITED,
        )
