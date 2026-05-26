"""Unit tests: ContractRedlineWorkItemSource.

Per Implementation Guide Section 7.1: synthetic fixtures only.
    Tenants: alice, bob, carol
    Counterparties: Acme Industrial, Beta Manufacturing, Gamma Components

Uses SQLiteLedger(:memory:) directly — no StateManager, no TenancyEnforcer.
This is intentional: ContractRedlineWorkItemSource reads the ledger directly
for cross-tenant aggregation, bypassing per-tenant enforcement.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from acp.layer_b.agents.contract_redline_source import ContractRedlineWorkItemSource
from acp.layer_b.core.adapters.sqlite_ledger import SQLiteLedger
from acp.layer_b.core.types import (
    NegotiationRow,
    NegotiationState,
    PortfolioReadContext,
    ROLE_PORTFOLIO_AGGREGATOR,
)

_EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)
_RECENT = datetime(2026, 1, 10, tzinfo=timezone.utc)


def _ctx() -> PortfolioReadContext:
    return PortfolioReadContext(reader_id="system")


def _row(
    negotiation_id: str,
    owner: str,
    tenant_id: str,
    status: NegotiationState = NegotiationState.NEGOTIATING,
    counterparty_description: str | None = "Acme Industrial - synthetic widget assembly",
    contract_type: str | None = "generic-agreement",
    last_activity_date: datetime | None = _RECENT,
    round_number: int = 1,
    priority: str | None = "High",
    automation_status: str = "Active",
) -> NegotiationRow:
    return NegotiationRow(
        negotiation_id=negotiation_id,
        row_number=1,
        owner=owner,
        workflow_id="contract_redline",
        counterparty_description=counterparty_description,
        contract_type=contract_type,
        status=status,
        last_activity_date=last_activity_date,
        round_number=round_number,
        priority=priority,
        automation_status=automation_status,
    )


def _seed_ledger(ledger: SQLiteLedger) -> None:
    """Seed three tenants with realistic spread of rows."""
    ledger.upsert_row("alice", _row("neg-alice-001", owner="alice", tenant_id="alice",
                                    status=NegotiationState.NEGOTIATING,
                                    counterparty_description="Acme Industrial - synthetic widget assembly",
                                    last_activity_date=_EPOCH))
    ledger.upsert_row("alice", _row("neg-alice-002", owner="alice", tenant_id="alice",
                                    status=NegotiationState.PENDING_SIGNATURE,
                                    counterparty_description="Beta Manufacturing - synthetic components",
                                    last_activity_date=_RECENT))
    ledger.upsert_row("bob", _row("neg-bob-001", owner="bob", tenant_id="bob",
                                   status=NegotiationState.ON_HOLD,
                                   counterparty_description="Beta Manufacturing - synthetic components",
                                   last_activity_date=None))
    ledger.upsert_row("carol", _row("neg-carol-001", owner="carol", tenant_id="carol",
                                     status=NegotiationState.CONTRACT_SENT,
                                     counterparty_description="Gamma Components - synthetic assemblies",
                                     last_activity_date=_RECENT))


# ------------------------------------------------------------------ #
# Field mapping                                                       #
# ------------------------------------------------------------------ #

class WorkItemMappingTests(unittest.TestCase):
    """Each NegotiationRow field maps to the correct WorkItem field."""

    def setUp(self):
        self.ledger = SQLiteLedger(db_path=":memory:")
        self.ledger.upsert_row("alice", _row(
            "neg-test-001",
            owner="alice",
            tenant_id="alice",
            status=NegotiationState.NEGOTIATING,
            counterparty_description="Acme Industrial - synthetic widget assembly",
            contract_type="generic-agreement",
            last_activity_date=_RECENT,
            round_number=2,
            priority="High",
            automation_status="Active",
        ))
        self.source = ContractRedlineWorkItemSource(self.ledger)
        items = self.source.get_work_items(_ctx())
        self.assertEqual(len(items), 1)
        self.item = items[0]

    def test_work_item_id_is_negotiation_id(self):
        self.assertEqual(self.item.work_item_id, "neg-test-001")

    def test_tenant_id_is_correct(self):
        self.assertEqual(self.item.tenant_id, "alice")

    def test_workflow_id_is_contract_redline(self):
        self.assertEqual(self.item.workflow_id, "contract_redline")

    def test_owner_is_row_owner(self):
        self.assertEqual(self.item.owner, "alice")

    def test_status_is_negotiation_state_value(self):
        self.assertEqual(self.item.status, NegotiationState.NEGOTIATING.value)
        self.assertEqual(self.item.status, "Negotiating")

    def test_created_at_is_none(self):
        # NegotiationRow has no creation timestamp
        self.assertIsNone(self.item.created_at)

    def test_last_activity_at_maps_from_last_activity_date(self):
        self.assertEqual(self.item.last_activity_at, _RECENT)

    def test_counterparty_name_maps_from_counterparty_description(self):
        self.assertEqual(self.item.counterparty_name, "Acme Industrial - synthetic widget assembly")

    def test_contract_type_is_correct(self):
        self.assertEqual(self.item.contract_type, "generic-agreement")

    def test_payload_summary_contains_round_number(self):
        self.assertEqual(self.item.payload_summary.get("round_number"), 2)

    def test_payload_summary_contains_priority(self):
        self.assertEqual(self.item.payload_summary.get("priority"), "High")

    def test_payload_summary_contains_automation_status(self):
        self.assertEqual(self.item.payload_summary.get("automation_status"), "Active")


# ------------------------------------------------------------------ #
# Cross-tenant aggregation                                            #
# ------------------------------------------------------------------ #

class CrossTenantTests(unittest.TestCase):
    """Rows from all tenants appear in results with correct tenant_id."""

    def setUp(self):
        self.ledger = SQLiteLedger(db_path=":memory:")
        _seed_ledger(self.ledger)
        self.source = ContractRedlineWorkItemSource(self.ledger)
        self.items = self.source.get_work_items(_ctx())

    def test_all_four_rows_returned(self):
        self.assertEqual(len(self.items), 4)

    def test_alice_rows_have_correct_tenant_id(self):
        alice_items = [i for i in self.items if i.tenant_id == "alice"]
        self.assertEqual(len(alice_items), 2)

    def test_bob_rows_have_correct_tenant_id(self):
        bob_items = [i for i in self.items if i.tenant_id == "bob"]
        self.assertEqual(len(bob_items), 1)

    def test_carol_rows_have_correct_tenant_id(self):
        carol_items = [i for i in self.items if i.tenant_id == "carol"]
        self.assertEqual(len(carol_items), 1)

    def test_all_negotiation_ids_present(self):
        ids = {i.work_item_id for i in self.items}
        self.assertIn("neg-alice-001", ids)
        self.assertIn("neg-alice-002", ids)
        self.assertIn("neg-bob-001", ids)
        self.assertIn("neg-carol-001", ids)


# ------------------------------------------------------------------ #
# Empty ledger                                                        #
# ------------------------------------------------------------------ #

class EmptyLedgerTests(unittest.TestCase):
    """Empty ledger returns empty list without error."""

    def test_empty_ledger_returns_empty_list(self):
        ledger = SQLiteLedger(db_path=":memory:")
        source = ContractRedlineWorkItemSource(ledger)
        items = source.get_work_items(_ctx())
        self.assertEqual(items, [])


# ------------------------------------------------------------------ #
# Null / optional fields                                              #
# ------------------------------------------------------------------ #

class NullFieldTests(unittest.TestCase):
    """Optional NegotiationRow fields map correctly when None."""

    def test_none_last_activity_date_maps_to_none_last_activity_at(self):
        ledger = SQLiteLedger(db_path=":memory:")
        ledger.upsert_row("alice", _row("neg-null-001", owner="alice", tenant_id="alice",
                                        last_activity_date=None))
        source = ContractRedlineWorkItemSource(ledger)
        items = source.get_work_items(_ctx())
        self.assertEqual(len(items), 1)
        self.assertIsNone(items[0].last_activity_at)

    def test_none_counterparty_description_maps_to_none_counterparty_name(self):
        ledger = SQLiteLedger(db_path=":memory:")
        ledger.upsert_row("alice", _row("neg-null-002", owner="alice", tenant_id="alice",
                                        counterparty_description=None))
        source = ContractRedlineWorkItemSource(ledger)
        items = source.get_work_items(_ctx())
        self.assertIsNone(items[0].counterparty_name)

    def test_none_contract_type_maps_to_none_contract_type(self):
        ledger = SQLiteLedger(db_path=":memory:")
        ledger.upsert_row("alice", _row("neg-null-003", owner="alice", tenant_id="alice",
                                        contract_type=None))
        source = ContractRedlineWorkItemSource(ledger)
        items = source.get_work_items(_ctx())
        self.assertIsNone(items[0].contract_type)

    def test_source_name_is_stable(self):
        ledger = SQLiteLedger(db_path=":memory:")
        source = ContractRedlineWorkItemSource(ledger)
        self.assertEqual(source.source_name, "contract_redline")
        self.assertEqual(source.source_name, "contract_redline")  # stable across calls
