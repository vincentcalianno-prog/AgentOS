"""Tests for Agent 3 (State Manager).

Per Implementation Guide Section 7.1: synthetic fixtures only. No deployment-specific
counterparty names, no real clause text, no real email content.

Fixtures use made-up names:
    Counterparties: "Acme Industrial", "Beta Manufacturing", "Gamma Components", "Delta Systems"
    Tenant owners: "alice", "bob", "carol"
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from acp.layer_b.agents.state_manager import StateManager
from acp.layer_b.core.adapters.in_memory_audit import InMemoryAuditLog
from acp.layer_b.core.adapters.sqlite_ledger import SQLiteLedger
from acp.layer_b.core.tenancy import TenancyEnforcer
from acp.layer_b.core.types import (
    EVENT_INBOUND_REDLINE_RECEIVED,
    EVENT_OUTBOUND_CONTRACT_SENT,
    InvalidTransitionError,
    NegotiationNotFoundError,
    NegotiationRow,
    NegotiationState,
    ROLE_PORTFOLIO_AGGREGATOR,
    StateEvent,
    TenancyViolation,
    TenantContext,
    is_valid_transition,
)


def _make_row(negotiation_id: str, owner: str, **kwargs) -> NegotiationRow:
    """Synthetic row factory. No deployment-specific values."""
    defaults = dict(
        negotiation_id=negotiation_id,
        row_number=1,
        owner=owner,
        category="GenericCategoryA",
        priority="High",
        counterparty_description="Acme Industrial - synthetic widget assembly",
        whos_court=owner,
        status=NegotiationState.NOT_STARTED,
        contract_type="generic-agreement",
        round_number=0,
    )
    defaults.update(kwargs)
    return NegotiationRow(**defaults)


class StateMachineTests(unittest.TestCase):
    """Unit tests for the pure state machine logic."""

    def test_same_state_transition_is_valid(self):
        self.assertTrue(is_valid_transition(
            NegotiationState.NEGOTIATING, NegotiationState.NEGOTIATING
        ))

    def test_valid_forward_transitions(self):
        valid_pairs = [
            (NegotiationState.NOT_STARTED, NegotiationState.REQUESTED),
            (NegotiationState.REQUESTED, NegotiationState.CONTRACT_SENT),
            (NegotiationState.CONTRACT_SENT, NegotiationState.REDLINES_RECEIVED),
            (NegotiationState.REDLINES_RECEIVED, NegotiationState.NEGOTIATING),
            (NegotiationState.NEGOTIATING, NegotiationState.PENDING_SIGNATURE),
            (NegotiationState.PENDING_SIGNATURE, NegotiationState.EXECUTED_ACTIVE),
        ]
        for src, dst in valid_pairs:
            with self.subTest(src=src, dst=dst):
                self.assertTrue(is_valid_transition(src, dst))

    def test_terminal_states_have_no_outbound_transitions(self):
        # EXECUTED_ACTIVE and WILL_NOT_EXECUTE are terminal
        for terminal in (NegotiationState.EXECUTED_ACTIVE, NegotiationState.WILL_NOT_EXECUTE):
            for other in NegotiationState:
                if other == terminal:
                    continue  # same-state is always OK
                with self.subTest(terminal=terminal, attempted=other):
                    self.assertFalse(
                        is_valid_transition(terminal, other),
                        f"Should not transition from terminal {terminal} to {other}",
                    )

    def test_on_hold_can_resume_negotiation(self):
        self.assertTrue(is_valid_transition(
            NegotiationState.ON_HOLD, NegotiationState.NEGOTIATING
        ))

    def test_cannot_jump_from_not_started_to_executed(self):
        self.assertFalse(is_valid_transition(
            NegotiationState.NOT_STARTED, NegotiationState.EXECUTED_ACTIVE
        ))


class StateManagerBasicTests(unittest.TestCase):
    """Tests for the StateManager facade with synthetic data."""

    def setUp(self):
        self.ledger = SQLiteLedger()
        self.audit = InMemoryAuditLog()
        self.tenancy = TenancyEnforcer(self.audit)
        self.sm = StateManager(self.ledger, self.tenancy, self.audit)

        self.alice = TenantContext(tenant_id="alice")
        self.bob = TenantContext(tenant_id="bob")
        self.aggregator = TenantContext(
            tenant_id="aggregator",
            roles=frozenset({ROLE_PORTFOLIO_AGGREGATOR}),
        )

    def test_create_and_retrieve_negotiation(self):
        row = _make_row("neg-001", "alice")
        self.sm.create_negotiation(self.alice, row)

        retrieved = self.sm.get_negotiation(self.alice, "neg-001")
        self.assertEqual(retrieved.negotiation_id, "neg-001")
        self.assertEqual(retrieved.owner, "alice")
        self.assertEqual(retrieved.status, NegotiationState.NOT_STARTED)
        self.assertIsNotNone(retrieved.last_activity_date)

    def test_list_own_negotiations(self):
        for i in range(3):
            row = _make_row(f"neg-{i:03d}", "alice", row_number=i+1,
                            counterparty_description=f"Acme Industrial {i}")
            self.sm.create_negotiation(self.alice, row)

        rows = self.sm.list_negotiations(self.alice)
        self.assertEqual(len(rows), 3)

    def test_duplicate_creation_rejected(self):
        row = _make_row("neg-001", "alice")
        self.sm.create_negotiation(self.alice, row)
        with self.assertRaises(ValueError):
            self.sm.create_negotiation(self.alice, row)


class StateTransitionTests(unittest.TestCase):
    """Tests for state machine enforcement at the StateManager level."""

    def setUp(self):
        self.ledger = SQLiteLedger()
        self.audit = InMemoryAuditLog()
        self.tenancy = TenancyEnforcer(self.audit)
        self.sm = StateManager(self.ledger, self.tenancy, self.audit)
        self.alice = TenantContext(tenant_id="alice")

    def test_valid_transition_applied(self):
        self.sm.create_negotiation(self.alice, _make_row("neg-001", "alice"))
        self.sm.transition_state(
            self.alice, "neg-001", NegotiationState.REQUESTED, reason="test"
        )
        row = self.sm.get_negotiation(self.alice, "neg-001")
        self.assertEqual(row.status, NegotiationState.REQUESTED)

    def test_invalid_transition_rejected(self):
        self.sm.create_negotiation(self.alice, _make_row("neg-001", "alice"))
        # Cannot jump from NOT_STARTED directly to EXECUTED_ACTIVE
        with self.assertRaises(InvalidTransitionError):
            self.sm.transition_state(
                self.alice, "neg-001", NegotiationState.EXECUTED_ACTIVE
            )
        # Original state preserved
        row = self.sm.get_negotiation(self.alice, "neg-001")
        self.assertEqual(row.status, NegotiationState.NOT_STARTED)

    def test_full_lifecycle_progression(self):
        self.sm.create_negotiation(self.alice, _make_row("neg-001", "alice"))
        progression = [
            NegotiationState.REQUESTED,
            NegotiationState.CONTRACT_SENT,
            NegotiationState.REDLINES_RECEIVED,
            NegotiationState.NEGOTIATING,
            NegotiationState.PENDING_SIGNATURE,
            NegotiationState.EXECUTED_ACTIVE,
        ]
        for state in progression:
            self.sm.transition_state(self.alice, "neg-001", state)
        row = self.sm.get_negotiation(self.alice, "neg-001")
        self.assertEqual(row.status, NegotiationState.EXECUTED_ACTIVE)


class TenancyEnforcementTests(unittest.TestCase):
    """Tests for tenancy isolation. This is the critical security boundary."""

    def setUp(self):
        self.ledger = SQLiteLedger()
        self.audit = InMemoryAuditLog()
        self.tenancy = TenancyEnforcer(self.audit)
        self.sm = StateManager(self.ledger, self.tenancy, self.audit)

        self.alice = TenantContext(tenant_id="alice")
        self.bob = TenantContext(tenant_id="bob")
        self.aggregator = TenantContext(
            tenant_id="aggregator",
            roles=frozenset({ROLE_PORTFOLIO_AGGREGATOR}),
        )

    def test_cannot_write_to_other_tenant(self):
        """Bob cannot write a row owned by alice."""
        row = _make_row("neg-001", "alice")
        with self.assertRaises(TenancyViolation):
            self.sm.create_negotiation(self.bob, row)

    def test_cannot_transition_other_tenants_negotiation(self):
        self.sm.create_negotiation(self.alice, _make_row("neg-001", "alice"))
        with self.assertRaises(TenancyViolation):
            self.sm.transition_state(
                self.bob, "neg-001", NegotiationState.REQUESTED
            )

    def test_cannot_read_other_tenants_negotiation_without_role(self):
        self.sm.create_negotiation(self.alice, _make_row("neg-001", "alice"))
        with self.assertRaises(TenancyViolation):
            self.sm.get_negotiation(self.bob, "neg-001")

    def test_cannot_list_other_tenants_negotiations_without_role(self):
        self.sm.create_negotiation(self.alice, _make_row("neg-001", "alice"))
        with self.assertRaises(TenancyViolation):
            self.sm.list_negotiations(self.bob, target_tenant="alice")

    def test_aggregator_can_read_cross_tenant(self):
        self.sm.create_negotiation(self.alice, _make_row("neg-001", "alice"))
        self.sm.create_negotiation(self.bob, _make_row("neg-002", "bob"))

        # Aggregator reads across all tenants
        all_negotiations = self.sm.list_all_negotiations_cross_tenant(self.aggregator)
        self.assertEqual(set(all_negotiations.keys()), {"alice", "bob"})
        self.assertEqual(len(all_negotiations["alice"]), 1)
        self.assertEqual(len(all_negotiations["bob"]), 1)

    def test_non_aggregator_cannot_call_cross_tenant_read(self):
        with self.assertRaises(TenancyViolation):
            self.sm.list_all_negotiations_cross_tenant(self.alice)

    def test_tenancy_violations_are_audited(self):
        try:
            self.sm.create_negotiation(self.bob, _make_row("neg-001", "alice"))
        except TenancyViolation:
            pass

        violations = self.audit.query(agent_name="tenancy_enforcer")
        self.assertGreaterEqual(len(violations), 1)
        self.assertEqual(violations[0].severity, "violation")


class FieldUpdateTests(unittest.TestCase):
    """Tests for non-state field updates."""

    def setUp(self):
        self.ledger = SQLiteLedger()
        self.audit = InMemoryAuditLog()
        self.tenancy = TenancyEnforcer(self.audit)
        self.sm = StateManager(self.ledger, self.tenancy, self.audit)
        self.alice = TenantContext(tenant_id="alice")
        self.sm.create_negotiation(self.alice, _make_row("neg-001", "alice"))

    def test_update_arbitrary_field(self):
        self.sm.update_fields(
            self.alice, "neg-001",
            {"whos_court": "Legal", "priority": "Medium"},
        )
        row = self.sm.get_negotiation(self.alice, "neg-001")
        self.assertEqual(row.whos_court, "Legal")
        self.assertEqual(row.priority, "Medium")

    def test_cannot_update_status_via_update_fields(self):
        with self.assertRaises(ValueError):
            self.sm.update_fields(
                self.alice, "neg-001",
                {"status": NegotiationState.NEGOTIATING},
            )

    def test_cannot_update_identity_field(self):
        with self.assertRaises(ValueError):
            self.sm.update_fields(
                self.alice, "neg-001",
                {"negotiation_id": "neg-other"},
            )

    def test_unknown_field_rejected(self):
        with self.assertRaises(ValueError):
            self.sm.update_fields(
                self.alice, "neg-001",
                {"not_a_real_field": "value"},
            )


class EventProcessingTests(unittest.TestCase):
    """Tests for event-driven state changes."""

    def setUp(self):
        self.ledger = SQLiteLedger()
        self.audit = InMemoryAuditLog()
        self.tenancy = TenancyEnforcer(self.audit)
        self.sm = StateManager(self.ledger, self.tenancy, self.audit)
        self.alice = TenantContext(tenant_id="alice")
        self.emitted_events: list[StateEvent] = []
        self.sm.subscribe(lambda e: self.emitted_events.append(e))

    def test_outbound_contract_sent_event(self):
        # Get into REQUESTED state first (legitimate predecessor)
        self.sm.create_negotiation(self.alice, _make_row("neg-001", "alice"))
        self.sm.transition_state(
            self.alice, "neg-001", NegotiationState.REQUESTED,
        )

        event = StateEvent(
            event_type=EVENT_OUTBOUND_CONTRACT_SENT,
            tenant_id="alice",
            negotiation_id="neg-001",
            payload={"storage_path": "tenant-root/generic-agreement/acme/round_0/outbound_v1.docx"},
            emitted_at=datetime.now(timezone.utc),
            emitted_by="email_watcher",
        )
        self.sm.process_event(self.alice, event)

        row = self.sm.get_negotiation(self.alice, "neg-001")
        self.assertEqual(row.status, NegotiationState.CONTRACT_SENT)
        self.assertEqual(
            row.last_outbound_version_sent,
            "tenant-root/generic-agreement/acme/round_0/outbound_v1.docx",
        )

    def test_inbound_redline_increments_round_and_emits_extraction_event(self):
        # Pre-conditions: get the negotiation to CONTRACT_SENT
        self.sm.create_negotiation(self.alice, _make_row("neg-001", "alice"))
        self.sm.transition_state(self.alice, "neg-001", NegotiationState.REQUESTED)
        self.sm.transition_state(self.alice, "neg-001", NegotiationState.CONTRACT_SENT)

        event = StateEvent(
            event_type=EVENT_INBOUND_REDLINE_RECEIVED,
            tenant_id="alice",
            negotiation_id="neg-001",
            payload={
                "inbox_message_id": "msg-abc-123",
                "inbox_thread_id": "thread-xyz-789",
            },
            emitted_at=datetime.now(timezone.utc),
            emitted_by="email_watcher",
        )
        self.sm.process_event(self.alice, event)

        row = self.sm.get_negotiation(self.alice, "neg-001")
        self.assertEqual(row.status, NegotiationState.REDLINES_RECEIVED)
        self.assertEqual(row.round_number, 1)
        self.assertEqual(row.whos_court, "alice")  # back to owner

        # Check that document_extraction_required was emitted to subscribers
        extraction_events = [
            e for e in self.emitted_events
            if e.event_type == "document_extraction_required"
        ]
        self.assertEqual(len(extraction_events), 1)
        self.assertEqual(extraction_events[0].payload["inbox_message_id"], "msg-abc-123")

    def test_event_for_other_tenant_rejected(self):
        self.sm.create_negotiation(self.alice, _make_row("neg-001", "alice"))
        bob = TenantContext(tenant_id="bob")
        event = StateEvent(
            event_type=EVENT_OUTBOUND_CONTRACT_SENT,
            tenant_id="alice",
            negotiation_id="neg-001",
            payload={},
            emitted_at=datetime.now(timezone.utc),
            emitted_by="email_watcher",
        )
        with self.assertRaises(TenancyViolation):
            self.sm.process_event(bob, event)


class RoundIncrementTests(unittest.TestCase):
    def setUp(self):
        self.ledger = SQLiteLedger()
        self.audit = InMemoryAuditLog()
        self.tenancy = TenancyEnforcer(self.audit)
        self.sm = StateManager(self.ledger, self.tenancy, self.audit)
        self.alice = TenantContext(tenant_id="alice")

    def test_round_increments(self):
        self.sm.create_negotiation(self.alice, _make_row("neg-001", "alice"))
        for expected in range(1, 4):
            self.sm.increment_round(self.alice, "neg-001")
            row = self.sm.get_negotiation(self.alice, "neg-001")
            self.assertEqual(row.round_number, expected)


class AuditTrailTests(unittest.TestCase):
    def setUp(self):
        self.ledger = SQLiteLedger()
        self.audit = InMemoryAuditLog()
        self.tenancy = TenancyEnforcer(self.audit)
        self.sm = StateManager(self.ledger, self.tenancy, self.audit)
        self.alice = TenantContext(tenant_id="alice")

    def test_create_writes_audit_entry(self):
        self.sm.create_negotiation(self.alice, _make_row("neg-001", "alice"))
        events = self.audit.query(tenant_id="alice")
        creation_events = [e for e in events if e.event_type == "create_negotiation"]
        self.assertEqual(len(creation_events), 1)

    def test_state_transition_writes_audit_entry(self):
        self.sm.create_negotiation(self.alice, _make_row("neg-001", "alice"))
        self.sm.transition_state(self.alice, "neg-001", NegotiationState.REQUESTED, reason="test")
        events = self.audit.query(tenant_id="alice", agent_name="state_manager")
        transition_events = [e for e in events if e.event_type == "state_transition"]
        self.assertEqual(len(transition_events), 1)
        self.assertEqual(transition_events[0].payload["to_state"], "Requested")

    def test_invalid_transition_audited_as_warning(self):
        self.sm.create_negotiation(self.alice, _make_row("neg-001", "alice"))
        try:
            self.sm.transition_state(self.alice, "neg-001", NegotiationState.EXECUTED_ACTIVE)
        except InvalidTransitionError:
            pass
        events = self.audit.query(tenant_id="alice")
        rejected = [e for e in events if e.event_type == "invalid_transition_rejected"]
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0].severity, "warning")


if __name__ == "__main__":
    unittest.main(verbosity=2)
