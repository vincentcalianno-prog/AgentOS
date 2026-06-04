"""Integration tests: Agent 5 (Redline Analysis) pipeline.

Two pipeline scopes tested:
  1. Agent 5 alone: EVENT_DIFF_COMPLETE → redline_analysis.json stored
     → EVENT_ANALYSIS_COMPLETE emitted → State Manager audits.
  2. Full chain: Agent 1 → SM → Agent 2 → SM → Agent 4 → SM → Agent 5 → SM
     (end-to-end from inbox message to analysis complete).

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
from acp.layer_b.agents.redline_analysis import ANALYSIS_FILENAME, RedlineAnalyzer
from acp.layer_b.agents.state_manager import StateManager
from acp.layer_b.agents.structural_diff import DIFF_FILENAME, Clause, StructuralDiff
from acp.layer_b.core.adapters.in_memory_audit import InMemoryAuditLog
from acp.layer_b.core.adapters.sqlite_ledger import SQLiteLedger
from acp.layer_b.core.tenancy import TenancyEnforcer
from acp.layer_b.core.types import (
    EVENT_ANALYSIS_COMPLETE,
    NegotiationRow,
    NegotiationState,
    StateEvent,
    TenantContext,
)
from acp.layer_b.tests.fixtures.mock_document_parser import (
    COUNTERPARTY_CLAUSES,
    OUTBOUND_CLAUSES,
)
from acp.layer_b.tests.fixtures.mock_inbox import MockInboxAdapter, make_redline_message
from acp.layer_b.tests.fixtures.mock_llm import ACME_INDUSTRIAL_ANALYZER
from acp.layer_b.tests.fixtures.mock_storage import MockStorageAdapter

_EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)
_SYNTHETIC_CONTENT = b"SYNTHETIC CONTRACT DOCUMENT BYTES - ACME INDUSTRIAL"


def _build_sm(ledger, audit):
    tenancy = TenancyEnforcer(audit)
    return StateManager(ledger=ledger, tenancy=tenancy, audit=audit)


def _seed_negotiation(sm, tenant_id, negotiation_id, thread_id,
                      initial_state=NegotiationState.NEGOTIATING,
                      storage_folder_path=None):
    ctx = TenantContext(tenant_id=tenant_id)
    row = NegotiationRow(
        negotiation_id=negotiation_id,
        row_number=1,
        owner=tenant_id,
        workflow_id="contract_redline",
        counterparty_description="Acme Industrial - synthetic widget assembly",
        contract_type="generic-agreement",
        counterparty_profile_ref="acme-industrial",
        status=initial_state,
        inbox_thread_id=thread_id,
        automation_status="Active",
        storage_folder_path=storage_folder_path,
    )
    return sm.create_negotiation(ctx, row)


class AnalysisEventToStateManagerTests(unittest.TestCase):
    """Agent 5 → SM: analysis complete is audited and re-emitted downstream."""

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
        self.diff_path = f"{self.storage_folder}/{DIFF_FILENAME}"

        # Write a minimal structural_diff.json
        diff_doc = {
            "negotiation_id": self.negotiation_id,
            "round_number": 1,
            "counterparty_document_path": f"{self.storage_folder}/cp.bin",
            "outbound_document_path": None,
            "entries": [
                {"clause_reference": "1.1", "change_type": "modified",
                 "original_text": "Net-30.", "counterparty_text": "Net-45.",
                 "surrounding_context": "", "character_delta": 3},
            ],
        }
        self.storage.store(self.diff_path, json.dumps(diff_doc).encode())

        _seed_negotiation(
            self.sm, self.tenant_id, self.negotiation_id, self.thread_id,
            storage_folder_path=self.storage_folder,
        )

        self.analyzer = RedlineAnalyzer(
            storage=self.storage,
            audit=self.audit,
            config={},
            analyze_clause=ACME_INDUSTRIAL_ANALYZER,
        )
        self.analyzer.subscribe(
            lambda event: self.sm.process_event(
                TenantContext(tenant_id=event.tenant_id), event
            )
        )

    def _make_diff_complete_event(self):
        from acp.layer_b.core.types import EVENT_DIFF_COMPLETE
        return StateEvent(
            event_type=EVENT_DIFF_COMPLETE,
            tenant_id=self.tenant_id,
            negotiation_id=self.negotiation_id,
            workflow_id="contract_redline",
            payload={"diff_path": self.diff_path, "round_number": 1},
            emitted_at=_EPOCH,
            emitted_by="structural_diff",
        )

    def test_analysis_json_is_persisted(self):
        self.analyzer.process_event(self.ctx, self._make_diff_complete_event())
        analysis_path = f"{self.storage_folder}/{ANALYSIS_FILENAME}"
        self.assertTrue(self.storage.exists(analysis_path))

    def test_analysis_complete_event_is_emitted_downstream(self):
        self.analyzer.process_event(self.ctx, self._make_diff_complete_event())
        events = [e for e in self.final_downstream if e.event_type == EVENT_ANALYSIS_COMPLETE]
        self.assertEqual(len(events), 1)

    def test_analysis_complete_carries_analysis_path(self):
        self.analyzer.process_event(self.ctx, self._make_diff_complete_event())
        evt = next(e for e in self.final_downstream if e.event_type == EVENT_ANALYSIS_COMPLETE)
        self.assertIsNotNone(evt.payload.get("analysis_path"))

    def test_analysis_complete_carries_summary(self):
        self.analyzer.process_event(self.ctx, self._make_diff_complete_event())
        evt = next(e for e in self.final_downstream if e.event_type == EVENT_ANALYSIS_COMPLETE)
        self.assertIn("summary", evt.payload)
        self.assertIn("total_analysed", evt.payload["summary"])

    def test_both_agents_write_to_audit_log(self):
        self.analyzer.process_event(self.ctx, self._make_diff_complete_event())
        for agent_name in ("redline_analyzer", "state_manager"):
            events = self.audit.query(agent_name=agent_name)
            self.assertTrue(len(events) > 0, f"{agent_name} wrote no audit events")


class FullChainTests(unittest.TestCase):
    """Agent 1 → SM → Agent 2 → SM → Agent 4 → SM → Agent 5 → SM."""

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
            inbox=self.inbox, storage=self.storage, audit=self.audit,
            config={"storage_root": "tenant-root"},
        )
        self.extractor.subscribe(
            lambda event: self.sm.process_event(TenantContext(tenant_id=event.tenant_id), event)
        )

        # Agent 4
        _diff_call_count = [0]

        def _diff_parser(content: bytes) -> list[Clause]:
            idx = _diff_call_count[0]
            _diff_call_count[0] += 1
            return COUNTERPARTY_CLAUSES if idx == 0 else OUTBOUND_CLAUSES

        self.differ = StructuralDiff(
            storage=self.storage, audit=self.audit, config={}, parse_document=_diff_parser,
        )
        self.differ.subscribe(
            lambda event: self.sm.process_event(TenantContext(tenant_id=event.tenant_id), event)
        )

        # Agent 5
        self.analyzer = RedlineAnalyzer(
            storage=self.storage, audit=self.audit, config={},
            analyze_clause=ACME_INDUSTRIAL_ANALYZER,
        )
        self.analyzer.subscribe(
            lambda event: self.sm.process_event(TenantContext(tenant_id=event.tenant_id), event)
        )

        # Agent 1
        self.watcher = EmailWatcher(
            inbox=self.inbox, classify=lambda s, b: CLASSIFICATION_REDLINE,
            audit=self.audit, config={},
        )
        self.watcher.subscribe(
            lambda event: self.sm.process_event(TenantContext(tenant_id=event.tenant_id), event)
        )
        self.sm.subscribe(
            lambda event: self.extractor.process_event(TenantContext(tenant_id=event.tenant_id), event)
        )
        self.sm.subscribe(
            lambda event: self.differ.process_event(TenantContext(tenant_id=event.tenant_id), event)
        )
        self.sm.subscribe(
            lambda event: self.analyzer.process_event(TenantContext(tenant_id=event.tenant_id), event)
        )

        _seed_negotiation(
            self.sm, self.tenant_id, self.negotiation_id, self.thread_id,
            initial_state=NegotiationState.CONTRACT_SENT,
        )

    def test_full_chain_emits_analysis_complete(self):
        self.watcher.poll(self.ctx, since=_EPOCH, active_thread_ids={self.thread_id})
        events = [e for e in self.final_downstream if e.event_type == EVENT_ANALYSIS_COMPLETE]
        self.assertEqual(len(events), 1)

    def test_full_chain_persists_analysis_json(self):
        self.watcher.poll(self.ctx, since=_EPOCH, active_thread_ids={self.thread_id})
        analysis_files = [p for p in self.storage.stored_paths if p.endswith(ANALYSIS_FILENAME)]
        self.assertEqual(len(analysis_files), 1)

    def test_full_chain_analysis_has_recommendations(self):
        self.watcher.poll(self.ctx, since=_EPOCH, active_thread_ids={self.thread_id})
        analysis_path = next(p for p in self.storage.stored_paths if p.endswith(ANALYSIS_FILENAME))
        doc = json.loads(self.storage.retrieve(analysis_path).decode())
        self.assertGreater(len(doc["recommendations"]), 0)

    def test_full_chain_state_is_negotiating(self):
        self.watcher.poll(self.ctx, since=_EPOCH, active_thread_ids={self.thread_id})
        row = self.sm.get_negotiation(self.ctx, self.negotiation_id)
        self.assertEqual(row.status, NegotiationState.NEGOTIATING)

    def test_all_five_agents_write_to_audit_log(self):
        self.watcher.poll(self.ctx, since=_EPOCH, active_thread_ids={self.thread_id})
        for agent_name in (
            "email_watcher", "state_manager", "document_extractor",
            "structural_diff", "redline_analyzer",
        ):
            events = self.audit.query(agent_name=agent_name)
            self.assertTrue(len(events) > 0, f"{agent_name} wrote no audit events")
