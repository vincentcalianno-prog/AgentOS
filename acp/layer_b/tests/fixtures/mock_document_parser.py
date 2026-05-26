"""Synthetic document parser fixture for Agent 4 (Structural Diff) tests.

Per Implementation Guide Section 7.1: synthetic fixtures only.
    Counterparty: Acme Industrial
    SCMs: alice, bob, carol

Provides pre-built clause sets representing:
  - An outbound version (round 1) of a generic agreement
  - Acme Industrial's counterparty redline (round 2): one modification,
    one addition, one deletion, remaining clauses unchanged

Use make_parser_for(clauses) to get a ParseDocumentFn that returns a
fixed clause list regardless of the bytes passed.
"""

from __future__ import annotations

from typing import Callable

from acp.layer_b.agents.structural_diff import Clause

# Type alias matching structural_diff.ParseDocumentFn
ParseDocumentFn = Callable[[bytes], list[Clause]]


# ---------------------------------------------------------------------------
# Synthetic clause sets
# ---------------------------------------------------------------------------

# Outbound version sent to Acme Industrial in round 1
OUTBOUND_CLAUSES: list[Clause] = [
    Clause(reference="1.1", text="Payment terms are net-30 from invoice date."),
    Clause(reference="1.2", text="Late payments incur a 1.5% monthly fee."),
    Clause(reference="2.1", text="Term of agreement is 24 months from execution."),
    Clause(reference="2.2", text="Either party may terminate with 60 days written notice."),
    Clause(reference="3.1", text="All deliveries shall be made FOB origin."),
]

# Acme Industrial's counterparty redline (round 2):
#   1.1 — modified (payment terms changed to net-45)
#   1.2 — unchanged
#   2.1 — unchanged
#   2.2 — modified (termination notice reduced to 30 days)
#   3.1 — deleted (removed entirely)
#   4.1 — added   (new force majeure clause)
COUNTERPARTY_CLAUSES: list[Clause] = [
    Clause(reference="1.1", text="Payment terms are net-45 from invoice date."),
    Clause(reference="1.2", text="Late payments incur a 1.5% monthly fee."),
    Clause(reference="2.1", text="Term of agreement is 24 months from execution."),
    Clause(reference="2.2", text="Either party may terminate with 30 days written notice."),
    Clause(reference="4.1", text="Neither party is liable for delays caused by force majeure events."),
]

# A minimal clause set with no changes (for unchanged-only tests)
IDENTICAL_CLAUSES: list[Clause] = [
    Clause(reference="1.1", text="Payment terms are net-30 from invoice date."),
    Clause(reference="1.2", text="Late payments incur a 1.5% monthly fee."),
]

# Single-clause sets for targeted modification tests
SINGLE_CLAUSE_OUTBOUND: list[Clause] = [
    Clause(reference="1.1", text="Original clause text."),
]
SINGLE_CLAUSE_COUNTERPARTY: list[Clause] = [
    Clause(reference="1.1", text="Modified clause text by counterparty."),
]


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def make_parser_for(clauses: list[Clause]) -> ParseDocumentFn:
    """Return a ParseDocumentFn that ignores its bytes argument and returns clauses."""
    def _parser(content: bytes) -> list[Clause]:
        return list(clauses)
    return _parser
