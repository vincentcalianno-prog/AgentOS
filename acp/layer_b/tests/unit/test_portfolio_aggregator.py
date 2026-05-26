"""Unit tests: Agent 9 (Portfolio Aggregator).

Per Implementation Guide Section 7.1: synthetic fixtures only.
    Tenants: alice, bob, carol
    Counterparties: Acme Industrial, Beta Manufacturing, Gamma Components

Unit tests use MockWorkItemSource — a configurable stub that returns a fixed
list of WorkItems. Agent 9 is tested independently of any ledger or source
implementation.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from acp.layer_b.agents.portfolio_aggregator import PortfolioAggregatorAgent
from acp.layer_b.core.adapters.audit_adapter import AuditLogAdapter
from acp.layer_b.core.adapters.in_memory_audit import InMemoryAuditLog
from acp.layer_b.core.adapters.work_item_source import WorkItemSource
from acp.layer_b.core.types import (
    ROLE_PORTFOLIO_AGGREGATOR,
    PortfolioReadContext,
    WorkItem,
)

_NOW = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
_10_DAYS_AGO = _NOW - timedelta(days=10)
_5_DAYS_AGO = _NOW - timedelta(days=5)
_20_DAYS_AGO = _NOW - timedelta(days=20)
_2_DAYS_AGO = _NOW - timedelta(days=2)


# ------------------------------------------------------------------ #
# Fixtures                                                            #
# ------------------------------------------------------------------ #

class MockWorkItemSource(WorkItemSource):
    """Configurable stub that returns a fixed list of WorkItems."""

    def __init__(self, items: list[WorkItem], name: str = "mock_source") -> None:
        self._items = list(items)
        self._name = name

    @property
    def source_name(self) -> str:
        return self._name

    def get_work_items(self, context: PortfolioReadContext) -> list[WorkItem]:
        return list(self._items)


class FailingWorkItemSource(WorkItemSource):
    """Source that always raises — tests non-fatal source failure."""

    @property
    def source_name(self) -> str:
        return "failing_source"

    def get_work_items(self, context: PortfolioReadContext) -> list[WorkItem]:
        raise RuntimeError("Source unavailable")


def _ctx(reader_id: str = "system") -> PortfolioReadContext:
    return PortfolioReadContext(reader_id=reader_id)


def _ctx_no_role() -> PortfolioReadContext:
    """Context with no roles — should trigger PermissionError."""
    return PortfolioReadContext(reader_id="unauthorized", roles=frozenset())


def _item(
    work_item_id: str,
    tenant_id: str = "alice",
    owner: str = "alice",
    status: str = "Negotiating",
    last_activity_at: datetime | None = _10_DAYS_AGO,
    workflow_id: str = "contract_redline",
    contract_type: str | None = "generic-agreement",
    counterparty_name: str | None = "Acme Industrial",
) -> WorkItem:
    return WorkItem(
        work_item_id=work_item_id,
        tenant_id=tenant_id,
        workflow_id=workflow_id,
        owner=owner,
        status=status,
        created_at=None,
        last_activity_at=last_activity_at,
        counterparty_name=counterparty_name,
        contract_type=contract_type,
    )


# Three-tenant synthetic dataset
_ALICE_ITEMS = [
    _item("neg-alice-001", tenant_id="alice", owner="alice", status="Negotiating",
          last_activity_at=_20_DAYS_AGO, counterparty_name="Acme Industrial"),
    _item("neg-alice-002", tenant_id="alice", owner="alice", status="Pending Signature",
          last_activity_at=_2_DAYS_AGO, counterparty_name="Beta Manufacturing"),
    _item("neg-alice-003", tenant_id="alice", owner="alice", status="Executed / Active",
          last_activity_at=_2_DAYS_AGO, counterparty_name="Gamma Components"),
]
_BOB_ITEMS = [
    _item("neg-bob-001", tenant_id="bob", owner="bob", status="Negotiating",
          last_activity_at=_20_DAYS_AGO, counterparty_name="Beta Manufacturing"),
    _item("neg-bob-002", tenant_id="bob", owner="bob", status="On Hold",
          last_activity_at=None, counterparty_name="Acme Industrial"),  # None = maximally stalled
]
_CAROL_ITEMS = [
    _item("neg-carol-001", tenant_id="carol", owner="carol", status="Contract Sent",
          last_activity_at=_2_DAYS_AGO, counterparty_name="Gamma Components"),
]
_ALL_ITEMS = _ALICE_ITEMS + _BOB_ITEMS + _CAROL_ITEMS


def _make_agent(
    items: list[WorkItem] | None = None,
    audit: AuditLogAdapter | None = None,
    extra_source: WorkItemSource | None = None,
) -> tuple[PortfolioAggregatorAgent, InMemoryAuditLog]:
    audit = audit or InMemoryAuditLog()
    source = MockWorkItemSource(items if items is not None else _ALL_ITEMS)
    sources = [source]
    if extra_source:
        sources.append(extra_source)
    return PortfolioAggregatorAgent(sources=sources, audit=audit), audit


# ------------------------------------------------------------------ #
# Stall detection                                                     #
# ------------------------------------------------------------------ #

class StallDetectionTests(unittest.TestCase):
    """stalled_work_items() threshold boundary conditions."""

    def _run(self, items, threshold_days, **kwargs):
        agent, _ = _make_agent(items)
        # Patch _NOW via a thin subclass to freeze time
        import unittest.mock as mock
        with mock.patch("acp.layer_b.agents.portfolio_aggregator.datetime") as dt:
            dt.now.return_value = _NOW
            dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            return agent.stalled_work_items(_ctx(), threshold_days, **kwargs)

    def test_item_older_than_threshold_is_stalled(self):
        # neg-alice-001 last activity 20 days ago; threshold = 10 → stalled
        items = [_item("neg-001", last_activity_at=_20_DAYS_AGO)]
        agent, _ = _make_agent(items)
        import unittest.mock as mock
        with mock.patch("acp.layer_b.agents.portfolio_aggregator.datetime") as dt:
            dt.now.return_value = _NOW
            result = agent.stalled_work_items(_ctx(), threshold_days=10)
        self.assertEqual(len(result), 1)

    def test_item_newer_than_threshold_is_not_stalled(self):
        # last activity 2 days ago; threshold = 10 → not stalled
        items = [_item("neg-001", last_activity_at=_2_DAYS_AGO)]
        agent, _ = _make_agent(items)
        import unittest.mock as mock
        with mock.patch("acp.layer_b.agents.portfolio_aggregator.datetime") as dt:
            dt.now.return_value = _NOW
            result = agent.stalled_work_items(_ctx(), threshold_days=10)
        self.assertEqual(len(result), 0)

    def test_item_with_no_last_activity_is_maximally_stalled(self):
        items = [_item("neg-001", last_activity_at=None)]
        agent, _ = _make_agent(items)
        import unittest.mock as mock
        with mock.patch("acp.layer_b.agents.portfolio_aggregator.datetime") as dt:
            dt.now.return_value = _NOW
            result = agent.stalled_work_items(_ctx(), threshold_days=1)
        self.assertEqual(len(result), 1)

    def test_stall_threshold_exactly_met_is_stalled(self):
        # Exactly at threshold — timedelta(days=10) >= timedelta(days=10) → stalled
        exactly_10_days_ago = _NOW - timedelta(days=10)
        items = [_item("neg-001", last_activity_at=exactly_10_days_ago)]
        agent, _ = _make_agent(items)
        import unittest.mock as mock
        with mock.patch("acp.layer_b.agents.portfolio_aggregator.datetime") as dt:
            dt.now.return_value = _NOW
            result = agent.stalled_work_items(_ctx(), threshold_days=10)
        self.assertEqual(len(result), 1)

    def test_empty_sources_returns_empty_list(self):
        agent, _ = _make_agent(items=[])
        result = agent.stalled_work_items(_ctx(), threshold_days=7)
        self.assertEqual(result, [])


# ------------------------------------------------------------------ #
# Queue depth                                                         #
# ------------------------------------------------------------------ #

class QueueDepthTests(unittest.TestCase):
    """queue_depth_by_status() counts items by status string."""

    def test_correct_counts_across_all_tenants(self):
        agent, _ = _make_agent(_ALL_ITEMS)
        depth = agent.queue_depth_by_status(_ctx())
        # Negotiating: alice-001, bob-001 = 2
        self.assertEqual(depth.get("Negotiating"), 2)
        # On Hold: bob-002 = 1
        self.assertEqual(depth.get("On Hold"), 1)
        # Pending Signature: alice-002 = 1
        self.assertEqual(depth.get("Pending Signature"), 1)

    def test_total_count_matches_item_count(self):
        agent, _ = _make_agent(_ALL_ITEMS)
        depth = agent.queue_depth_by_status(_ctx())
        self.assertEqual(sum(depth.values()), len(_ALL_ITEMS))

    def test_empty_sources_returns_empty_dict(self):
        agent, _ = _make_agent(items=[])
        depth = agent.queue_depth_by_status(_ctx())
        self.assertEqual(depth, {})

    def test_single_status_returns_one_key(self):
        items = [_item("neg-001", status="On Hold"), _item("neg-002", status="On Hold")]
        agent, _ = _make_agent(items)
        depth = agent.queue_depth_by_status(_ctx())
        self.assertEqual(list(depth.keys()), ["On Hold"])
        self.assertEqual(depth["On Hold"], 2)


# ------------------------------------------------------------------ #
# Throughput                                                          #
# ------------------------------------------------------------------ #

class ThroughputTests(unittest.TestCase):
    """throughput_by_owner() counts recently active items per owner."""

    def test_items_within_window_counted(self):
        # alice-002 and alice-003 active 2 days ago; window = 7 days
        agent, _ = _make_agent(_ALL_ITEMS)
        import unittest.mock as mock
        with mock.patch("acp.layer_b.agents.portfolio_aggregator.datetime") as dt:
            dt.now.return_value = _NOW
            counts = agent.throughput_by_owner(_ctx(), days=7)
        # alice: 2 items (alice-002 + alice-003), carol: 1 item (carol-001)
        self.assertEqual(counts.get("alice"), 2)
        self.assertEqual(counts.get("carol"), 1)

    def test_items_outside_window_excluded(self):
        # alice-001 and bob-001 last activity 20 days ago; window = 7 days → excluded
        agent, _ = _make_agent(_ALL_ITEMS)
        import unittest.mock as mock
        with mock.patch("acp.layer_b.agents.portfolio_aggregator.datetime") as dt:
            dt.now.return_value = _NOW
            counts = agent.throughput_by_owner(_ctx(), days=7)
        # bob has only stale/None items in last 7 days
        self.assertNotIn("bob", counts)

    def test_items_with_no_activity_excluded(self):
        # bob-002 has last_activity_at=None → excluded from throughput
        items = [_item("neg-001", owner="bob", last_activity_at=None)]
        agent, _ = _make_agent(items)
        import unittest.mock as mock
        with mock.patch("acp.layer_b.agents.portfolio_aggregator.datetime") as dt:
            dt.now.return_value = _NOW
            counts = agent.throughput_by_owner(_ctx(), days=30)
        self.assertEqual(counts, {})

    def test_empty_sources_returns_empty_dict(self):
        agent, _ = _make_agent(items=[])
        counts = agent.throughput_by_owner(_ctx(), days=7)
        self.assertEqual(counts, {})


# ------------------------------------------------------------------ #
# Filters                                                             #
# ------------------------------------------------------------------ #

class FilterTests(unittest.TestCase):
    """workflow_id and contract_type filters narrow results correctly."""

    def _make_mixed_items(self) -> list[WorkItem]:
        return [
            _item("neg-cr-001", workflow_id="contract_redline", contract_type="generic-agreement"),
            _item("neg-cr-002", workflow_id="contract_redline", contract_type="specialized-agreement"),
            _item("neg-other-001", workflow_id="rfq_workflow", contract_type=None),
        ]

    def test_workflow_id_filter_narrows_results(self):
        agent, _ = _make_agent(self._make_mixed_items())
        depth = agent.queue_depth_by_status(_ctx(), workflow_id="contract_redline")
        total = sum(depth.values())
        self.assertEqual(total, 2)

    def test_contract_type_filter_narrows_results(self):
        agent, _ = _make_agent(self._make_mixed_items())
        import unittest.mock as mock
        with mock.patch("acp.layer_b.agents.portfolio_aggregator.datetime") as dt:
            dt.now.return_value = _NOW
            result = agent.stalled_work_items(
                _ctx(), threshold_days=1, contract_type="generic-agreement"
            )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].work_item_id, "neg-cr-001")

    def test_combined_filter_both_must_match(self):
        agent, _ = _make_agent(self._make_mixed_items())
        depth = agent.queue_depth_by_status(
            _ctx(), workflow_id="contract_redline", contract_type="specialized-agreement"
        )
        self.assertEqual(sum(depth.values()), 1)

    def test_no_filter_returns_all_workflows(self):
        agent, _ = _make_agent(self._make_mixed_items())
        depth = agent.queue_depth_by_status(_ctx())
        self.assertEqual(sum(depth.values()), 3)

    def test_nonmatching_filter_returns_empty(self):
        agent, _ = _make_agent(self._make_mixed_items())
        depth = agent.queue_depth_by_status(_ctx(), workflow_id="nonexistent_workflow")
        self.assertEqual(depth, {})


# ------------------------------------------------------------------ #
# Role enforcement                                                    #
# ------------------------------------------------------------------ #

class RoleEnforcementTests(unittest.TestCase):
    """Missing ROLE_PORTFOLIO_AGGREGATOR raises PermissionError on every method."""

    def setUp(self):
        self.agent, _ = _make_agent()

    def test_stalled_work_items_requires_role(self):
        with self.assertRaises(PermissionError):
            self.agent.stalled_work_items(_ctx_no_role(), threshold_days=7)

    def test_queue_depth_requires_role(self):
        with self.assertRaises(PermissionError):
            self.agent.queue_depth_by_status(_ctx_no_role())

    def test_throughput_requires_role(self):
        with self.assertRaises(PermissionError):
            self.agent.throughput_by_owner(_ctx_no_role(), days=7)

    def test_valid_role_does_not_raise(self):
        # Default PortfolioReadContext carries the role — must not raise
        try:
            self.agent.queue_depth_by_status(_ctx())
        except PermissionError:
            self.fail("PermissionError raised with valid PortfolioReadContext")


# ------------------------------------------------------------------ #
# Source failure                                                      #
# ------------------------------------------------------------------ #

class SourceFailureTests(unittest.TestCase):
    """A failing source is non-fatal; results from healthy sources are returned."""

    def test_failing_source_does_not_abort_query(self):
        healthy = MockWorkItemSource([_item("neg-001")], name="healthy_source")
        failing = FailingWorkItemSource()
        audit = InMemoryAuditLog()
        agent = PortfolioAggregatorAgent(sources=[failing, healthy], audit=audit)
        depth = agent.queue_depth_by_status(_ctx())
        self.assertEqual(sum(depth.values()), 1)

    def test_failing_source_is_audited_as_error(self):
        failing = FailingWorkItemSource()
        audit = InMemoryAuditLog()
        agent = PortfolioAggregatorAgent(sources=[failing], audit=audit)
        agent.queue_depth_by_status(_ctx())
        errors = [e for e in audit.query(agent_name="portfolio_aggregator") if e.severity == "error"]
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].event_type, "source_error")
        self.assertIn("failing_source", errors[0].payload.get("source_name", ""))

    def test_no_sources_returns_empty_result(self):
        audit = InMemoryAuditLog()
        agent = PortfolioAggregatorAgent(sources=[], audit=audit)
        depth = agent.queue_depth_by_status(_ctx())
        self.assertEqual(depth, {})


# ------------------------------------------------------------------ #
# Audit trail                                                         #
# ------------------------------------------------------------------ #

class AuditTrailTests(unittest.TestCase):
    """Every query writes a platform-scoped audit event."""

    def setUp(self):
        self.audit = InMemoryAuditLog()
        self.agent, _ = _make_agent(audit=self.audit)

    def _portfolio_events(self):
        return self.audit.query(agent_name="portfolio_aggregator")

    def test_stalled_query_writes_audit_event(self):
        import unittest.mock as mock
        with mock.patch("acp.layer_b.agents.portfolio_aggregator.datetime") as dt:
            dt.now.return_value = _NOW
            self.agent.stalled_work_items(_ctx(), threshold_days=7)
        events = [e for e in self._portfolio_events() if e.event_type == "stalled_work_items_queried"]
        self.assertEqual(len(events), 1)

    def test_queue_depth_query_writes_audit_event(self):
        self.agent.queue_depth_by_status(_ctx())
        events = [e for e in self._portfolio_events() if e.event_type == "queue_depth_queried"]
        self.assertEqual(len(events), 1)

    def test_throughput_query_writes_audit_event(self):
        import unittest.mock as mock
        with mock.patch("acp.layer_b.agents.portfolio_aggregator.datetime") as dt:
            dt.now.return_value = _NOW
            self.agent.throughput_by_owner(_ctx(), days=7)
        events = [e for e in self._portfolio_events() if e.event_type == "throughput_queried"]
        self.assertEqual(len(events), 1)

    def test_audit_events_use_platform_workflow_id(self):
        self.agent.queue_depth_by_status(_ctx())
        for evt in self._portfolio_events():
            self.assertEqual(evt.workflow_id, "platform")

    def test_audit_events_use_reader_id_as_tenant(self):
        ctx = PortfolioReadContext(reader_id="portfolio-system")
        self.agent.queue_depth_by_status(ctx)
        for evt in self._portfolio_events():
            self.assertEqual(evt.tenant_id, "portfolio-system")

    def test_audit_events_have_no_negotiation_id(self):
        self.agent.queue_depth_by_status(_ctx())
        for evt in self._portfolio_events():
            self.assertIsNone(evt.negotiation_id)

    def test_stall_audit_payload_includes_result_count(self):
        import unittest.mock as mock
        with mock.patch("acp.layer_b.agents.portfolio_aggregator.datetime") as dt:
            dt.now.return_value = _NOW
            self.agent.stalled_work_items(_ctx(), threshold_days=1)
        evt = next(e for e in self._portfolio_events() if e.event_type == "stalled_work_items_queried")
        self.assertIn("result_count", evt.payload)
        self.assertIn("threshold_days", evt.payload)
