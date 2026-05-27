"""Unit tests: Agent 8 (Workflow Orchestrator).

Uses SQLiteLedger(:memory:), InMemoryAuditLog, and a real PortfolioAggregatorAgent
backed by a ContractRedlineWorkItemSource. All tests are deterministic; no mocks.

Six test classes:
    RouteNotificationTests     — route_notification() matching rules
    ScanSLAViolationsTests     — scan_sla_violations() breach detection
    RetryFailedEventTests      — retry_failed_event() re-emit and exhaustion
    ResolveInboxEventTests     — resolve_inbox_event() policy variants
    EnterDegradedModeTests     — enter_degraded_mode() event emission
    ProcessEventTests          — process_event() retry state lifecycle

Per Implementation Guide Section 7.1: synthetic counterparties only.
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
from acp.layer_b.agents.workflow_orchestrator_config import (
    NotificationRoute,
    OperationalConfig,
    OrganizationConfig,
    WorkflowOrchestratorConfig,
)
from acp.layer_b.core.adapters.in_memory_audit import InMemoryAuditLog
from acp.layer_b.core.adapters.sqlite_ledger import SQLiteLedger
from acp.layer_b.core.tenancy import TenancyEnforcer
from acp.layer_b.core.types import (
    EVENT_NEGOTIATION_FAILED,
    EVENT_NEGOTIATION_PAUSED,
    EVENT_NOTIFICATION_REQUIRED,
    EVENT_RETRY_EXHAUSTED,
    EVENT_SLA_BREACH_DETECTED,
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
# Shared test helpers
# ---------------------------------------------------------------

def _build_stack(config=SYNTHETIC_CONFIG):
    """Return (ledger, audit, sm, portfolio, orchestrator) with shared ledger."""
    ledger = SQLiteLedger(db_path=":memory:")
    audit = InMemoryAuditLog()
    tenancy = TenancyEnforcer(audit)
    sm = StateManager(ledger=ledger, tenancy=tenancy, audit=audit)
    source = ContractRedlineWorkItemSource(ledger)
    portfolio = PortfolioAggregatorAgent(sources=[source], audit=audit)
    orchestrator = WorkflowOrchestratorAgent(
        config=config, ledger=ledger, audit=audit, portfolio=portfolio
    )
    return ledger, audit, sm, portfolio, orchestrator


def _seed(sm, tenant_id, negotiation_id, status, last_activity_date,
          inbox_thread_id=None, row_number=1):
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
        automation_status="Active",
        inbox_thread_id=inbox_thread_id,
    )
    sm.create_negotiation(ctx, row)


def _make_event(event_type, tenant_id, negotiation_id, workflow_id="contract_redline",
                payload=None):
    return StateEvent(
        event_type=event_type,
        tenant_id=tenant_id,
        negotiation_id=negotiation_id,
        workflow_id=workflow_id,
        payload=payload or {},
        emitted_at=datetime.now(timezone.utc),
        emitted_by="test",
    )


def _make_retry_row(tenant_id, negotiation_id, attempt_count=1,
                    event_type="diff_complete", status="pending", error="test error"):
    return EventRetryRow(
        retry_id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        negotiation_id=negotiation_id,
        workflow_id="contract_redline",
        event_type=event_type,
        payload_json=json.dumps({"round_number": 1}),
        attempt_count=attempt_count,
        last_attempt_at=datetime.now(timezone.utc),
        last_error=error,
        status=status,
    )


# ---------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------

class RouteNotificationTests(unittest.TestCase):
    """route_notification() fan-out matching rules."""

    def setUp(self):
        self.ledger, self.audit, self.sm, self.portfolio, self.orch = _build_stack()
        self.received: list[StateEvent] = []
        self.orch.subscribe(self.received.append)

    def test_matching_route_emits_notification(self):
        event = _make_event("sla_breach_detected", "alice", "neg-001")
        notifications = self.orch.route_notification(event)
        self.assertGreater(len(notifications), 0)
        self.assertTrue(all(n.event_type == EVENT_NOTIFICATION_REQUIRED for n in notifications))

    def test_all_matching_routes_fire(self):
        # SYNTHETIC_CONFIG has 2 routes for sla_breach_detected
        # (alice — any workflow, vincent — contract_redline only)
        event = _make_event("sla_breach_detected", "alice", "neg-001",
                            workflow_id="contract_redline")
        notifications = self.orch.route_notification(event)
        self.assertEqual(len(notifications), 2)

    def test_workflow_id_filter_excludes_non_matching(self):
        # "rfq_workflow" should NOT match vincent's route (workflow_id="contract_redline")
        event = _make_event("sla_breach_detected", "alice", "neg-001",
                            workflow_id="rfq_workflow")
        notifications = self.orch.route_notification(event)
        recipient_ids = [n.payload["recipient_id"] for n in notifications]
        self.assertIn("alice", recipient_ids)       # alice has no workflow filter
        self.assertNotIn("vincent", recipient_ids)  # vincent scoped to contract_redline

    def test_no_matching_routes_returns_empty(self):
        event = _make_event("unknown_event_xyz", "alice", "neg-001")
        notifications = self.orch.route_notification(event)
        self.assertEqual(notifications, [])

    def test_notification_payload_carries_recipient_and_channel(self):
        event = _make_event("sla_breach_detected", "alice", "neg-001",
                            workflow_id="rfq_workflow")
        notifications = self.orch.route_notification(event)
        n = notifications[0]
        self.assertIn("recipient_id", n.payload)
        self.assertIn("channel_preference", n.payload)
        self.assertIn("source_event_type", n.payload)

    def test_notifications_are_emitted_to_subscribers(self):
        event = _make_event("sla_breach_detected", "alice", "neg-001",
                            workflow_id="contract_redline")
        self.orch.route_notification(event)
        emitted_types = [e.event_type for e in self.received]
        self.assertTrue(all(t == EVENT_NOTIFICATION_REQUIRED for t in emitted_types))
        self.assertEqual(len(self.received), 2)


class ScanSLAViolationsTests(unittest.TestCase):
    """scan_sla_violations() detects breaches and routes notifications."""

    def setUp(self):
        self.ledger, self.audit, self.sm, self.portfolio, self.orch = _build_stack()
        self.received: list[StateEvent] = []
        self.orch.subscribe(self.received.append)

        # Seed one stale NEGOTIATING row (100d old > 10d threshold)
        # and one recent NEGOTIATING row (not stalled)
        _seed(self.sm, "alice", "neg-stale-001",
              NegotiationState.NEGOTIATING, _OLD, row_number=1)
        _seed(self.sm, "alice", "neg-recent-001",
              NegotiationState.NEGOTIATING, _RECENT, row_number=2)

    def test_stale_negotiating_row_triggers_violation(self):
        notifications = self.orch.scan_sla_violations(_PORTFOLIO_CTX)
        stale_notifs = [
            n for n in notifications
            if n.negotiation_id == "neg-stale-001"
        ]
        self.assertGreater(len(stale_notifs), 0)

    def test_recent_row_does_not_trigger_violation(self):
        notifications = self.orch.scan_sla_violations(_PORTFOLIO_CTX)
        recent_notifs = [
            n for n in notifications
            if n.negotiation_id == "neg-recent-001"
        ]
        self.assertEqual(len(recent_notifs), 0)

    def test_returns_notification_required_events(self):
        notifications = self.orch.scan_sla_violations(_PORTFOLIO_CTX)
        self.assertTrue(all(n.event_type == EVENT_NOTIFICATION_REQUIRED for n in notifications))

    def test_audit_records_violation_detection(self):
        self.orch.scan_sla_violations(_PORTFOLIO_CTX)
        events = self.audit.query(agent_name="workflow_orchestrator")
        types = [e.event_type for e in events]
        self.assertIn("sla_violations_detected", types)

    def test_no_rows_produces_no_violations(self):
        # Fresh stack — no negotiations seeded
        _, _, _, _, orch = _build_stack()
        notifications = orch.scan_sla_violations(_PORTFOLIO_CTX)
        self.assertEqual(notifications, [])

    def test_wrong_status_rows_not_counted(self):
        # PENDING_SIGNATURE threshold is 5d; seed a stale NEGOTIATING row
        # and verify PENDING_SIGNATURE threshold produces 0 (no rows in that status)
        notifications = self.orch.scan_sla_violations(_PORTFOLIO_CTX)
        pending_sig_notifs = [
            n for n in notifications
            if n.payload.get("source_payload", {}).get("status")
               == NegotiationState.PENDING_SIGNATURE.value
        ]
        self.assertEqual(len(pending_sig_notifs), 0)


class RetryFailedEventTests(unittest.TestCase):
    """retry_failed_event() re-emits pending rows and exhausts after max attempts."""

    def setUp(self):
        self.ledger, self.audit, self.sm, self.portfolio, self.orch = _build_stack()
        self.received: list[StateEvent] = []
        self.orch.subscribe(self.received.append)
        # Seed the negotiation so degraded mode can find it
        _seed(self.sm, "alice", "neg-alice-001",
              NegotiationState.NEGOTIATING, _RECENT)

    def test_pending_row_is_re_emitted(self):
        row = _make_retry_row("alice", "neg-alice-001", attempt_count=1)
        self.ledger.upsert_retry_state(row)

        self.orch.retry_failed_event(_PORTFOLIO_CTX)

        emitted_types = [e.event_type for e in self.received]
        self.assertIn("diff_complete", emitted_types)

    def test_reconstructed_event_carries_retry_id(self):
        row = _make_retry_row("alice", "neg-alice-001", attempt_count=1)
        self.ledger.upsert_retry_state(row)

        self.orch.retry_failed_event(_PORTFOLIO_CTX)

        re_emitted = [e for e in self.received if e.event_type == "diff_complete"]
        self.assertGreater(len(re_emitted), 0)
        self.assertIn("retry_id", re_emitted[0].payload)

    def test_exhausted_row_triggers_degraded_mode(self):
        row = _make_retry_row("alice", "neg-alice-001",
                              attempt_count=3,  # == max_retry_attempts
                              status="pending")
        self.ledger.upsert_retry_state(row)

        self.orch.retry_failed_event(_PORTFOLIO_CTX)

        # Should emit EVENT_NEGOTIATION_PAUSED and EVENT_RETRY_EXHAUSTED
        emitted_types = {e.event_type for e in self.received}
        self.assertIn(EVENT_NEGOTIATION_PAUSED, emitted_types)
        self.assertIn(EVENT_RETRY_EXHAUSTED, emitted_types)

    def test_exhausted_row_is_marked_exhausted_in_ledger(self):
        row = _make_retry_row("alice", "neg-alice-001",
                              attempt_count=3, status="pending")
        self.ledger.upsert_retry_state(row)

        self.orch.retry_failed_event(_PORTFOLIO_CTX)

        updated = self.ledger.get_retry_state(row.retry_id)
        self.assertEqual(updated.status, "exhausted")

    def test_pending_row_is_marked_in_progress_after_re_emit(self):
        row = _make_retry_row("alice", "neg-alice-001", attempt_count=1)
        self.ledger.upsert_retry_state(row)

        self.orch.retry_failed_event(_PORTFOLIO_CTX)

        updated = self.ledger.get_retry_state(row.retry_id)
        self.assertEqual(updated.status, "in_progress")

    def test_no_pending_retries_emits_nothing(self):
        self.orch.retry_failed_event(_PORTFOLIO_CTX)
        self.assertEqual(self.received, [])

    def test_audit_records_event_retried(self):
        row = _make_retry_row("alice", "neg-alice-001", attempt_count=1)
        self.ledger.upsert_retry_state(row)

        self.orch.retry_failed_event(_PORTFOLIO_CTX)

        events = self.audit.query(agent_name="workflow_orchestrator")
        types = [e.event_type for e in events]
        self.assertIn("event_retried", types)


class ResolveInboxEventTests(unittest.TestCase):
    """resolve_inbox_event() maps inbox threads to negotiations."""

    def setUp(self):
        self.ledger, self.audit, self.sm, self.portfolio, self.orch = _build_stack()
        # Seed a row with a known inbox_thread_id
        _seed(self.sm, "alice", "neg-alice-001",
              NegotiationState.NEGOTIATING, _RECENT,
              inbox_thread_id="thread-abc-123")

    def _inbox_event(self, thread_id):
        return _make_event(
            "inbound_non_redline", "alice", "neg-alice-001",
            payload={"inbox_thread_id": thread_id},
        )

    def test_known_thread_resolves_to_negotiation_id(self):
        result = self.orch.resolve_inbox_event(self._inbox_event("thread-abc-123"))
        self.assertEqual(result, "neg-alice-001")

    def test_unknown_thread_notify_for_triage_returns_none(self):
        result = self.orch.resolve_inbox_event(self._inbox_event("thread-unknown"))
        self.assertIsNone(result)

    def test_unknown_thread_triage_emits_notification(self):
        received: list[StateEvent] = []
        self.orch.subscribe(received.append)
        self.orch.resolve_inbox_event(self._inbox_event("thread-unknown"))
        emitted_types = [e.event_type for e in received]
        self.assertIn(EVENT_NOTIFICATION_REQUIRED, emitted_types)

    def test_missing_thread_id_returns_none(self):
        event = _make_event("inbound_non_redline", "alice", "neg-alice-001", payload={})
        result = self.orch.resolve_inbox_event(event)
        self.assertIsNone(result)

    def test_drop_silently_policy_does_not_emit(self):
        from acp.layer_b.agents.workflow_orchestrator_config import (
            CredentialsConfig, ExtensionsConfig, PlaybookConfig,
        )
        config = WorkflowOrchestratorConfig(
            credentials=CredentialsConfig(),
            operational=OperationalConfig(
                sla_thresholds={}, max_retry_attempts=3
            ),
            playbook=PlaybookConfig(),
            organization=OrganizationConfig(
                notification_routes=(),
                lookup_failure_policy="drop_silently",
            ),
            extensions=ExtensionsConfig(),
        )
        ledger, audit, sm, portfolio, orch = _build_stack(config=config)
        _seed(sm, "alice", "neg-drop-001",
              NegotiationState.NEGOTIATING, _RECENT,
              inbox_thread_id="thread-known")

        received: list[StateEvent] = []
        orch.subscribe(received.append)
        result = orch.resolve_inbox_event(
            _make_event("inbound_non_redline", "alice", "neg-drop-001",
                        payload={"inbox_thread_id": "thread-not-found"})
        )
        self.assertIsNone(result)
        self.assertEqual(received, [])

    def test_auto_create_policy_raises_not_implemented(self):
        from acp.layer_b.agents.workflow_orchestrator_config import (
            CredentialsConfig, ExtensionsConfig, PlaybookConfig,
        )
        config = WorkflowOrchestratorConfig(
            credentials=CredentialsConfig(),
            operational=OperationalConfig(
                sla_thresholds={}, max_retry_attempts=3
            ),
            playbook=PlaybookConfig(),
            organization=OrganizationConfig(
                notification_routes=(),
                lookup_failure_policy="auto_create_negotiation",
            ),
            extensions=ExtensionsConfig(),
        )
        _, _, _, _, orch = _build_stack(config=config)
        with self.assertRaises(NotImplementedError):
            orch.resolve_inbox_event(
                _make_event("inbound_non_redline", "alice", "neg-001",
                            payload={"inbox_thread_id": "thread-not-found"})
            )


class EnterDegradedModeTests(unittest.TestCase):
    """enter_degraded_mode() pauses automation and routes notifications."""

    def setUp(self):
        self.ledger, self.audit, self.sm, self.portfolio, self.orch = _build_stack()
        self.received: list[StateEvent] = []
        self.orch.subscribe(self.received.append)
        _seed(self.sm, "alice", "neg-alice-001",
              NegotiationState.NEGOTIATING, _RECENT)

    def _ctx(self):
        return TenantContext(tenant_id="alice")

    def test_emits_negotiation_paused(self):
        self.orch.enter_degraded_mode(self._ctx(), "neg-alice-001", reason="test")
        types = [e.event_type for e in self.received]
        self.assertIn(EVENT_NEGOTIATION_PAUSED, types)

    def test_paused_event_carries_reason(self):
        self.orch.enter_degraded_mode(self._ctx(), "neg-alice-001", reason="retry exhausted")
        paused = [e for e in self.received if e.event_type == EVENT_NEGOTIATION_PAUSED]
        self.assertGreater(len(paused), 0)
        self.assertEqual(paused[0].payload.get("reason"), "retry exhausted")

    def test_paused_event_uses_platform_workflow_id(self):
        self.orch.enter_degraded_mode(self._ctx(), "neg-alice-001", reason="test")
        paused = [e for e in self.received if e.event_type == EVENT_NEGOTIATION_PAUSED]
        self.assertEqual(paused[0].workflow_id, "platform")

    def test_notification_routed_for_configured_route(self):
        # SYNTHETIC_CONFIG has a route for event_pattern="negotiation_paused"
        self.orch.enter_degraded_mode(self._ctx(), "neg-alice-001", reason="test")
        notifs = [e for e in self.received if e.event_type == EVENT_NOTIFICATION_REQUIRED]
        self.assertGreater(len(notifs), 0)

    def test_audit_records_degraded_mode_entered(self):
        self.orch.enter_degraded_mode(self._ctx(), "neg-alice-001", reason="test")
        events = self.audit.query(agent_name="workflow_orchestrator")
        types = [e.event_type for e in events]
        self.assertIn("degraded_mode_entered", types)

    def test_audit_event_uses_warning_severity(self):
        self.orch.enter_degraded_mode(self._ctx(), "neg-alice-001", reason="test")
        events = self.audit.query(agent_name="workflow_orchestrator")
        degraded = [e for e in events if e.event_type == "degraded_mode_entered"]
        self.assertGreater(len(degraded), 0)
        self.assertEqual(degraded[0].severity, "warning")


class ProcessEventTests(unittest.TestCase):
    """process_event() retry state lifecycle."""

    def setUp(self):
        self.ledger, self.audit, self.sm, self.portfolio, self.orch = _build_stack()
        self.received: list[StateEvent] = []
        self.orch.subscribe(self.received.append)
        _seed(self.sm, "alice", "neg-alice-001",
              NegotiationState.NEGOTIATING, _RECENT)

    def _ctx(self):
        return TenantContext(tenant_id="alice")

    def _fail_event(self, retry_id=None):
        payload = {
            "failed_event_type": "diff_complete",
            "failed_event_payload_json": json.dumps({"round_number": 1}),
            "error": "synthetic downstream failure",
        }
        if retry_id is not None:
            payload["retry_id"] = retry_id
        return _make_event(
            EVENT_NEGOTIATION_FAILED, "alice", "neg-alice-001",
            payload=payload,
        )

    def test_first_failure_creates_retry_row(self):
        self.orch.process_event(self._ctx(), self._fail_event())
        pending = self.ledger.list_pending_retries(tenant_id="alice")
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].attempt_count, 1)
        self.assertEqual(pending[0].status, "pending")

    def test_retry_row_carries_correct_event_type(self):
        self.orch.process_event(self._ctx(), self._fail_event())
        pending = self.ledger.list_pending_retries(tenant_id="alice")
        self.assertEqual(pending[0].event_type, "diff_complete")

    def test_retry_row_carries_payload_json(self):
        self.orch.process_event(self._ctx(), self._fail_event())
        pending = self.ledger.list_pending_retries(tenant_id="alice")
        payload = json.loads(pending[0].payload_json)
        self.assertEqual(payload.get("round_number"), 1)

    def test_known_retry_id_increments_attempt_count(self):
        # First failure creates the row
        self.orch.process_event(self._ctx(), self._fail_event())
        row = self.ledger.list_pending_retries(tenant_id="alice")[0]
        retry_id = row.retry_id

        # Second failure with the same retry_id increments count
        self.orch.process_event(self._ctx(), self._fail_event(retry_id=retry_id))
        updated = self.ledger.get_retry_state(retry_id)
        self.assertEqual(updated.attempt_count, 2)

    def test_first_failure_routes_notification(self):
        self.orch.process_event(self._ctx(), self._fail_event())
        types = [e.event_type for e in self.received]
        self.assertIn(EVENT_NOTIFICATION_REQUIRED, types)

    def test_unknown_event_type_is_audited_as_warning(self):
        unknown = _make_event("some_unknown_event", "alice", "neg-alice-001")
        self.orch.process_event(self._ctx(), unknown)
        events = self.audit.query(agent_name="workflow_orchestrator")
        warnings = [e for e in events if e.event_type == "unhandled_event_type"]
        self.assertGreater(len(warnings), 0)

    def test_retry_required_event_creates_retry_row(self):
        from acp.layer_b.core.types import EVENT_RETRY_REQUIRED
        event = _make_event(
            EVENT_RETRY_REQUIRED, "alice", "neg-alice-001",
            payload={
                "failed_event_type": "analysis_complete",
                "failed_event_payload_json": "{}",
                "error": "transient timeout",
            },
        )
        self.orch.process_event(self._ctx(), event)
        pending = self.ledger.list_pending_retries(tenant_id="alice")
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].event_type, "analysis_complete")

    def test_audit_uses_platform_workflow_id(self):
        self.orch.process_event(self._ctx(), self._fail_event())
        events = self.audit.query(agent_name="workflow_orchestrator")
        self.assertTrue(all(e.workflow_id == "platform" for e in events))
