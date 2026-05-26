"""Unit tests: Agent 7 (LRS Generator).

Per Implementation Guide Section 7.1: synthetic fixtures only.
    Counterparty: Acme Industrial
    Tenant owners: alice, bob, carol

Unit tests construct StateEvent directly — they bypass State Manager.
Consequently _make_event() includes contract_type and counterparty_description
explicitly in the payload (fields that State Manager enriches in production).
"""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone

from acp.layer_b.agents.counter_proposal import PROPOSALS_FILENAME
from acp.layer_b.agents.lrs_generator import (
    LRS_DOCUMENT_FILENAME,
    LRS_METADATA_FILENAME,
    LRSGeneratorAgent,
    LRSInput,
    LRSOutput,
)
from acp.layer_b.agents.redline_analysis import ANALYSIS_FILENAME
from acp.layer_b.agents.structural_diff import DIFF_FILENAME
from acp.layer_b.core.adapters.in_memory_audit import InMemoryAuditLog
from acp.layer_b.core.types import (
    EVENT_COUNTER_PROPOSALS_READY,
    EVENT_LRS_READY,
    StateEvent,
    TenantContext,
)
from acp.layer_b.tests.fixtures.mock_renderer import (
    ACME_INDUSTRIAL_RENDERER,
    make_fixed_renderer,
    make_markdown_renderer,
)
from acp.layer_b.tests.fixtures.mock_storage import MockStorageAdapter

_EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)
_STORAGE_FOLDER = "tenant-root/generic-agreement/acme-industrial/round_1"
_DIFF_PATH = f"{_STORAGE_FOLDER}/{DIFF_FILENAME}"
_ANALYSIS_PATH = f"{_STORAGE_FOLDER}/{ANALYSIS_FILENAME}"
_PROPOSALS_PATH = f"{_STORAGE_FOLDER}/{PROPOSALS_FILENAME}"
_LRS_MD_PATH = f"{_STORAGE_FOLDER}/lrs_v1.md"
_METADATA_PATH = f"{_STORAGE_FOLDER}/lrs_v1_metadata.json"


def _make_event(
    negotiation_id: str = "neg-001",
    tenant_id: str = "alice",
    proposals_path: str = _PROPOSALS_PATH,
    round_number: int = 1,
    contract_type: str = "generic-agreement",
    counterparty_description: str = "Acme Industrial - synthetic widget assembly",
) -> StateEvent:
    """Construct an EVENT_COUNTER_PROPOSALS_READY as State Manager would emit it.

    Includes contract_type and counterparty_description in the payload — fields
    that State Manager enriches from the NegotiationRow before re-emitting.
    """
    return StateEvent(
        event_type=EVENT_COUNTER_PROPOSALS_READY,
        tenant_id=tenant_id,
        negotiation_id=negotiation_id,
        workflow_id="contract_redline",
        payload={
            "proposals_path": proposals_path,
            "round_number": round_number,
            "summary": {},
            "contract_type": contract_type,
            "counterparty_description": counterparty_description,
        },
        emitted_at=_EPOCH,
        emitted_by="state_manager",
    )


def _seed_inputs(storage: MockStorageAdapter, negotiation_id: str = "neg-001") -> None:
    """Write structural_diff.json, redline_analysis.json, and counter_proposals.json."""
    diff_doc = {
        "negotiation_id": negotiation_id,
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
    storage.store(_DIFF_PATH, json.dumps(diff_doc).encode())

    analysis_doc = {
        "negotiation_id": negotiation_id,
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
    storage.store(_ANALYSIS_PATH, json.dumps(analysis_doc).encode())

    proposals_doc = {
        "negotiation_id": negotiation_id,
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
    storage.store(_PROPOSALS_PATH, json.dumps(proposals_doc).encode())


def _make_agent(storage, renderer, config=None) -> tuple:
    audit = InMemoryAuditLog()
    captured: list[StateEvent] = []
    agent = LRSGeneratorAgent(
        storage=storage,
        audit=audit,
        config=config or {},
        render_lrs=renderer,
    )
    agent.subscribe(captured.append)
    return agent, audit, captured


def _alice() -> TenantContext:
    return TenantContext(tenant_id="alice")


class HappyPathTests(unittest.TestCase):
    """All three input JSONs present — document written, event emitted."""

    def setUp(self):
        self.storage = MockStorageAdapter()
        _seed_inputs(self.storage)
        self.agent, self.audit, self.captured = _make_agent(
            self.storage, ACME_INDUSTRIAL_RENDERER
        )

    def test_lrs_document_is_written(self):
        self.agent.process_event(_alice(), _make_event())
        self.assertTrue(self.storage.exists(_LRS_MD_PATH))

    def test_metadata_json_is_written(self):
        self.agent.process_event(_alice(), _make_event())
        self.assertTrue(self.storage.exists(_METADATA_PATH))

    def test_lrs_ready_event_is_emitted(self):
        self.agent.process_event(_alice(), _make_event())
        events = [e for e in self.captured if e.event_type == EVENT_LRS_READY]
        self.assertEqual(len(events), 1)

    def test_event_carries_lrs_path(self):
        self.agent.process_event(_alice(), _make_event())
        evt = next(e for e in self.captured if e.event_type == EVENT_LRS_READY)
        self.assertEqual(evt.payload.get("lrs_path"), _LRS_MD_PATH)

    def test_event_carries_round_number(self):
        self.agent.process_event(_alice(), _make_event())
        evt = next(e for e in self.captured if e.event_type == EVENT_LRS_READY)
        self.assertEqual(evt.payload.get("round_number"), 1)


class PartialInputTests(unittest.TestCase):
    """Missing input JSONs produce empty dicts and audit warnings; event still emitted."""

    def test_missing_diff_produces_warning_and_empty_dict(self):
        storage = MockStorageAdapter()
        _seed_inputs(storage)
        storage.stored_data.pop(_DIFF_PATH, None)  # remove diff
        agent, audit, captured = _make_agent(storage, make_fixed_renderer())
        agent.process_event(_alice(), _make_event())
        warnings = [e for e in audit.query(agent_name="lrs_generator") if e.severity == "warning"]
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0].event_type, "diff_missing")
        self.assertEqual(len(captured), 1)

    def test_missing_analysis_produces_warning_and_empty_dict(self):
        storage = MockStorageAdapter()
        _seed_inputs(storage)
        storage.stored_data.pop(_ANALYSIS_PATH, None)
        agent, audit, captured = _make_agent(storage, make_fixed_renderer())
        agent.process_event(_alice(), _make_event())
        warnings = [e for e in audit.query(agent_name="lrs_generator") if e.severity == "warning"]
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0].event_type, "analysis_missing")
        self.assertEqual(len(captured), 1)

    def test_missing_counter_proposals_produces_warning_and_empty_dict(self):
        storage = MockStorageAdapter()
        _seed_inputs(storage)
        storage.stored_data.pop(_PROPOSALS_PATH, None)
        agent, audit, captured = _make_agent(storage, make_fixed_renderer())
        agent.process_event(_alice(), _make_event())
        warnings = [e for e in audit.query(agent_name="lrs_generator") if e.severity == "warning"]
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0].event_type, "counter_proposals_missing")
        self.assertEqual(len(captured), 1)

    def test_all_three_missing_produces_three_warnings(self):
        storage = MockStorageAdapter()
        # Seed only proposals_path so the event doesn't get skipped,
        # but none of the three input JSONs
        storage.store(_PROPOSALS_PATH, b"")  # placeholder so event is processed
        agent, audit, captured = _make_agent(storage, make_fixed_renderer())
        agent.process_event(_alice(), _make_event())
        warnings = [e for e in audit.query(agent_name="lrs_generator") if e.severity == "warning"]
        warning_types = {e.event_type for e in warnings}
        self.assertIn("diff_missing", warning_types)
        self.assertIn("analysis_missing", warning_types)
        self.assertIn("counter_proposals_missing", warning_types)


class FilenamePatternTests(unittest.TestCase):
    """LRS document and metadata filenames follow the configured templates."""

    def test_document_filename_uses_round_number_and_format(self):
        storage = MockStorageAdapter()
        _seed_inputs(storage)
        agent, _, _ = _make_agent(storage, make_markdown_renderer())
        agent.process_event(_alice(), _make_event(round_number=1))
        self.assertTrue(storage.exists(f"{_STORAGE_FOLDER}/lrs_v1.md"))

    def test_different_format_produces_correct_extension(self):
        storage = MockStorageAdapter()
        _seed_inputs(storage)
        agent, _, _ = _make_agent(
            storage, make_fixed_renderer(document_format="pdf")
        )
        agent.process_event(_alice(), _make_event(round_number=2))
        self.assertTrue(storage.exists(f"{_STORAGE_FOLDER}/lrs_v2.pdf"))

    def test_metadata_filename_is_independent_of_document_format(self):
        storage = MockStorageAdapter()
        _seed_inputs(storage)
        agent, _, _ = _make_agent(
            storage, make_fixed_renderer(document_format="docx")
        )
        agent.process_event(_alice(), _make_event(round_number=3))
        self.assertTrue(storage.exists(f"{_STORAGE_FOLDER}/lrs_v3_metadata.json"))


class RendererContractTests(unittest.TestCase):
    """LRSInput is constructed with the correct fields; renderer failure is non-fatal."""

    def test_lrs_input_fields_are_correct(self):
        """Renderer receives correct negotiation_id, workflow_id, contract_type, counterparty_name."""
        received: list[LRSInput] = []

        def _capturing_renderer(lrs_input: LRSInput) -> LRSOutput:
            received.append(lrs_input)
            return LRSOutput(document_bytes=b"captured", document_format="txt", metadata={})

        storage = MockStorageAdapter()
        _seed_inputs(storage)
        agent, _, _ = _make_agent(storage, _capturing_renderer)
        agent.process_event(
            _alice(),
            _make_event(
                negotiation_id="neg-acme",
                contract_type="generic-agreement",
                counterparty_description="Acme Industrial - synthetic widget assembly",
            ),
        )
        self.assertEqual(len(received), 1)
        inp = received[0]
        self.assertEqual(inp.negotiation_id, "neg-acme")
        self.assertEqual(inp.workflow_id, "contract_redline")
        self.assertEqual(inp.contract_type, "generic-agreement")
        self.assertEqual(inp.counterparty_name, "Acme Industrial - synthetic widget assembly")
        self.assertEqual(inp.round_number, 1)

    def test_renderer_failure_event_still_emitted_with_legal_review_flag(self):
        def _failing_renderer(lrs_input: LRSInput) -> LRSOutput:
            raise RuntimeError("Renderer unavailable")

        storage = MockStorageAdapter()
        _seed_inputs(storage)
        agent, _, captured = _make_agent(storage, _failing_renderer)
        agent.process_event(_alice(), _make_event())
        self.assertEqual(len(captured), 1)
        evt = captured[0]
        self.assertTrue(evt.payload.get("requires_legal_review"))

    def test_renderer_failure_still_writes_placeholder_to_storage(self):
        def _failing_renderer(lrs_input: LRSInput) -> LRSOutput:
            raise RuntimeError("Renderer unavailable")

        storage = MockStorageAdapter()
        _seed_inputs(storage)
        agent, _, _ = _make_agent(storage, _failing_renderer)
        agent.process_event(_alice(), _make_event())
        # Placeholder document (lrs_v1.txt) and metadata should be written
        lrs_files = [p for p in storage.stored_paths if "lrs_v1" in p]
        self.assertGreater(len(lrs_files), 0)


class WrongEventTypeTests(unittest.TestCase):
    """Non-counter-proposals-ready events are silently ignored."""

    def test_wrong_event_type_ignored(self):
        storage = MockStorageAdapter()
        agent, _, captured = _make_agent(storage, make_fixed_renderer())
        wrong_event = StateEvent(
            event_type="some_other_event",
            tenant_id="alice",
            negotiation_id="neg-001",
            workflow_id="contract_redline",
            payload={},
            emitted_at=_EPOCH,
            emitted_by="state_manager",
        )
        agent.process_event(_alice(), wrong_event)
        self.assertEqual(len(captured), 0)
        self.assertEqual(len(storage.stored_paths), 0)


class AuditTrailTests(unittest.TestCase):
    """Audit events are written correctly."""

    def setUp(self):
        self.storage = MockStorageAdapter()
        _seed_inputs(self.storage)
        self.agent, self.audit, self.captured = _make_agent(
            self.storage, ACME_INDUSTRIAL_RENDERER
        )

    def test_lrs_generated_is_audited(self):
        self.agent.process_event(_alice(), _make_event())
        events = self.audit.query(agent_name="lrs_generator")
        generated = [e for e in events if e.event_type == "lrs_generated"]
        self.assertEqual(len(generated), 1)

    def test_lrs_path_in_audit_payload(self):
        self.agent.process_event(_alice(), _make_event())
        events = self.audit.query(agent_name="lrs_generator")
        generated = next(e for e in events if e.event_type == "lrs_generated")
        self.assertIn("lrs_path", generated.payload)

    def test_missing_json_audited_as_warning(self):
        storage = MockStorageAdapter()
        _seed_inputs(storage)
        storage.stored_data.pop(_DIFF_PATH, None)
        agent, audit, _ = _make_agent(storage, make_fixed_renderer())
        agent.process_event(_alice(), _make_event())
        warnings = [e for e in audit.query(agent_name="lrs_generator") if e.severity == "warning"]
        self.assertTrue(len(warnings) >= 1)

    def test_audit_events_carry_correct_tenant(self):
        self.agent.process_event(TenantContext(tenant_id="bob"), _make_event(tenant_id="bob"))
        events = self.audit.query(agent_name="lrs_generator")
        for evt in events:
            self.assertEqual(evt.tenant_id, "bob")

    def test_audit_events_carry_workflow_id(self):
        self.agent.process_event(_alice(), _make_event())
        events = self.audit.query(agent_name="lrs_generator")
        for evt in events:
            self.assertEqual(evt.workflow_id, "contract_redline")
