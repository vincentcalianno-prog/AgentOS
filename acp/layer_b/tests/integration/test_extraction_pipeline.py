"""Integration tests: Agent 2 (Document Extraction) pipeline.

Two pipeline scopes tested:
  1. Agent 2 alone: EVENT_DOCUMENT_EXTRACTION_REQUIRED → file stored → EVENT_DOCUMENT_EXTRACTED
     → State Manager updates last_counterparty_version and emits EVENT_ROUND_READY_FOR_ANALYSIS.
  2. Full chain: Agent 1 → State Manager → Agent 2 → State Manager (end-to-end from inbox
     message to tracker updated).

Per Implementation Guide Section 7.1: synthetic fixtures only.
    Suppliers: Acme Industrial, Beta Manufacturing, Gamma Components
    SCMs: alice, bob, carol
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from acp.layer_b.agents.document_extraction import DocumentExtractor
from acp.layer_b.agents.email_watcher import CLASSIFICATION_REDLINE, EmailWatcher
from acp.layer_b.agents.state_manager import StateManager
from acp.layer_b.core.adapters.in_memory_audit import InMemoryAuditLog
from acp.layer_b.core.adapters.sqlite_ledger import SQLiteLedger
from acp.layer_b.core.tenancy import TenancyEnforcer
from acp.layer_b.core.types import (
    EVENT_ROUND_READY_FOR_ANALYSIS,
    NegotiationRow,
    NegotiationState,
    StateEvent,
    TenantContext,
)
from acp.layer_b.tests.fixtures.mock_inbox import MockInboxAdapter, make_redline_message
from acp.layer_b.tests.fixtures.mock_storage import MockStorageAdapter

_EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)
_SYNTHETIC_CONTENT = b"SYNTHETIC CONTRACT DOCUMENT BYTES - ACME INDUSTRIAL"


def _build_sm(ledger, audit):
    tenancy = TenancyEnforcer(audit)
    return StateManager(ledger=ledger, tenancy=tenancy, audit=audit)


def _seed_negotiation(
    sm: StateManager,
    ledger: SQLiteLedger,
    tenant_id: str,
    negotiation_id: str,
    thread_id: str,
    contract_type: str = "generic-agreement",
    counterparty_ref: str = "acme-industrial",
    initial_state: NegotiationState = NegotiationState.CONTRACT_SENT,
) -> NegotiationRow:
    ctx = TenantContext(tenant_id=tenant_id)
    row = NegotiationRow(
        negotiation_id=negotiation_id,
        row_number=1,
        owner=tenant_id,
        counterparty_description="Acme Industrial - synthetic widget assembly",
        contract_type=contract_type,
        counterparty_profile_ref=counterparty_ref,
        status=initial_state,
        inbox_thread_id=thread_id,
        automation_status="Active",
    )
    return sm.create_negotiation(ctx, row)


class ExtractionEventToStateManagerTests(unittest.TestCase):
    """Agent 2 → State Manager: document extracted updates tracker and triggers analysis."""

    def setUp(self):
        self.ledger = SQLiteLedger(db_path=":memory:")
        self.audit = InMemoryAuditLog()
        self.sm = _build_sm(self.ledger, self.audit)

        self.downstream: list[StateEvent] = []
        self.sm.subscribe(self.downstream.append)

        self.inbox = MockInboxAdapter()
        self.inbox.add_attachment("att-001", _SYNTHETIC_CONTENT)
        self.storage = MockStorageAdapter()

        self.extractor = DocumentExtractor(
            inbox=self.inbox,
            storage=self.storage,
            audit=self.audit,
            config={"storage_root": "tenant-root"},
        )
        # Wire Agent 2 → State Manager
        self.extractor.subscribe(
            lambda event: self.sm.process_event(
                TenantContext(tenant_id=event.tenant_id), event
            )
        )

        self.thread_id = "thread-acme-001"
        self.negotiation_id = self.thread_id
        self.tenant_id = "alice"
        self.ctx = TenantContext(tenant_id=self.tenant_id)

        # Seed negotiation already in REDLINES_RECEIVED (as if Agent 1 already ran)
        _seed_negotiation(
            self.sm, self.ledger,
            tenant_id=self.tenant_id,
            negotiation_id=self.negotiation_id,
            thread_id=self.thread_id,
            initial_state=NegotiationState.REDLINES_RECEIVED,
        )

    def _make_extraction_event(self) -> StateEvent:
        from acp.layer_b.core.types import EVENT_DOCUMENT_EXTRACTION_REQUIRED
        return StateEvent(
            event_type=EVENT_DOCUMENT_EXTRACTION_REQUIRED,
            tenant_id=self.tenant_id,
            negotiation_id=self.negotiation_id,
            payload={
                "inbox_message_id": "msg-001",
                "inbox_thread_id": self.thread_id,
                "attachment_ids": ["att-001"],
                "round_number": 1,
                "contract_type": "generic-agreement",
                "counterparty_ref": "acme-industrial",
            },
            emitted_at=_EPOCH,
            emitted_by="state_manager",
        )

    def test_last_counterparty_version_is_updated(self):
        self.extractor.process_event(self.ctx, self._make_extraction_event())
        row = self.sm.get_negotiation(self.ctx, self.negotiation_id)
        self.assertIsNotNone(row.last_counterparty_version)

    def test_storage_folder_path_is_updated(self):
        self.extractor.process_event(self.ctx, self._make_extraction_event())
        row = self.sm.get_negotiation(self.ctx, self.negotiation_id)
        self.assertIsNotNone(row.storage_folder_path)

    def test_storage_folder_path_is_prefix_of_version_path(self):
        self.extractor.process_event(self.ctx, self._make_extraction_event())
        row = self.sm.get_negotiation(self.ctx, self.negotiation_id)
        self.assertTrue(row.last_counterparty_version.startswith(row.storage_folder_path))

    def test_round_ready_for_analysis_is_emitted(self):
        self.extractor.process_event(self.ctx, self._make_extraction_event())
        analysis_events = [
            e for e in self.downstream
            if e.event_type == EVENT_ROUND_READY_FOR_ANALYSIS
        ]
        self.assertEqual(len(analysis_events), 1)

    def test_round_ready_event_carries_storage_path(self):
        self.extractor.process_event(self.ctx, self._make_extraction_event())
        evt = next(e for e in self.downstream if e.event_type == EVENT_ROUND_READY_FOR_ANALYSIS)
        self.assertIsNotNone(evt.payload.get("counterparty_document_path"))

    def test_round_ready_event_carries_round_number(self):
        self.extractor.process_event(self.ctx, self._make_extraction_event())
        evt = next(e for e in self.downstream if e.event_type == EVENT_ROUND_READY_FOR_ANALYSIS)
        self.assertEqual(evt.payload["round_number"], 1)

    def test_file_is_persisted_to_storage(self):
        self.extractor.process_event(self.ctx, self._make_extraction_event())
        self.assertEqual(len(self.storage.stored_paths), 1)

    def test_stored_content_is_retrievable_and_correct(self):
        self.extractor.process_event(self.ctx, self._make_extraction_event())
        path = next(iter(self.storage.stored_paths))
        self.assertEqual(self.storage.retrieve(path), _SYNTHETIC_CONTENT)


class FullChainTests(unittest.TestCase):
    """Agent 1 → State Manager → Agent 2 → State Manager: inbox to tracker updated."""

    def setUp(self):
        self.ledger = SQLiteLedger(db_path=":memory:")
        self.audit = InMemoryAuditLog()
        self.sm = _build_sm(self.ledger, self.audit)

        self.final_downstream: list[StateEvent] = []
        self.sm.subscribe(self.final_downstream.append)

        self.thread_id = "thread-acme-001"
        self.negotiation_id = self.thread_id
        self.tenant_id = "alice"
        self.ctx = TenantContext(tenant_id=self.tenant_id)

        # Inbox: redline message with one attachment
        self.inbox = MockInboxAdapter()
        self.inbox.add_attachment("att-001", _SYNTHETIC_CONTENT)
        self.inbox.add_message(make_redline_message(
            message_id="msg-001",
            thread_id=self.thread_id,
            attachment_ids=("att-001",),
        ))

        self.storage = MockStorageAdapter()

        # Agent 2
        self.extractor = DocumentExtractor(
            inbox=self.inbox,
            storage=self.storage,
            audit=self.audit,
            config={"storage_root": "tenant-root"},
        )
        self.extractor.subscribe(
            lambda event: self.sm.process_event(
                TenantContext(tenant_id=event.tenant_id), event
            )
        )

        # Agent 1
        self.watcher = EmailWatcher(
            inbox=self.inbox,
            classify=lambda s, b: CLASSIFICATION_REDLINE,
            audit=self.audit,
            config={},
        )
        # Wire Agent 1 → State Manager
        self.watcher.subscribe(
            lambda event: self.sm.process_event(
                TenantContext(tenant_id=event.tenant_id), event
            )
        )
        # Wire State Manager → Agent 2 (via the extraction event)
        self.sm.subscribe(
            lambda event: self.extractor.process_event(
                TenantContext(tenant_id=event.tenant_id), event
            )
        )

        # Seed negotiation in CONTRACT_SENT state
        _seed_negotiation(
            self.sm, self.ledger,
            tenant_id=self.tenant_id,
            negotiation_id=self.negotiation_id,
            thread_id=self.thread_id,
        )

    def test_full_chain_transitions_to_redlines_received(self):
        self.watcher.poll(self.ctx, since=_EPOCH, active_thread_ids={self.thread_id})
        row = self.sm.get_negotiation(self.ctx, self.negotiation_id)
        self.assertEqual(row.status, NegotiationState.REDLINES_RECEIVED)

    def test_full_chain_increments_round(self):
        self.watcher.poll(self.ctx, since=_EPOCH, active_thread_ids={self.thread_id})
        row = self.sm.get_negotiation(self.ctx, self.negotiation_id)
        self.assertEqual(row.round_number, 1)

    def test_full_chain_stores_file(self):
        self.watcher.poll(self.ctx, since=_EPOCH, active_thread_ids={self.thread_id})
        self.assertEqual(len(self.storage.stored_paths), 1)

    def test_full_chain_updates_last_counterparty_version(self):
        self.watcher.poll(self.ctx, since=_EPOCH, active_thread_ids={self.thread_id})
        row = self.sm.get_negotiation(self.ctx, self.negotiation_id)
        self.assertIsNotNone(row.last_counterparty_version)

    def test_full_chain_emits_round_ready_for_analysis(self):
        self.watcher.poll(self.ctx, since=_EPOCH, active_thread_ids={self.thread_id})
        analysis_events = [
            e for e in self.final_downstream
            if e.event_type == EVENT_ROUND_READY_FOR_ANALYSIS
        ]
        self.assertEqual(len(analysis_events), 1)

    def test_all_three_agents_write_to_audit_log(self):
        self.watcher.poll(self.ctx, since=_EPOCH, active_thread_ids={self.thread_id})
        for agent_name in ("email_watcher", "state_manager", "document_extractor"):
            events = self.audit.query(agent_name=agent_name)
            self.assertTrue(len(events) > 0, f"{agent_name} wrote no audit events")
