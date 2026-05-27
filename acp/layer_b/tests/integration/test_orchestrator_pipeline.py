"""Integration tests: Agent 8 (Workflow Orchestrator) pipeline.

Uses SQLiteLedger(:memory:), StateManager, InMemoryAuditLog,
ContractRedlineWorkItemSource, PortfolioAggregatorAgent, and
WorkflowOrchestratorAgent wired together.

Three test classes:
    SLANotificationPipelineTests   — stale row → scan → notification routed to SM
    DegradedModePipelineTests      — enter_degraded_mode → SM sets Paused → pipeline gated
    RetryExhaustionPipelineTests   — process_event × max_attempts → degraded mode

Per Implementation Guide Section 7.1: synthetic counterparties only.
    Counterparties: Acme Industrial, Beta Manufacturing
"""

from __future__ import annotations

import json
import unittest
import uuid
from datetime import datetime, timedelta, timezone

from acp.layer_b.agents.contract_redline_source import ContractRedlineWorkItemSource
from acp.layer_b.agents.portfolio_aggregator import PortfolioAggregatorAgent
from acp.layer_b.agents.state_manager import StateManager
from acp.layer_b.agents.workflow_orchestrator import WorkflowOrchestratorAgent
from acp.layer_b.core.adapters.in_memory_audit import InMemoryAuditLog
from acp.layer_b.core.adapters.sqlite_ledger import SQLiteLedger
from acp.layer_b.core.tenancy import TenancyEnforcer
from acp.layer_b.core.types import (
    EVENT_NEGOTIATION_FAILED,
    EVENT_NEGOTIATION_PAUSED,
    EVENT_NOTIFICATION_REQUIRED,
    EVENT_RETRY_EXHAUSTED,
    EventRetryRow,
    NegotiationRow,
    NegotiationState,
    PortfolioReadContext,
    StateEvent,
    TenantContext,
)
from acp.layer_b.tests.fixtures.synthetic_config import SYNTHETIC_CONFIG

_NOW = datetime.now(timezone.utc)
_OLD = _NOW - timedelta(days=100)   # clearly stalled: > 10d threshold
_RECENT = _NOW - timedelta(seconds=30)

_PORTFOLIO_CTX = PortfolioReadContext(reader_id="system")


# ---------------------------------------------------------------
# Shared setup
# ---------------------------------------------------------------

def _build_wired_stack():
    """Return all agents wired together; SM subscribes to orchestrator and vice versa."""
    ledger = SQLiteLedger(db_path=":memory:")
    audit = InMemoryAuditLog()
    tenancy = TenancyEnforcer(audit)
    sm = StateManager(ledger=ledger, tenancy=tenancy, audit=audit)

    source = ContractRedlineWorkItemSource(ledger)
    portfolio = PortfolioAggregatorAgent(sources=[source], audit=audit)

    orch = WorkflowOrchestratorAgent(
        config=SYNTHETIC_CONFIG, ledger=ledger, audit=audit, portfolio=portfolio
    )

    # Wire: SM forwards NEGOTIATION_FAILED / RETRY_REQUIRED to orchestrator
    sm.subscribe(
        lambda event: orch.process_event(
            TenantContext(tenant_id=event.tenant_id), event
        )
    )
    # Wire: orchestrator forwards NEGOTIATION_PAUSED to SM so it can set automation_status
    orch.subscribe(
        lambda event: sm.process_event(
            TenantContext(tenant_id=event.tenant_id), event
        ) if event.event_type == EVENT_NEGOTIATION_PAUSED else None
    )

    return ledger, audit, sm, portfolio, orch


def _seed(sm, tenant_id, negotiation_id, status, last_activity_date,
          inbox_thread_id=None, automation_status="Active", row_number=1):
    ctx = TenantContext(tenant_id=tenant_id)
    row = NegotiationRow(
        negotiation_id=negotiation_id,
        row_number=row_number,
        owner=tenant_id,
        workflow_id="contract_redline",
        counterparty_description="Acme Industrial - synthetic widget assembly",
        contract_type="generic-agreement",
        status=status,
        last_activity_date=last_activity_date,
        round_number=1,
        priority="High",
        automation_status=automation_status,
        inbox_thread_id=inbox_thread_id,
    )
    sm.create_negotiation(ctx, row)


# ---------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------

class SLANotificationPipelineTests(unittest.TestCase):
    """scan_sla_violations() → SLA breach → NOTIFICATION_REQUIRED emitted."""

    def setUp(self):
        self.ledger, self.audit, self.sm, self.portfolio, self.orch = _build_wired_stack()
        self.received: list[StateEvent] = []
        self.orch.subscribe(self.received.append)

        # One stale NEGOTIATING row (100d > 10d threshold) — should trigger SLA breach
        _seed(self.sm, "alice", "neg-stale-001",
              NegotiationState.NEGOTIATING, _OLD, row_number=1)
        # One recent NEGOTIATING row — should NOT trigger
        _seed(self.sm, "alice", "neg-recent-001",
              NegotiationState.NEGOTIATING, _RECENT, row_number=2)

    def test_stale_row_produces_notification_required_event(self):
        self.orch.scan_sla_violations(_PORTFOLIO_CTX)
        notifs = [
            e for e in self.received
            if e.event_type == EVENT_NOTIFICATION_REQUIRED
            and e.negotiation_id == "neg-stale-001"
        ]
        self.assertGreater(len(notifs), 0)

    def test_notification_carries_recipient_id(self):
        self.orch.scan_sla_violations(_PORTFOLIO_CTX)
        notifs = [
            e for e in self.received
            if e.event_type == EVENT_NOTIFICATION_REQUIRED
            and e.negotiation_id == "neg-stale-001"
        ]
        self.assertGreater(len(notifs), 0)
        self.assertIn("recipient_id", notifs[0].payload)

    def test_recent_row_produces_no_notification(self):
        self.orch.scan_sla_violations(_PORTFOLIO_CTX)
        notifs = [
            e for e in self.received
            if e.event_type == EVENT_NOTIFICATION_REQUIRED
            and e.negotiation_id == "neg-recent-001"
        ]
        self.assertEqual(notifs, [])

    def test_scan_produces_audit_events(self):
        self.orch.scan_sla_violations(_PORTFOLIO_CTX)
        orch_events = self.audit.query(agent_name="workflow_orchestrator")
        types = [e.event_type for e in orch_events]
        self.assertIn("sla_violations_detected", types)

    def test_scan_audit_events_use_platform_workflow_id(self):
        self.orch.scan_sla_violations(_PORTFOLIO_CTX)
        orch_events = self.audit.query(agent_name="workflow_orchestrator")
        self.assertTrue(all(e.workflow_id == "platform" for e in orch_events))

    def test_two_tenants_both_scanned(self):
        _seed(self.sm, "bob", "neg-bob-stale-001",
              NegotiationState.NEGOTIATING, _OLD, row_number=1)
        notifications = self.orch.scan_sla_violations(_PORTFOLIO_CTX)
        negotiation_ids = {n.negotiation_id for n in notifications}
        self.assertIn("neg-stale-001", negotiation_ids)
        self.assertIn("neg-bob-stale-001", negotiation_ids)


class DegradedModePipelineTests(unittest.TestCase):
    """enter_degraded_mode → SM sets Paused → SM gates further pipeline events."""

    def setUp(self):
        self.ledger, self.audit, self.sm, self.portfolio, self.orch = _build_wired_stack()
        self.received: list[StateEvent] = []
        self.orch.subscribe(self.received.append)
        _seed(self.sm, "alice", "neg-alice-001",
              NegotiationState.NEGOTIATING, _RECENT)

    def _ctx(self):
        return TenantContext(tenant_id="alice")

    def test_enter_degraded_mode_emits_negotiation_paused(self):
        self.orch.enter_degraded_mode(self._ctx(), "neg-alice-001", reason="test")
        types = {e.event_type for e in self.received}
        self.assertIn(EVENT_NEGOTIATION_PAUSED, types)

    def test_sm_receives_paused_event_and_sets_paused_status(self):
        self.orch.enter_degraded_mode(self._ctx(), "neg-alice-001", reason="test")
        row = self.sm.get_negotiation(self._ctx(), "neg-alice-001")
        self.assertEqual(row.automation_status, "Paused")

    def test_pipeline_gated_after_degraded_mode(self):
        """After pausing, SM's re-emit handlers gate events for this negotiation."""
        # First put negotiation into Paused state
        self.orch.enter_degraded_mode(self._ctx(), "neg-alice-001", reason="test")
        row = self.sm.get_negotiation(self._ctx(), "neg-alice-001")
        self.assertEqual(row.automation_status, "Paused")

        # Now simulate a diff_complete event arriving — SM should gate it
        downstream_received: list[StateEvent] = []
        # Subscribe a second subscriber that records re-emitted diff_complete events
        self.sm.subscribe(lambda e: downstream_received.append(e)
                          if e.event_type == "diff_complete" else None)

        diff_event = StateEvent(
            event_type="diff_complete",
            tenant_id="alice",
            negotiation_id="neg-alice-001",
            workflow_id="contract_redline",
            payload={"round_number": 1},
            emitted_at=datetime.now(timezone.utc),
            emitted_by="test",
        )
        self.sm.process_event(self._ctx(), diff_event)

        # diff_complete should NOT be re-emitted since negotiation is Paused
        self.assertEqual(downstream_received, [])

    def test_audit_records_pipeline_gated(self):
        self.orch.enter_degraded_mode(self._ctx(), "neg-alice-001", reason="test")

        diff_event = StateEvent(
            event_type="diff_complete",
            tenant_id="alice",
            negotiation_id="neg-alice-001",
            workflow_id="contract_redline",
            payload={"round_number": 1},
            emitted_at=datetime.now(timezone.utc),
            emitted_by="test",
        )
        self.sm.process_event(self._ctx(), diff_event)

        sm_events = self.audit.query(agent_name="state_manager")
        types = [e.event_type for e in sm_events]
        self.assertIn("pipeline_gated_paused", types)

    def test_negotiation_resumed_clears_paused_status(self):
        from acp.layer_b.core.types import EVENT_NEGOTIATION_RESUMED
        # Pause first
        self.orch.enter_degraded_mode(self._ctx(), "neg-alice-001", reason="test")
        row = self.sm.get_negotiation(self._ctx(), "neg-alice-001")
        self.assertEqual(row.automation_status, "Paused")

        # Resume via SM event
        resume_event = StateEvent(
            event_type=EVENT_NEGOTIATION_RESUMED,
            tenant_id="alice",
            negotiation_id="neg-alice-001",
            workflow_id="contract_redline",
            payload={},
            emitted_at=datetime.now(timezone.utc),
            emitted_by="test",
        )
        self.sm.process_event(self._ctx(), resume_event)

        row = self.sm.get_negotiation(self._ctx(), "neg-alice-001")
        self.assertEqual(row.automation_status, "Active")


class RetryExhaustionPipelineTests(unittest.TestCase):
    """Retry exhaustion: max_attempts reached → degraded mode → SM sets Paused."""

    def setUp(self):
        self.ledger, self.audit, self.sm, self.portfolio, self.orch = _build_wired_stack()
        self.received: list[StateEvent] = []
        self.orch.subscribe(self.received.append)
        _seed(self.sm, "alice", "neg-alice-001",
              NegotiationState.NEGOTIATING, _RECENT)

    def _ctx(self):
        return TenantContext(tenant_id="alice")

    def _seed_retry(self, attempt_count):
        row = EventRetryRow(
            retry_id=str(uuid.uuid4()),
            tenant_id="alice",
            negotiation_id="neg-alice-001",
            workflow_id="contract_redline",
            event_type="diff_complete",
            payload_json=json.dumps({"round_number": 1}),
            attempt_count=attempt_count,
            last_attempt_at=datetime.now(timezone.utc),
            last_error="synthetic downstream failure",
            status="pending",
        )
        self.ledger.upsert_retry_state(row)
        return row

    def test_exhausted_retry_emits_negotiation_paused(self):
        # max_retry_attempts=3 in SYNTHETIC_CONFIG
        self._seed_retry(attempt_count=3)
        self.orch.retry_failed_event(_PORTFOLIO_CTX)
        types = {e.event_type for e in self.received}
        self.assertIn(EVENT_NEGOTIATION_PAUSED, types)

    def test_exhausted_retry_emits_retry_exhausted(self):
        self._seed_retry(attempt_count=3)
        self.orch.retry_failed_event(_PORTFOLIO_CTX)
        types = {e.event_type for e in self.received}
        self.assertIn(EVENT_RETRY_EXHAUSTED, types)

    def test_sm_sets_paused_after_exhaustion(self):
        self._seed_retry(attempt_count=3)
        self.orch.retry_failed_event(_PORTFOLIO_CTX)
        row = self.sm.get_negotiation(self._ctx(), "neg-alice-001")
        self.assertEqual(row.automation_status, "Paused")

    def test_below_max_attempts_does_not_pause(self):
        self._seed_retry(attempt_count=2)  # < max_retry_attempts=3
        self.orch.retry_failed_event(_PORTFOLIO_CTX)
        types = {e.event_type for e in self.received}
        self.assertNotIn(EVENT_NEGOTIATION_PAUSED, types)
        row = self.sm.get_negotiation(self._ctx(), "neg-alice-001")
        self.assertNotEqual(row.automation_status, "Paused")

    def test_process_event_failure_creates_retry_then_sweep_exhausts(self):
        """Full cycle: process_event creates row; sweep exhausts it after max attempts."""
        # Create row at max_retry_attempts via process_event + manual increment
        fail_event = StateEvent(
            event_type=EVENT_NEGOTIATION_FAILED,
            tenant_id="alice",
            negotiation_id="neg-alice-001",
            workflow_id="contract_redline",
            payload={
                "failed_event_type": "analysis_complete",
                "failed_event_payload_json": "{}",
                "error": "network timeout",
            },
            emitted_at=datetime.now(timezone.utc),
            emitted_by="test_agent",
        )
        self.orch.process_event(self._ctx(), fail_event)

        # Verify retry row was created
        pending = self.ledger.list_pending_retries(tenant_id="alice")
        self.assertEqual(len(pending), 1)
        retry_id = pending[0].retry_id

        # Manually push attempt_count to max to test exhaustion on next sweep
        from acp.layer_b.core.types import EventRetryRow
        updated = EventRetryRow(
            retry_id=retry_id,
            tenant_id="alice",
            negotiation_id="neg-alice-001",
            workflow_id="contract_redline",
            event_type="analysis_complete",
            payload_json="{}",
            attempt_count=3,  # == max_retry_attempts
            last_attempt_at=datetime.now(timezone.utc),
            last_error="network timeout",
            status="pending",
        )
        self.ledger.upsert_retry_state(updated)

        self.orch.retry_failed_event(_PORTFOLIO_CTX)

        exhausted = self.ledger.get_retry_state(retry_id)
        self.assertEqual(exhausted.status, "exhausted")

        row = self.sm.get_negotiation(self._ctx(), "neg-alice-001")
        self.assertEqual(row.automation_status, "Paused")
