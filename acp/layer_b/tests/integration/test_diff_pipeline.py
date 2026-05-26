"""Integration tests: Agent 4 (Structural Diff) pipeline.

Two pipeline scopes tested:
  1. Agent 4 alone: EVENT_ROUND_READY_FOR_ANALYSIS → structural_diff.json stored
     → EVENT_DIFF_COMPLETE emitted → State Manager transitions to NEGOTIATING.
  2. Full chain: Agent 1 → State Manager → Agent 2 → State Manager → Agent 4
     → State Manager (end-to-end from inbox message to diff complete).

Per Implementation Guide Section 7.1: synthetic fixtures only.
    Counterparty: Acme Industrial
    Tenant owners: alice, bob, carol
"""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone

from acp.layer_b.agents.document_extraction import DocumentExtractor
from acp.layer_b.agents.email_watcher import CLASSIFICATION_REDLINE, EmailWatcher
from acp.layer_b.agents.state_manager import StateManager
from acp.layer_b.agents.structural_diff import DIFF_FILENAME, Clause, StructuralDiff
from acp.layer_b.core.adapters.in_memory_audit import InMemoryAuditLog
from acp.layer_b.core.adapters.sqlite_ledger import SQLiteLedger
from acp.layer_b.core.tenancy import TenancyEnforcer
from acp.layer_b.core.types import (
    EVENT_DIFF_COMPLETE,
    NegotiationRow,
    NegotiationState,
    StateEvent,
    TenantContext,
)
from acp.layer_b.tests.fixtures.mock_document_parser import (
    COUNTERPARTY_CLAUSES,
    OUTBOUND_CLAUSES,
    make_parser_for,
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
    tenant_id: str,
    negotiation_id: str,
    thread_id: str,
    initial_state: NegotiationState = NegotiationState.REDLINES_RECEIVED,
    storage_folder_path: str | None = None,
) -> NegotiationRow:
    ctx = TenantContext(tenant_id=tenant_id)
    row = NegotiationRow(
        negotiation_id=negotiation_id,
        row_number=1,
        owner=tenant_id,
        counterparty_description="Acme Industrial - synthetic widget assembly",
        contract_type="generic-agreement",
        counterparty_profile_ref="acme-industrial",
        status=initial_state,
        inbox_thread_id=thread_id,
        automation_status="Active",
        storage_folder_path=storage_folder_path,
    )
    return sm.create_negotiation(ctx, row)


class DiffEventToStateManagerTests(unittest.TestCase):
    """Agent 4 → State Manager: diff complete transitions negotiation to NEGOTIATING."""

    def setUp(self):
        self.ledger = SQLiteLedger(db_path=":memory:")
        self.audit = InMemoryAuditLog()
        self.sm = _build_sm(self.ledger, self.audit)

        self.final_downstream: list[StateEvent] = []
        self.sm.subscribe(self.final_downstream.append)

        self.storage = MockStorageAdapter()
        self.thread_id = "thread-acme-001"
        self.negotiation_id = self.thread_id
        self.tenant_id = "alice"
        self.ctx = TenantContext(tenant_id=self.tenant_id)

        self.storage_folder = "tenant-root/generic-agreement/acme-industrial/round_1"
        self.counterparty_path = f"{self.storage_folder}/20260101T000000Z_att-001.bin"
        self.outbound_path = "tenant-root/generic-agreement/acme-industrial/round_0/outbound.bin"

        # Seed both documents in storage
        self.storage.store(self.counterparty_path, _SYNTHETIC_CONTENT)
        self.storage.store(self.outbound_path, b"OUTBOUND CONTENT")

        # Seed negotiation in REDLINES_RECEIVED (as if Agents 1 & 2 already ran)
        _seed_negotiation(
            self.sm,
            tenant_id=self.tenant_id,
            negotiation_id=self.negotiation_id,
            thread_id=self.thread_id,
            storage_folder_path=self.storage_folder,
        )

        # Build Agent 4 with the Acme Industrial clause scenario
        _call_count = [0]

        def _parser(content: bytes) -> list[Clause]:
            idx = _call_count[0]
            _call_count[0] += 1
            return COUNTERPARTY_CLAUSES if idx == 0 else OUTBOUND_CLAUSES

        self.differ = StructuralDiff(
            storage=self.storage,
            audit=self.audit,
            config={},
            parse_document=_parser,
        )
        # Wire Agent 4 → State Manager
        self.differ.subscribe(
            lambda event: self.sm.process_event(
                TenantContext(tenant_id=event.tenant_id), event
            )
        )

    def _make_analysis_event(self) -> StateEvent:
        from acp.layer_b.core.types import EVENT_ROUND_READY_FOR_ANALYSIS
        return StateEvent(
            event_type=EVENT_ROUND_READY_FOR_ANALYSIS,
            tenant_id=self.tenant_id,
            negotiation_id=self.negotiation_id,
            payload={
                "counterparty_document_path": self.counterparty_path,
                "outbound_document_path": self.outbound_path,
                "storage_folder_path": self.storage_folder,
                "round_number": 1,
            },
            emitted_at=_EPOCH,
            emitted_by="state_manager",
        )

    def test_diff_json_is_persisted(self):
        self.differ.process_event(self.ctx, self._make_analysis_event())
        diff_path = f"{self.storage_folder}/{DIFF_FILENAME}"
        self.assertTrue(self.storage.exists(diff_path))

    def test_diff_json_contains_entries(self):
        self.differ.process_event(self.ctx, self._make_analysis_event())
        diff_path = f"{self.storage_folder}/{DIFF_FILENAME}"
        diff = json.loads(self.storage.retrieve(diff_path).decode())
        self.assertGreater(len(diff["entries"]), 0)

    def test_state_transitions_to_negotiating(self):
        self.differ.process_event(self.ctx, self._make_analysis_event())
        row = self.sm.get_negotiation(self.ctx, self.negotiation_id)
        self.assertEqual(row.status, NegotiationState.NEGOTIATING)

    def test_diff_complete_event_is_emitted_downstream(self):
        self.differ.process_event(self.ctx, self._make_analysis_event())
        diff_events = [e for e in self.final_downstream if e.event_type == EVENT_DIFF_COMPLETE]
        self.assertEqual(len(diff_events), 1)

    def test_diff_complete_event_carries_diff_path(self):
        self.differ.process_event(self.ctx, self._make_analysis_event())
        evt = next(e for e in self.final_downstream if e.event_type == EVENT_DIFF_COMPLETE)
        self.assertIsNotNone(evt.payload.get("diff_path"))

    def test_all_agents_write_to_audit_log(self):
        self.differ.process_event(self.ctx, self._make_analysis_event())
        for agent_name in ("structural_diff", "state_manager"):
            events = self.audit.query(agent_name=agent_name)
            self.assertTrue(len(events) > 0, f"{agent_name} wrote no audit events")


class FullChainTests(unittest.TestCase):
    """Agent 1 → SM → Agent 2 → SM → Agent 4 → SM: inbox to diff complete."""

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

        # Agent 4 — alternating parser for counterparty/outbound
        _call_count = [0]

        def _parser(content: bytes) -> list[Clause]:
            idx = _call_count[0]
            _call_count[0] += 1
            return COUNTERPARTY_CLAUSES if idx == 0 else OUTBOUND_CLAUSES

        self.differ = StructuralDiff(
            storage=self.storage,
            audit=self.audit,
            config={},
            parse_document=_parser,
        )
        self.differ.subscribe(
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
        # Wire State Manager → Agent 2
        self.sm.subscribe(
            lambda event: self.extractor.process_event(
                TenantContext(tenant_id=event.tenant_id), event
            )
        )
        # Wire State Manager → Agent 4
        self.sm.subscribe(
            lambda event: self.differ.process_event(
                TenantContext(tenant_id=event.tenant_id), event
            )
        )

        # Seed negotiation in CONTRACT_SENT
        _seed_negotiation(
            self.sm,
            tenant_id=self.tenant_id,
            negotiation_id=self.negotiation_id,
            thread_id=self.thread_id,
            initial_state=NegotiationState.CONTRACT_SENT,
        )

    def test_full_chain_transitions_to_negotiating(self):
        self.watcher.poll(self.ctx, since=_EPOCH, active_thread_ids={self.thread_id})
        row = self.sm.get_negotiation(self.ctx, self.negotiation_id)
        self.assertEqual(row.status, NegotiationState.NEGOTIATING)

    def test_full_chain_persists_diff_json(self):
        self.watcher.poll(self.ctx, since=_EPOCH, active_thread_ids={self.thread_id})
        diff_files = [p for p in self.storage.stored_paths if p.endswith(DIFF_FILENAME)]
        self.assertEqual(len(diff_files), 1)

    def test_full_chain_emits_diff_complete(self):
        self.watcher.poll(self.ctx, since=_EPOCH, active_thread_ids={self.thread_id})
        diff_events = [e for e in self.final_downstream if e.event_type == EVENT_DIFF_COMPLETE]
        self.assertEqual(len(diff_events), 1)

    def test_full_chain_stores_counterparty_document(self):
        self.watcher.poll(self.ctx, since=_EPOCH, active_thread_ids={self.thread_id})
        doc_files = [p for p in self.storage.stored_paths if p.endswith(".bin")]
        self.assertEqual(len(doc_files), 1)

    def test_all_four_agents_write_to_audit_log(self):
        self.watcher.poll(self.ctx, since=_EPOCH, active_thread_ids={self.thread_id})
        for agent_name in ("email_watcher", "state_manager", "document_extractor", "structural_diff"):
            events = self.audit.query(agent_name=agent_name)
            self.assertTrue(len(events) > 0, f"{agent_name} wrote no audit events")
