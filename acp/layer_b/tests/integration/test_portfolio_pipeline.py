"""Integration tests: Agent 9 (Portfolio Aggregator) pipeline.

Uses SQLiteLedger(:memory:) + StateManager (to seed rows via the normal write
path) + ContractRedlineWorkItemSource + PortfolioAggregatorAgent.

Three tenants with a realistic spread of statuses and activity ages:
    alice:  NEGOTIATING (100d old), PENDING_SIGNATURE (recent), EXECUTED_ACTIVE (recent)
    bob:    NEGOTIATING (100d old), ON_HOLD (200d old)
    carol:  CONTRACT_SENT (recent)

No time mocking is needed — tests use explicit old/recent dates computed
relative to test startup and thresholds that clearly separate the two bands.
StateManager stamps last_activity_date=now() only when None is passed; passing
an explicit old date preserves it through the ledger round-trip.

Per Implementation Guide Section 7.1: synthetic fixtures only.
    Counterparties: Acme Industrial, Beta Manufacturing, Gamma Components
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from acp.layer_b.agents.contract_redline_source import ContractRedlineWorkItemSource
from acp.layer_b.agents.portfolio_aggregator import PortfolioAggregatorAgent
from acp.layer_b.agents.state_manager import StateManager
from acp.layer_b.core.adapters.in_memory_audit import InMemoryAuditLog
from acp.layer_b.core.adapters.sqlite_ledger import SQLiteLedger
from acp.layer_b.core.tenancy import TenancyEnforcer
from acp.layer_b.core.types import (
    NegotiationRow,
    NegotiationState,
    PortfolioReadContext,
    TenantContext,
)

# Dates computed once at module load so all tests share the same reference frame.
# "old" items are 100–200 days past last activity; "recent" items are seconds old.
_NOW = datetime.now(timezone.utc)
_OLD = _NOW - timedelta(days=100)      # clearly stalled: > 50d threshold
_VERY_OLD = _NOW - timedelta(days=200) # maximally stalled for distinct ordering
_RECENT = _NOW - timedelta(seconds=30) # clearly recent: within any 7-day window

# Thresholds chosen so there is no ambiguity between old and recent bands.
_STALL_THRESHOLD_DAYS = 50   # old (100d+) stalled, recent (seconds) not stalled
_THROUGHPUT_DAYS = 7         # recent (seconds) counted, old (100d+) excluded


def _build_sm(ledger, audit):
    tenancy = TenancyEnforcer(audit)
    return StateManager(ledger=ledger, tenancy=tenancy, audit=audit)


def _seed_row(sm, tenant_id, negotiation_id, status, last_activity_date,
              counterparty_description, contract_type="generic-agreement",
              row_number=1):
    ctx = TenantContext(tenant_id=tenant_id)
    row = NegotiationRow(
        negotiation_id=negotiation_id,
        row_number=row_number,
        owner=tenant_id,
        workflow_id="contract_redline",
        counterparty_description=counterparty_description,
        contract_type=contract_type,
        status=status,
        last_activity_date=last_activity_date,
        round_number=1,
        priority="High",
        automation_status="Active",
    )
    sm.create_negotiation(ctx, row)


def _seed_all(sm):
    """Seed three tenants with varied statuses and activity ages.

    alice:  3 rows — 1 stale (100d), 2 recent
    bob:    2 rows — both stale (100d, 200d)
    carol:  1 row  — recent
    """
    _seed_row(sm, "alice", "neg-alice-001",
              NegotiationState.NEGOTIATING, _OLD,
              "Acme Industrial - synthetic widget assembly", row_number=1)
    _seed_row(sm, "alice", "neg-alice-002",
              NegotiationState.PENDING_SIGNATURE, _RECENT,
              "Beta Manufacturing - synthetic components", row_number=2)
    _seed_row(sm, "alice", "neg-alice-003",
              NegotiationState.EXECUTED_ACTIVE, _RECENT,
              "Gamma Components - synthetic assemblies", row_number=3)

    _seed_row(sm, "bob", "neg-bob-001",
              NegotiationState.NEGOTIATING, _OLD,
              "Beta Manufacturing - synthetic components", row_number=1)
    _seed_row(sm, "bob", "neg-bob-002",
              NegotiationState.ON_HOLD, _VERY_OLD,
              "Acme Industrial - synthetic widget assembly", row_number=2)

    _seed_row(sm, "carol", "neg-carol-001",
              NegotiationState.CONTRACT_SENT, _RECENT,
              "Gamma Components - synthetic assemblies", row_number=1)


class AggregationTests(unittest.TestCase):
    """Core aggregation queries return correct results across all tenants."""

    def setUp(self):
        self.ledger = SQLiteLedger(db_path=":memory:")
        self.audit = InMemoryAuditLog()
        self.sm = _build_sm(self.ledger, self.audit)
        _seed_all(self.sm)

        self.source = ContractRedlineWorkItemSource(self.ledger)
        self.agent = PortfolioAggregatorAgent(
            sources=[self.source],
            audit=self.audit,
        )
        self.ctx = PortfolioReadContext(reader_id="system")

    def test_all_six_rows_are_visible(self):
        depth = self.agent.queue_depth_by_status(self.ctx)
        self.assertEqual(sum(depth.values()), 6)

    def test_stalled_items_above_threshold(self):
        # Stalled (≥50d): neg-alice-001 (100d), neg-bob-001 (100d), neg-bob-002 (200d) = 3
        result = self.agent.stalled_work_items(self.ctx, threshold_days=_STALL_THRESHOLD_DAYS)
        self.assertEqual(len(result), 3)
        ids = {i.work_item_id for i in result}
        self.assertIn("neg-alice-001", ids)
        self.assertIn("neg-bob-001", ids)
        self.assertIn("neg-bob-002", ids)

    def test_recent_items_not_stalled(self):
        # Not stalled: alice-002, alice-003, carol-001 (all seconds old)
        result = self.agent.stalled_work_items(self.ctx, threshold_days=_STALL_THRESHOLD_DAYS)
        ids = {i.work_item_id for i in result}
        self.assertNotIn("neg-alice-002", ids)
        self.assertNotIn("neg-alice-003", ids)
        self.assertNotIn("neg-carol-001", ids)

    def test_queue_depth_negotiating_count(self):
        depth = self.agent.queue_depth_by_status(self.ctx)
        # NEGOTIATING: neg-alice-001, neg-bob-001 = 2
        self.assertEqual(depth.get(NegotiationState.NEGOTIATING.value), 2)

    def test_queue_depth_all_statuses_present(self):
        depth = self.agent.queue_depth_by_status(self.ctx)
        expected = {
            NegotiationState.NEGOTIATING.value,
            NegotiationState.PENDING_SIGNATURE.value,
            NegotiationState.EXECUTED_ACTIVE.value,
            NegotiationState.ON_HOLD.value,
            NegotiationState.CONTRACT_SENT.value,
        }
        self.assertEqual(set(depth.keys()), expected)

    def test_throughput_within_7_days(self):
        # Recent (seconds old): alice-002, alice-003 → alice:2; carol-001 → carol:1
        counts = self.agent.throughput_by_owner(self.ctx, days=_THROUGHPUT_DAYS)
        self.assertEqual(counts.get("alice"), 2)
        self.assertEqual(counts.get("carol"), 1)

    def test_old_items_excluded_from_throughput(self):
        # Old items (100d+): alice-001, bob-001, bob-002 → not counted in 7d window
        counts = self.agent.throughput_by_owner(self.ctx, days=_THROUGHPUT_DAYS)
        self.assertNotIn("bob", counts)

    def test_throughput_wide_window_includes_old_items(self):
        # 365-day window: everything except items with no activity (none seeded here)
        counts = self.agent.throughput_by_owner(self.ctx, days=365)
        self.assertEqual(counts.get("alice"), 3)
        self.assertEqual(counts.get("bob"), 2)
        self.assertEqual(counts.get("carol"), 1)


class WorkflowFilterTests(unittest.TestCase):
    """workflow_id and contract_type filters operate correctly on cross-tenant results."""

    def setUp(self):
        self.ledger = SQLiteLedger(db_path=":memory:")
        self.audit = InMemoryAuditLog()
        self.sm = _build_sm(self.ledger, self.audit)
        _seed_all(self.sm)

        self.source = ContractRedlineWorkItemSource(self.ledger)
        self.agent = PortfolioAggregatorAgent(
            sources=[self.source],
            audit=self.audit,
        )
        self.ctx = PortfolioReadContext(reader_id="system")

    def test_contract_redline_filter_returns_all_seeded_rows(self):
        depth = self.agent.queue_depth_by_status(self.ctx, workflow_id="contract_redline")
        self.assertEqual(sum(depth.values()), 6)

    def test_unknown_workflow_filter_returns_empty(self):
        depth = self.agent.queue_depth_by_status(self.ctx, workflow_id="rfq_workflow")
        self.assertEqual(depth, {})

    def test_contract_type_filter_matches_all_seeded_rows(self):
        # All rows seeded with contract_type="generic-agreement"
        depth = self.agent.queue_depth_by_status(self.ctx, contract_type="generic-agreement")
        self.assertEqual(sum(depth.values()), 6)

    def test_contract_type_filter_unknown_returns_empty(self):
        depth = self.agent.queue_depth_by_status(self.ctx, contract_type="specialized-agreement")
        self.assertEqual(depth, {})

    def test_combined_workflow_and_contract_type_filter(self):
        depth = self.agent.queue_depth_by_status(
            self.ctx,
            workflow_id="contract_redline",
            contract_type="generic-agreement",
        )
        self.assertEqual(sum(depth.values()), 6)


class AuditTests(unittest.TestCase):
    """Portfolio queries produce platform-scoped audit events."""

    def setUp(self):
        self.ledger = SQLiteLedger(db_path=":memory:")
        self.audit = InMemoryAuditLog()
        self.sm = _build_sm(self.ledger, self.audit)
        _seed_all(self.sm)

        source = ContractRedlineWorkItemSource(self.ledger)
        self.agent = PortfolioAggregatorAgent(sources=[source], audit=self.audit)
        self.ctx = PortfolioReadContext(reader_id="portfolio-system")

    def _portfolio_events(self):
        return self.audit.query(agent_name="portfolio_aggregator")

    def test_query_produces_audit_event(self):
        self.agent.queue_depth_by_status(self.ctx)
        self.assertGreater(len(self._portfolio_events()), 0)

    def test_audit_events_use_platform_workflow_id(self):
        self.agent.queue_depth_by_status(self.ctx)
        for evt in self._portfolio_events():
            self.assertEqual(evt.workflow_id, "platform")

    def test_audit_events_use_reader_id(self):
        self.agent.queue_depth_by_status(self.ctx)
        for evt in self._portfolio_events():
            self.assertEqual(evt.tenant_id, "portfolio-system")

    def test_all_three_query_types_produce_distinct_event_types(self):
        self.agent.stalled_work_items(self.ctx, threshold_days=_STALL_THRESHOLD_DAYS)
        self.agent.queue_depth_by_status(self.ctx)
        self.agent.throughput_by_owner(self.ctx, days=_THROUGHPUT_DAYS)
        event_types = {e.event_type for e in self._portfolio_events()}
        self.assertIn("stalled_work_items_queried", event_types)
        self.assertIn("queue_depth_queried", event_types)
        self.assertIn("throughput_queried", event_types)
