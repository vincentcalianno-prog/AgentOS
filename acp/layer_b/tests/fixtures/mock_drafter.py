"""Synthetic LLM drafter fixture for Agent 6 (Counter-Proposal Drafting) tests.

Per Implementation Guide Section 7.1: synthetic fixtures only.
    Counterparties: Acme Industrial, Beta Manufacturing, Gamma Components
    Tenant owners: alice, bob, carol

Provides deterministic DraftCounterProposalFn stubs:
  - make_fixed_drafter()          — returns the same draft for every clause
  - make_clause_map_drafter()     — returns per-clause drafts by clause_reference
  - ACME_INDUSTRIAL_DRAFTER       — maps the Acme Industrial round-1 scenario:
      1.1 (reject): firm counter back to net-30 terms
      2.2 (negotiate): collaborative counter offering 45-day notice as compromise
"""

from __future__ import annotations

from acp.layer_b.agents.counter_proposal import CounterProposalDraft, DraftCounterProposalFn


def make_fixed_drafter(
    counter_text: str,
    reasoning: str = "Synthetic fixed draft.",
    tone: str = "neutral",
    requires_legal_review: bool = False,
    playbook_reference: str | None = None,
) -> DraftCounterProposalFn:
    """Return a DraftCounterProposalFn that returns the same draft for every clause."""
    def _draft(
        clause_reference: str,
        recommendation: str,
        reasoning_from_analysis: str,
        original_text: str,
        counterparty_text: str,
        playbook_context: str,
        restore_strategy: str = "redraft",
    ) -> CounterProposalDraft:
        return CounterProposalDraft(
            clause_reference=clause_reference,
            based_on_recommendation=recommendation,
            original_text=original_text,
            counterparty_text=counterparty_text,
            counter_text=counter_text,
            reasoning=reasoning,
            tone=tone,
            playbook_reference=playbook_reference,
            requires_legal_review=requires_legal_review,
        )
    return _draft


def make_clause_map_drafter(
    mapping: dict[str, CounterProposalDraft],
    default_counter_text: str = "",
) -> DraftCounterProposalFn:
    """Return a DraftCounterProposalFn that looks up clause_reference in mapping.

    Clauses not in the mapping get a neutral placeholder with empty counter_text.
    """
    def _draft(
        clause_reference: str,
        recommendation: str,
        reasoning_from_analysis: str,
        original_text: str,
        counterparty_text: str,
        playbook_context: str,
        restore_strategy: str = "redraft",
    ) -> CounterProposalDraft:
        if clause_reference in mapping:
            return mapping[clause_reference]
        return CounterProposalDraft(
            clause_reference=clause_reference,
            based_on_recommendation=recommendation,
            original_text=original_text,
            counterparty_text=counterparty_text,
            counter_text=default_counter_text,
            reasoning="No mapping defined for this clause reference.",
            tone="neutral",
            playbook_reference=None,
            requires_legal_review=False,
        )
    return _draft


# ---------------------------------------------------------------------------
# Acme Industrial round-1 scenario
# Only 1.1 (reject) and 2.2 (negotiate) are draftable per ACME_INDUSTRIAL_ANALYZER.
# ---------------------------------------------------------------------------

ACME_INDUSTRIAL_DRAFTER: DraftCounterProposalFn = make_clause_map_drafter({
    "1.1": CounterProposalDraft(
        clause_reference="1.1",
        based_on_recommendation="reject",
        original_text="Payment terms are net-30 from invoice date.",
        counterparty_text="Payment terms are net-45 from invoice date.",
        counter_text="Payment terms shall remain net-30 from invoice date, consistent with standard terms.",
        reasoning="Net-45 exceeds policy maximum. Reinstating net-30 as per payment terms policy.",
        tone="firm",
        playbook_reference="payment-terms-policy",
        requires_legal_review=False,
    ),
    "2.2": CounterProposalDraft(
        clause_reference="2.2",
        based_on_recommendation="negotiate",
        original_text="Either party may terminate with 60 days written notice.",
        counterparty_text="Either party may terminate with 30 days written notice.",
        counter_text="Either party may terminate with 45 days written notice.",
        reasoning="Proposing 45-day notice as a compromise between the original 60 and counterparty's 30.",
        tone="collaborative",
        playbook_reference="termination-notice-policy",
        requires_legal_review=False,
    ),
})
