"""Integration tests: Agent 1 (Email Watcher) → Agent 3 (State Manager).

Verifies the end-to-end ingestion pipeline using:
    - MockInboxAdapter (synthetic inbox)
    - Deterministic classify stub (no LLM)
    - Real StateManager with SQLiteLedger + InMemoryAuditLog

Per Implementation Guide Section 7.1: synthetic fixtures only.
    Suppliers: Acme Industrial, Beta Manufacturing, Gamma Components
    SCMs: alice, bob, carol
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from acp.layer_b.agents.email_watcher import (
    CLASSIFICATION_IRRELEVANT,
    CLASSIFICATION_NON_REDLINE_CONTRACT,
    CLASSIFICATION_REDLINE,
    EmailWatcher,
)
from acp.layer_b.agents.state_manager import StateManager
from acp.layer_b.core.adapters.in_memory_audit import InMemoryAuditLog
from acp.layer_b.core.adapters.sqlite_ledger import SQLiteLedger
from acp.layer_b.core.tenancy import TenancyEnforcer
from acp.layer_b.core.types import (
    EVENT_DOCUMENT_EXTRACTION_REQUIRED,
    EVENT_INBOUND_REDLINE_RECEIVED,
    NegotiationRow,
    NegotiationState,
    StateEvent,
    TenantContext,
)
from acp.layer_b.tests.fixtures.mock_inbox import (
    MockInboxAdapter,
    make_irrelevant_message,
    make_non_redline_message,
    make_redline_message,
)

_EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _build_pipeline(
    inbox_messages: list,
    classify_fn=None,
) -> tuple[EmailWatcher, StateManager, SQLiteLedger, InMemoryAuditLog, list[StateEvent]]:
    """Wire Agent 1 → Agent 3 and return handles for assertions."""
    ledger = SQLiteLedger(db_path=":memory:")
    audit = InMemoryAuditLog()
    tenancy = TenancyEnforcer(audit)
    state_manager = StateManager(ledger=ledger, tenancy=tenancy, audit=audit)

    # Capture all events emitted by State Manager downstream
    downstream_events: list[StateEvent] = []
    state_manager.subscribe(downstream_events.append)

    inbox = MockInboxAdapter(inbox_messages)

    if classify_fn is None:
        classify_fn = lambda s, b: CLASSIFICATION_IRRELEVANT

    watcher = EmailWatcher(
        inbox=inbox,
        classify=classify_fn,
        audit=audit,
        config={},
    )
    # Wire Agent 1 output → Agent 3 input
    watcher.subscribe(
        lambda event: state_manager.process_event(
            TenantContext(tenant_id=event.tenant_id), event
        )
    )

    return watcher, state_manager, ledger, audit, downstream_events


def _seed_negotiation(
    state_manager: StateManager,
    ledger: SQLiteLedger,
    tenant_id: str,
    negotiation_id: str,
    thread_id: str,
    initial_state: NegotiationState = NegotiationState.CONTRACT_SENT,
) -> NegotiationRow:
    """Create a negotiation in the ledger that Agent 1 can trigger events against."""
    ctx = TenantContext(tenant_id=tenant_id)
    row = NegotiationRow(
        negotiation_id=negotiation_id,
        row_number=1,
        owner=tenant_id,
        counterparty_description="Acme Industrial - synthetic widget assembly",
        contract_type="MEPA",
        status=initial_state,
        inbox_thread_id=thread_id,
        automation_status="Active",
    )
    return state_manager.create_negotiation(ctx, row)


class RedlineIngestionTests(unittest.TestCase):
    """A redline message flows through to a state transition and derived event."""

    def setUp(self):
        self.thread_id = "thread-acme-001"
        # negotiation_id == thread_id: test simplification. In production the
        # Workflow Orchestrator maintains a thread_id → negotiation_id index;
        # EmailWatcher emits event.negotiation_id = msg.thread_id and the
        # Orchestrator resolves it before forwarding to State Manager.
        self.negotiation_id = self.thread_id
        self.tenant_id = "alice"
        self.ctx = TenantContext(tenant_id=self.tenant_id)

        msg = make_redline_message(
            message_id="msg-r-01",
            thread_id=self.thread_id,
        )
        self.watcher, self.sm, self.ledger, self.audit, self.downstream = (
            _build_pipeline(
                inbox_messages=[msg],
                classify_fn=lambda s, b: CLASSIFICATION_REDLINE,
            )
        )
        _seed_negotiation(
            self.sm, self.ledger,
            tenant_id=self.tenant_id,
            negotiation_id=self.negotiation_id,
            thread_id=self.thread_id,
        )

    def test_redline_transitions_negotiation_to_redlines_received(self):
        self.watcher.poll(
            self.ctx, since=_EPOCH,
            active_thread_ids={self.thread_id},
        )
        row = self.sm.get_negotiation(self.ctx, self.negotiation_id)
        self.assertEqual(row.status, NegotiationState.REDLINES_RECEIVED)

    def test_redline_increments_round_number(self):
        self.watcher.poll(
            self.ctx, since=_EPOCH,
            active_thread_ids={self.thread_id},
        )
        row = self.sm.get_negotiation(self.ctx, self.negotiation_id)
        self.assertEqual(row.round_number, 1)

    def test_redline_sets_whos_court_to_owner(self):
        self.watcher.poll(
            self.ctx, since=_EPOCH,
            active_thread_ids={self.thread_id},
        )
        row = self.sm.get_negotiation(self.ctx, self.negotiation_id)
        self.assertEqual(row.whos_court, self.tenant_id)

    def test_redline_triggers_document_extraction_required_event(self):
        self.watcher.poll(
            self.ctx, since=_EPOCH,
            active_thread_ids={self.thread_id},
        )
        extraction_events = [
            e for e in self.downstream
            if e.event_type == EVENT_DOCUMENT_EXTRACTION_REQUIRED
        ]
        self.assertEqual(len(extraction_events), 1)

    def test_document_extraction_event_carries_message_id(self):
        self.watcher.poll(
            self.ctx, since=_EPOCH,
            active_thread_ids={self.thread_id},
        )
        evt = next(
            e for e in self.downstream
            if e.event_type == EVENT_DOCUMENT_EXTRACTION_REQUIRED
        )
        self.assertEqual(evt.payload["inbox_message_id"], "msg-r-01")
        self.assertEqual(evt.payload["inbox_thread_id"], self.thread_id)

    def test_message_is_marked_processed_after_pipeline(self):
        self.watcher.poll(
            self.ctx, since=_EPOCH,
            active_thread_ids={self.thread_id},
        )
        self.assertIn("msg-r-01", self.watcher._inbox.processed)


class NonRedlineIngestionTests(unittest.TestCase):
    """A non-redline contract message does not trigger a state transition."""

    def setUp(self):
        self.thread_id = "thread-beta-001"
        self.negotiation_id = self.thread_id  # test simplification; see RedlineIngestionTests
        self.tenant_id = "bob"
        self.ctx = TenantContext(tenant_id=self.tenant_id)

        msg = make_non_redline_message(
            message_id="msg-nr-01",
            thread_id=self.thread_id,
        )
        self.watcher, self.sm, self.ledger, self.audit, self.downstream = (
            _build_pipeline(
                inbox_messages=[msg],
                classify_fn=lambda s, b: CLASSIFICATION_NON_REDLINE_CONTRACT,
            )
        )
        _seed_negotiation(
            self.sm, self.ledger,
            tenant_id=self.tenant_id,
            negotiation_id=self.negotiation_id,
            thread_id=self.thread_id,
            initial_state=NegotiationState.NEGOTIATING,
        )

    def test_non_redline_does_not_change_state(self):
        self.watcher.poll(
            self.ctx, since=_EPOCH,
            active_thread_ids={self.thread_id},
        )
        row = self.sm.get_negotiation(self.ctx, self.negotiation_id)
        self.assertEqual(row.status, NegotiationState.NEGOTIATING)

    def test_non_redline_does_not_increment_round(self):
        self.watcher.poll(
            self.ctx, since=_EPOCH,
            active_thread_ids={self.thread_id},
        )
        row = self.sm.get_negotiation(self.ctx, self.negotiation_id)
        self.assertEqual(row.round_number, 0)

    def test_non_redline_emits_no_downstream_events(self):
        self.watcher.poll(
            self.ctx, since=_EPOCH,
            active_thread_ids={self.thread_id},
        )
        self.assertEqual(len(self.downstream), 0)


class MultiTenantIsolationTests(unittest.TestCase):
    """Events from one tenant's inbox do not affect another tenant's negotiations."""

    def test_alice_redline_does_not_affect_bobs_negotiation(self):
        # Both alice and bob have negotiations in the same pipeline
        alice_ctx = TenantContext(tenant_id="alice")
        bob_ctx = TenantContext(tenant_id="bob")

        # Alice gets a redline on her thread
        alice_msg = make_redline_message(
            message_id="msg-alice-01",
            thread_id="thread-alice-acme",
        )
        watcher, sm, ledger, audit, downstream = _build_pipeline(
            inbox_messages=[alice_msg],
            classify_fn=lambda s, b: CLASSIFICATION_REDLINE,
        )

        # Seed alice's negotiation — negotiation_id == thread_id (test simplification)
        _seed_negotiation(
            sm, ledger,
            tenant_id="alice",
            negotiation_id="thread-alice-acme",
            thread_id="thread-alice-acme",
        )
        # Seed bob's negotiation (different thread, not active in this poll)
        _seed_negotiation(
            sm, ledger,
            tenant_id="bob",
            negotiation_id="thread-bob-beta",
            thread_id="thread-bob-beta",
        )

        # Poll only with alice's thread active
        watcher.poll(
            alice_ctx, since=_EPOCH,
            active_thread_ids={"thread-alice-acme"},
        )

        # Alice's negotiation advanced
        alice_row = sm.get_negotiation(alice_ctx, "thread-alice-acme")
        self.assertEqual(alice_row.status, NegotiationState.REDLINES_RECEIVED)

        # Bob's negotiation is unchanged
        bob_row = sm.get_negotiation(bob_ctx, "thread-bob-beta")
        self.assertEqual(bob_row.status, NegotiationState.CONTRACT_SENT)


class AuditCoverageTests(unittest.TestCase):
    """The audit log contains entries from both agents across the pipeline."""

    def test_both_agents_write_to_audit_log(self):
        thread_id = "thread-acme-001"
        tenant_id = "alice"
        ctx = TenantContext(tenant_id=tenant_id)

        msg = make_redline_message(thread_id=thread_id)
        watcher, sm, ledger, audit, _ = _build_pipeline(
            inbox_messages=[msg],
            classify_fn=lambda s, b: CLASSIFICATION_REDLINE,
        )
        _seed_negotiation(sm, ledger, tenant_id, thread_id, thread_id)
        watcher.poll(ctx, since=_EPOCH, active_thread_ids={thread_id})

        watcher_events = audit.query(agent_name="email_watcher")
        state_mgr_events = audit.query(agent_name="state_manager")

        self.assertTrue(len(watcher_events) > 0, "email_watcher produced no audit events")
        self.assertTrue(len(state_mgr_events) > 0, "state_manager produced no audit events")
