"""Synthetic LLM analyzer fixture for Agent 5 (Redline Analysis) tests.

Per Implementation Guide Section 7.1: synthetic fixtures only.
    Counterparty: Acme Industrial, Beta Manufacturing, Gamma Components
    Tenant owners: alice, bob, carol

Provides deterministic AnalyzeClauseFn stubs:
  - make_fixed_analyzer()         — returns the same recommendation for every clause
  - make_clause_map_analyzer()    — returns per-clause decisions by clause_reference
  - ACCEPT_ALL, REJECT_ALL, NEGOTIATE_ALL, ESCALATE_ALL — convenience stubs
  - ACME_INDUSTRIAL_ANALYZER      — maps the Acme Industrial round-1 scenario
    (clause_reference to recommendation matching COUNTERPARTY_CLAUSES in mock_document_parser)
"""

from __future__ import annotations

from typing import Callable

from acp.layer_b.agents.redline_analysis import AnalyzeClauseFn, ClauseRecommendation


def make_fixed_analyzer(
    recommendation: str,
    confidence: str = "high",
    requires_legal_review: bool = False,
    reasoning: str = "Synthetic fixed recommendation.",
    playbook_reference: str | None = None,
) -> AnalyzeClauseFn:
    """Return an AnalyzeClauseFn that gives the same decision for every clause."""
    def _analyze(
        clause_reference: str,
        change_type: str,
        original_text: str,
        counterparty_text: str,
        playbook_context: str,
        round_number: int = 0,
    ) -> ClauseRecommendation:
        return ClauseRecommendation(
            clause_reference=clause_reference,
            recommendation=recommendation,
            reasoning=reasoning,
            playbook_reference=playbook_reference,
            confidence=confidence,
            requires_legal_review=requires_legal_review,
        )
    return _analyze


def make_clause_map_analyzer(
    mapping: dict[str, ClauseRecommendation],
    default_recommendation: str = "escalate",
) -> AnalyzeClauseFn:
    """Return an AnalyzeClauseFn that looks up clause_reference in mapping.

    Clauses not in the mapping get a low-confidence escalation with
    default_recommendation.
    """
    def _analyze(
        clause_reference: str,
        change_type: str,
        original_text: str,
        counterparty_text: str,
        playbook_context: str,
        round_number: int = 0,
    ) -> ClauseRecommendation:
        if clause_reference in mapping:
            return mapping[clause_reference]
        return ClauseRecommendation(
            clause_reference=clause_reference,
            recommendation=default_recommendation,
            reasoning="No mapping defined for this clause reference.",
            playbook_reference=None,
            confidence="low",
            requires_legal_review=True,
        )
    return _analyze


# ---------------------------------------------------------------------------
# Convenience stubs
# ---------------------------------------------------------------------------

ACCEPT_ALL: AnalyzeClauseFn = make_fixed_analyzer("accept", confidence="high")
REJECT_ALL: AnalyzeClauseFn = make_fixed_analyzer(
    "reject", confidence="high", requires_legal_review=False
)
NEGOTIATE_ALL: AnalyzeClauseFn = make_fixed_analyzer("negotiate", confidence="medium")
ESCALATE_ALL: AnalyzeClauseFn = make_fixed_analyzer(
    "escalate", confidence="low", requires_legal_review=True
)


# ---------------------------------------------------------------------------
# Acme Industrial round-1 scenario
# Matches COUNTERPARTY_CLAUSES in mock_document_parser:
#   1.1 — modified (net-30 → net-45)          → reject
#   2.2 — modified (60 days → 30 days notice) → negotiate
#   3.1 — deleted                              → accept (deletion acceptable)
#   4.1 — added (force majeure)               → escalate (requires legal review)
# ---------------------------------------------------------------------------

ACME_INDUSTRIAL_ANALYZER: AnalyzeClauseFn = make_clause_map_analyzer({
    "1.1": ClauseRecommendation(
        clause_reference="1.1",
        recommendation="reject",
        reasoning="Net-45 payment terms exceed standard policy. Counterparty position not acceptable.",
        playbook_reference="payment-terms-policy",
        confidence="high",
        requires_legal_review=False,
    ),
    "2.2": ClauseRecommendation(
        clause_reference="2.2",
        recommendation="negotiate",
        reasoning="30-day notice is shorter than preferred 60-day. Counter with 45 days.",
        playbook_reference="termination-notice-policy",
        confidence="medium",
        requires_legal_review=False,
    ),
    "3.1": ClauseRecommendation(
        clause_reference="3.1",
        recommendation="accept",
        reasoning="Deletion of FOB origin clause is acceptable given revised logistics terms.",
        playbook_reference=None,
        confidence="high",
        requires_legal_review=False,
    ),
    "4.1": ClauseRecommendation(
        clause_reference="4.1",
        recommendation="escalate",
        reasoning="Force majeure addition introduces new liability scope. Requires legal review.",
        playbook_reference=None,
        confidence="medium",
        requires_legal_review=True,
    ),
})
