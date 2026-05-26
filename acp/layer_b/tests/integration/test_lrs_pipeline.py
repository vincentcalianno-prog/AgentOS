"""Integration tests: Agent 7 (LRS Generator) pipeline.

Two pipeline scopes tested:
  1. Agent 7 alone: EVENT_COUNTER_PROPOSALS_READY → lrs doc stored
     → EVENT_LRS_READY emitted → State Manager audits.
  2. Full chain: Agent 1 → SM → Agent 2 → SM → Agent 4 → SM → Agent 5 → SM → Agent 6 → SM → Agent 7 → SM
     (end-to-end from inbox message to LRS ready).

Per Implementation Guide Section 7.1: synthetic fixtures only.
    Counterparty: Acme Industrial
    Tenant owners: alice, bob, carol
"""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone

from acp.layer_b.agents.counter_proposal import PROPOSALS_FILENAME, CounterProposalAgent
from acp.layer_b.agents.document_extraction import DocumentExtractor
from acp.layer_b.agents.email_watcher import CLASSIFICATION_REDLINE, EmailWatcher
from acp.layer_b.agents.lrs_generator import LRSGeneratorAgent
from acp.layer_b.agents.redline_analysis import ANALYSIS_FILENAME, RedlineAnalyzer
from acp.layer_b.agents.state_manager import StateManager
from acp.layer_b.agents.structural_diff import DIFF_FILENAME, Clause, StructuralDiff
from acp.layer_b.core.adapters.in_memory_audit import InMemoryAuditLog
from acp.layer_b.core.adapters.sqlite_ledger import SQLiteLedger
from acp.layer_b.core.tenancy import TenancyEnforcer
from acp.layer_b.core.types import (
    EVENT_COUNTER_PROPOSALS_READY,
    EVENT_LRS_READY,
    NegotiationRow,
    NegotiationState,
    StateEvent,
    TenantContext,
)
from acp.layer_b.tests.fixtures.mock_document_parser import (
    COUNTERPARTY_CLAUSES,
    OUTBOUND_CLAUSES,
)
from acp.layer_b.tests.fixtures.mock_drafter import ACME_INDUSTRIAL_DRAFTER
from acp.layer_b.tests.fixtures.mock_inbox import MockInboxAdapter, make_redline_message
from acp.layer_b.tests.fixtures.mock_llm import ACME_INDUSTRIAL_ANALYZER
from acp.layer_b.tests.fixtures.mock_renderer import ACME_INDUSTRIAL_RENDERER
from acp.layer_b.tests.fixtures.mock_storage import MockStorageAdapter

_EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)
_SYNTHETIC_CONTENT = b"SYNTHETIC CONTRACT DOCUMENT BYTES - ACME INDUSTRIAL"
_STORAGE_FOLDER = "tenant-root/generic-agreement/acme-industrial/round_1"


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


class LRSEventToStateManagerTests(unittest.TestCase):
    """Agent 7 → SM: lrs_ready is audited and re-emitted downstream.

    State Manager receives a bare EVENT_COUNTER_PROPOSALS_READY (no contract_type /
    counterparty_description), enriches it from the NegotiationRow, re-emits to
    Agent 7, which writes the LRS document and emits EVENT_LRS_READY back to SM.
    """

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

        self.proposals_path = f"{_STORAGE_FOLDER}/{PROPOSALS_FILENAME}"

        # Pre-seed the three input JSONs that Agent 7 reads
        diff_doc = {
            "negotiation_id": self.negotiation_id,
            "round_number": 1,
            "entries": [
                {
                    "clause_reference": "1.1",
                    "change_type": "modified",
                    "original_text": "Payment terms are net-30 from invoice date.",
                    "counterparty_text": "Payment terms are net-45 from invoice date.",
                },
            ],
        }
        self.storage.store(f"{_STORAGE_FOLDER}/{DIFF_FILENAME}", json.dumps(diff_doc).encode())

        analysis_doc = {
            "negotiation_id": self.negotiation_id,
            "round_number": 1,
            "recommendations": [
                {
                    "clause_reference": "1.1",
                    "recommendation": "reject",
                    "reasoning": "Net-45 exceeds policy maximum.",
                    "original_text": "Payment terms are net-30 from invoice date.",
                    "counterparty_text": "Payment terms are net-45 from invoice date.",
                },
            ],
        }
        self.storage.store(f"{_STORAGE_FOLDER}/{ANALYSIS_FILENAME}", json.dumps(analysis_doc).encode())

        proposals_doc = {
            "negotiation_id": self.negotiation_id,
            "round_number": 1,
            "drafts": [
                {
                    "clause_reference": "1.1",
                    "based_on_recommendation": "reject",
                    "counter_text": "Payment terms shall remain net-30 from invoice date.",
                    "tone": "firm",
                    "requires_legal_review": False,
                },
            ],
        }
        self.storage.store(self.proposals_path, json.dumps(proposals_doc).encode())

        _seed_negotiation(
            self.sm, self.tenant_id, self.negotiation_id, self.thread_id,
            storage_folder_path=_STORAGE_FOLDER,
        )

        self.lrs_agent = LRSGeneratorAgent(
            storage=self.storage,
            audit=self.audit,
            config={},
            render_lrs=ACME_INDUSTRIAL_RENDERER,
        )
        # SM re-emits enriched EVENT_COUNTER_PROPOSALS_READY → Agent 7
        self.sm.subscribe(
            lambda event: self.lrs_agent.process_event(
                TenantContext(tenant_id=event.tenant_id), event
            )
        )
        # Agent 7 emits EVENT_LRS_READY → SM audits + re-emits to final_downstream
        self.lrs_agent.subscribe(
            lambda event: self.sm.process_event(
                TenantContext(tenant_id=event.tenant_id), event
            )
        )

    def _make_counter_proposals_ready_event(self):
        """EVENT_COUNTER_PROPOSALS_READY as Agent 6 would emit — no contract_type/counterparty_description.

        State Manager enriches those fields from the NegotiationRow before re-emitting to Agent 7.
        """
        return StateEvent(
            event_type=EVENT_COUNTER_PROPOSALS_READY,
            tenant_id=self.tenant_id,
            negotiation_id=self.negotiation_id,
            workflow_id="contract_redline",
            payload={
                "proposals_path": self.proposals_path,
                "round_number": 1,
                "summary": {"total_drafted": 1},
            },
            emitted_at=_EPOCH,
            emitted_by="counter_proposal_agent",
        )

    def test_lrs_document_is_persisted(self):
        self.sm.process_event(self.ctx, self._make_counter_proposals_ready_event())
        lrs_files = [p for p in self.storage.stored_paths
                     if "lrs_v" in p and not p.endswith("_metadata.json")]
        self.assertEqual(len(lrs_files), 1)

    def test_lrs_metadata_is_persisted(self):
        self.sm.process_event(self.ctx, self._make_counter_proposals_ready_event())
        meta_files = [p for p in self.storage.stored_paths if p.endswith("_metadata.json")]
        self.assertEqual(len(meta_files), 1)

    def test_lrs_ready_event_emitted_downstream(self):
        self.sm.process_event(self.ctx, self._make_counter_proposals_ready_event())
        events = [e for e in self.final_downstream if e.event_type == EVENT_LRS_READY]
        self.assertEqual(len(events), 1)

    def test_event_carries_lrs_path(self):
        self.sm.process_event(self.ctx, self._make_counter_proposals_ready_event())
        evt = next(e for e in self.final_downstream if e.event_type == EVENT_LRS_READY)
        self.assertIsNotNone(evt.payload.get("lrs_path"))

    def test_state_manager_enriches_contract_type(self):
        """SM enriches contract_type from NegotiationRow; markdown renderer includes it in the document."""
        self.sm.process_event(self.ctx, self._make_counter_proposals_ready_event())
        lrs_path = next(p for p in self.storage.stored_paths
                        if "lrs_v" in p and not p.endswith("_metadata.json"))
        content = self.storage.retrieve(lrs_path).decode()
        self.assertIn("generic-agreement", content)

    def test_both_agents_write_to_audit_log(self):
        self.sm.process_event(self.ctx, self._make_counter_proposals_ready_event())
        for agent_name in ("lrs_generator", "state_manager"):
            events = self.audit.query(agent_name=agent_name)
            self.assertTrue(len(events) > 0, f"{agent_name} wrote no audit events")


class FullChainTests(unittest.TestCase):
    """Agent 1 → SM → Agent 2 → SM → Agent 4 → SM → Agent 5 → SM → Agent 6 → SM → Agent 7 → SM."""

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

        # Agent 6
        self.drafter_agent = CounterProposalAgent(
            storage=self.storage, audit=self.audit, config={},
            draft_counter_proposal=ACME_INDUSTRIAL_DRAFTER,
        )
        self.drafter_agent.subscribe(
            lambda event: self.sm.process_event(TenantContext(tenant_id=event.tenant_id), event)
        )

        # Agent 7
        self.lrs_agent = LRSGeneratorAgent(
            storage=self.storage, audit=self.audit, config={},
            render_lrs=ACME_INDUSTRIAL_RENDERER,
        )
        self.lrs_agent.subscribe(
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
        self.sm.subscribe(
            lambda event: self.drafter_agent.process_event(TenantContext(tenant_id=event.tenant_id), event)
        )
        self.sm.subscribe(
            lambda event: self.lrs_agent.process_event(TenantContext(tenant_id=event.tenant_id), event)
        )

        _seed_negotiation(
            self.sm, self.tenant_id, self.negotiation_id, self.thread_id,
            initial_state=NegotiationState.CONTRACT_SENT,
        )

    def test_full_chain_emits_lrs_ready(self):
        self.watcher.poll(self.ctx, since=_EPOCH, active_thread_ids={self.thread_id})
        events = [e for e in self.final_downstream if e.event_type == EVENT_LRS_READY]
        self.assertEqual(len(events), 1)

    def test_full_chain_persists_lrs_document(self):
        self.watcher.poll(self.ctx, since=_EPOCH, active_thread_ids={self.thread_id})
        lrs_files = [p for p in self.storage.stored_paths
                     if "lrs_v" in p and not p.endswith("_metadata.json")]
        self.assertEqual(len(lrs_files), 1)

    def test_full_chain_lrs_document_has_content(self):
        self.watcher.poll(self.ctx, since=_EPOCH, active_thread_ids={self.thread_id})
        lrs_path = next(p for p in self.storage.stored_paths
                        if "lrs_v" in p and not p.endswith("_metadata.json"))
        content = self.storage.retrieve(lrs_path)
        self.assertGreater(len(content), 0)

    def test_full_chain_state_is_negotiating(self):
        self.watcher.poll(self.ctx, since=_EPOCH, active_thread_ids={self.thread_id})
        row = self.sm.get_negotiation(self.ctx, self.negotiation_id)
        self.assertEqual(row.status, NegotiationState.NEGOTIATING)

    def test_all_seven_agents_write_to_audit_log(self):
        self.watcher.poll(self.ctx, since=_EPOCH, active_thread_ids={self.thread_id})
        for agent_name in (
            "email_watcher", "state_manager", "document_extractor",
            "structural_diff", "redline_analyzer", "counter_proposal_agent",
            "lrs_generator",
        ):
            events = self.audit.query(agent_name=agent_name)
            self.assertTrue(len(events) > 0, f"{agent_name} wrote no audit events")
