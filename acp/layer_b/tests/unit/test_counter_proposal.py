"""Unit tests: Agent 6 (Counter-Proposal Drafting).

Per Implementation Guide Section 7.1: synthetic fixtures only.
    Counterparty: Acme Industrial
    Tenant owners: alice, bob, carol
"""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone

from acp.layer_b.agents.counter_proposal import (
    PROPOSALS_FILENAME,
    CounterProposalAgent,
    CounterProposalDraft,
)
from acp.layer_b.core.adapters.in_memory_audit import InMemoryAuditLog
from acp.layer_b.core.types import (
    EVENT_ANALYSIS_COMPLETE,
    EVENT_COUNTER_PROPOSALS_READY,
    StateEvent,
    TenantContext,
)
from acp.layer_b.tests.fixtures.mock_drafter import (
    ACME_INDUSTRIAL_DRAFTER,
    make_fixed_drafter,
    make_clause_map_drafter,
)
from acp.layer_b.tests.fixtures.mock_storage import MockStorageAdapter

_EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)
_STORAGE_FOLDER = "tenant-root/generic-agreement/acme-industrial/round_1"
_ANALYSIS_PATH = f"{_STORAGE_FOLDER}/redline_analysis.json"
_PROPOSALS_PATH = f"{_STORAGE_FOLDER}/{PROPOSALS_FILENAME}"


def _rec(ref, recommendation, reasoning, original, counterparty) -> dict:
    return {
        "clause_reference": ref,
        "recommendation": recommendation,
        "reasoning": reasoning,
        "original_text": original,
        "counterparty_text": counterparty,
    }


def _seed_analysis(storage, recommendations, negotiation_id="neg-001", round_number=1) -> None:
    doc = {
        "negotiation_id": negotiation_id,
        "round_number": round_number,
        "recommendations": recommendations,
    }
    storage.store(_ANALYSIS_PATH, json.dumps(doc).encode())


def _make_agent(storage, drafter, playbook_context="") -> tuple:
    audit = InMemoryAuditLog()
    captured: list[StateEvent] = []
    agent = CounterProposalAgent(
        storage=storage,
        audit=audit,
        config={"playbook_context": playbook_context},
        draft_counter_proposal=drafter,
    )
    agent.subscribe(captured.append)
    return agent, audit, captured


def _make_event(
    negotiation_id="neg-001",
    tenant_id="alice",
    analysis_path=_ANALYSIS_PATH,
    round_number=1,
) -> StateEvent:
    return StateEvent(
        event_type=EVENT_ANALYSIS_COMPLETE,
        tenant_id=tenant_id,
        negotiation_id=negotiation_id,
        payload={"analysis_path": analysis_path, "round_number": round_number},
        emitted_at=_EPOCH,
        emitted_by="redline_analyzer",
    )


class HappyPathTests(unittest.TestCase):
    """Basic happy-path: proposals written and event emitted."""

    def setUp(self):
        self.storage = MockStorageAdapter()
        _seed_analysis(self.storage, [
            _rec("1.1", "reject", "Net-45 exceeds policy.", "Net-30.", "Net-45."),
            _rec("2.2", "negotiate", "Compromise on notice.", "60-day notice.", "30-day notice."),
        ])
        self.agent, self.audit, self.captured = _make_agent(
            self.storage, ACME_INDUSTRIAL_DRAFTER
        )

    def test_proposals_json_is_written(self):
        self.agent.process_event(TenantContext(tenant_id="alice"), _make_event())
        self.assertTrue(self.storage.exists(_PROPOSALS_PATH))

    def test_counter_proposals_ready_event_is_emitted(self):
        self.agent.process_event(TenantContext(tenant_id="alice"), _make_event())
        events = [e for e in self.captured if e.event_type == EVENT_COUNTER_PROPOSALS_READY]
        self.assertEqual(len(events), 1)

    def test_event_carries_proposals_path(self):
        self.agent.process_event(TenantContext(tenant_id="alice"), _make_event())
        evt = next(e for e in self.captured if e.event_type == EVENT_COUNTER_PROPOSALS_READY)
        self.assertEqual(evt.payload.get("proposals_path"), _PROPOSALS_PATH)

    def test_event_carries_round_number(self):
        self.agent.process_event(TenantContext(tenant_id="alice"), _make_event())
        evt = next(e for e in self.captured if e.event_type == EVENT_COUNTER_PROPOSALS_READY)
        self.assertEqual(evt.payload.get("round_number"), 1)

    def test_event_carries_tenant_and_negotiation_id(self):
        self.agent.process_event(TenantContext(tenant_id="alice"), _make_event())
        evt = next(e for e in self.captured if e.event_type == EVENT_COUNTER_PROPOSALS_READY)
        self.assertEqual(evt.tenant_id, "alice")
        self.assertEqual(evt.negotiation_id, "neg-001")


class SkippedClausesTests(unittest.TestCase):
    """Accept and escalate clauses are not passed to the drafter."""

    def setUp(self):
        self.storage = MockStorageAdapter()
        self.drafted_refs: list[str] = []

        def _tracking_drafter(clause_reference, recommendation, reasoning_from_analysis,
                               original_text, counterparty_text, playbook_context):
            self.drafted_refs.append(clause_reference)
            return CounterProposalDraft(
                clause_reference=clause_reference,
                based_on_recommendation=recommendation,
                original_text=original_text,
                counterparty_text=counterparty_text,
                counter_text="counter",
                reasoning="tracked",
                tone="neutral",
                playbook_reference=None,
                requires_legal_review=False,
            )

        _seed_analysis(self.storage, [
            _rec("1.1", "reject", "Reject reason.", "Original.", "Counterparty."),
            _rec("2.2", "negotiate", "Negotiate reason.", "Original.", "Counterparty."),
            _rec("3.1", "accept", "Accept reason.", "Original.", "Counterparty."),
            _rec("4.1", "escalate", "Escalate reason.", "Original.", "Counterparty."),
        ])
        self.agent, self.audit, self.captured = _make_agent(self.storage, _tracking_drafter)

    def test_accept_clause_not_drafted(self):
        self.agent.process_event(TenantContext(tenant_id="alice"), _make_event())
        self.assertNotIn("3.1", self.drafted_refs)

    def test_escalate_clause_not_drafted(self):
        self.agent.process_event(TenantContext(tenant_id="alice"), _make_event())
        self.assertNotIn("4.1", self.drafted_refs)

    def test_only_draftable_clauses_in_json(self):
        self.agent.process_event(TenantContext(tenant_id="alice"), _make_event())
        doc = json.loads(self.storage.retrieve(_PROPOSALS_PATH).decode())
        drafted_refs = {d["clause_reference"] for d in doc["drafts"]}
        self.assertEqual(drafted_refs, {"1.1", "2.2"})


class StoragePersistenceTests(unittest.TestCase):
    """counter_proposals.json is written to the correct path with the right fields."""

    def setUp(self):
        self.storage = MockStorageAdapter()
        _seed_analysis(self.storage, [
            _rec("1.1", "reject", "Reject reason.", "Net-30.", "Net-45."),
        ], negotiation_id="neg-acme", round_number=2)
        drafter = make_fixed_drafter("Net-30 reinstated.", tone="firm")
        self.agent, self.audit, self.captured = _make_agent(self.storage, drafter)

    def test_written_to_correct_path(self):
        self.agent.process_event(
            TenantContext(tenant_id="alice"),
            _make_event(negotiation_id="neg-acme", round_number=2),
        )
        self.assertTrue(self.storage.exists(_PROPOSALS_PATH))

    def test_json_contains_negotiation_id(self):
        self.agent.process_event(
            TenantContext(tenant_id="alice"),
            _make_event(negotiation_id="neg-acme", round_number=2),
        )
        doc = json.loads(self.storage.retrieve(_PROPOSALS_PATH).decode())
        self.assertEqual(doc["negotiation_id"], "neg-acme")

    def test_json_contains_round_number(self):
        self.agent.process_event(
            TenantContext(tenant_id="alice"),
            _make_event(negotiation_id="neg-acme", round_number=2),
        )
        doc = json.loads(self.storage.retrieve(_PROPOSALS_PATH).decode())
        self.assertEqual(doc["round_number"], 2)

    def test_json_contains_analysis_path(self):
        self.agent.process_event(
            TenantContext(tenant_id="alice"),
            _make_event(negotiation_id="neg-acme", round_number=2),
        )
        doc = json.loads(self.storage.retrieve(_PROPOSALS_PATH).decode())
        self.assertEqual(doc["analysis_path"], _ANALYSIS_PATH)


class SummaryCountsTests(unittest.TestCase):
    """Summary counts are computed correctly and appear in both JSON and event."""

    def setUp(self):
        self.storage = MockStorageAdapter()
        _seed_analysis(self.storage, [
            _rec("1.1", "reject", "Reject.", "Original.", "Counterparty."),
            _rec("2.2", "negotiate", "Negotiate.", "Original.", "Counterparty."),
            _rec("3.1", "accept", "Accept.", "Original.", "Counterparty."),
        ])
        drafter = make_fixed_drafter("Counter text.", tone="neutral")
        self.agent, self.audit, self.captured = _make_agent(self.storage, drafter)

    def test_total_drafted_equals_negotiate_plus_reject(self):
        self.agent.process_event(TenantContext(tenant_id="alice"), _make_event())
        doc = json.loads(self.storage.retrieve(_PROPOSALS_PATH).decode())
        s = doc["summary"]
        self.assertEqual(s["total_drafted"], s["negotiate_count"] + s["reject_count"])

    def test_reject_count_correct(self):
        self.agent.process_event(TenantContext(tenant_id="alice"), _make_event())
        doc = json.loads(self.storage.retrieve(_PROPOSALS_PATH).decode())
        self.assertEqual(doc["summary"]["reject_count"], 1)

    def test_negotiate_count_correct(self):
        self.agent.process_event(TenantContext(tenant_id="alice"), _make_event())
        doc = json.loads(self.storage.retrieve(_PROPOSALS_PATH).decode())
        self.assertEqual(doc["summary"]["negotiate_count"], 1)

    def test_event_summary_matches_json_summary(self):
        self.agent.process_event(TenantContext(tenant_id="alice"), _make_event())
        doc = json.loads(self.storage.retrieve(_PROPOSALS_PATH).decode())
        evt = next(e for e in self.captured if e.event_type == EVENT_COUNTER_PROPOSALS_READY)
        self.assertEqual(evt.payload["summary"], doc["summary"])

    def test_acme_scenario_tones(self):
        """ACME_INDUSTRIAL_DRAFTER: 1.1 is firm, 2.2 is collaborative."""
        storage = MockStorageAdapter()
        _seed_analysis(storage, [
            _rec("1.1", "reject", "Net-45 exceeds policy.", "Net-30.", "Net-45."),
            _rec("2.2", "negotiate", "Compromise on notice.", "60-day notice.", "30-day notice."),
        ])
        agent, _, _ = _make_agent(storage, ACME_INDUSTRIAL_DRAFTER)
        agent.process_event(TenantContext(tenant_id="alice"), _make_event())
        doc = json.loads(storage.retrieve(_PROPOSALS_PATH).decode())
        tones = {d["clause_reference"]: d["tone"] for d in doc["drafts"]}
        self.assertEqual(tones.get("1.1"), "firm")
        self.assertEqual(tones.get("2.2"), "collaborative")


class LLMFailureTests(unittest.TestCase):
    """Failing drafter call produces counter_text='' entry; others still drafted; event emitted."""

    def setUp(self):
        self.storage = MockStorageAdapter()
        _seed_analysis(self.storage, [
            _rec("1.1", "reject", "Reject.", "Original.", "Counterparty."),
            _rec("2.2", "negotiate", "Negotiate.", "Original.", "Counterparty."),
        ])

        def _failing_on_1_1(clause_reference, recommendation, reasoning_from_analysis,
                             original_text, counterparty_text, playbook_context):
            if clause_reference == "1.1":
                raise RuntimeError("LLM timeout")
            return CounterProposalDraft(
                clause_reference=clause_reference,
                based_on_recommendation=recommendation,
                original_text=original_text,
                counterparty_text=counterparty_text,
                counter_text="Counter for 2.2.",
                reasoning="Drafted successfully.",
                tone="collaborative",
                playbook_reference=None,
                requires_legal_review=False,
            )

        self.agent, self.audit, self.captured = _make_agent(self.storage, _failing_on_1_1)

    def test_failed_clause_has_empty_counter_text(self):
        self.agent.process_event(TenantContext(tenant_id="alice"), _make_event())
        doc = json.loads(self.storage.retrieve(_PROPOSALS_PATH).decode())
        failed = next(d for d in doc["drafts"] if d["clause_reference"] == "1.1")
        self.assertEqual(failed["counter_text"], "")

    def test_other_clauses_still_drafted(self):
        self.agent.process_event(TenantContext(tenant_id="alice"), _make_event())
        doc = json.loads(self.storage.retrieve(_PROPOSALS_PATH).decode())
        ok = next(d for d in doc["drafts"] if d["clause_reference"] == "2.2")
        self.assertNotEqual(ok["counter_text"], "")

    def test_event_still_emitted_on_partial_failure(self):
        self.agent.process_event(TenantContext(tenant_id="alice"), _make_event())
        events = [e for e in self.captured if e.event_type == EVENT_COUNTER_PROPOSALS_READY]
        self.assertEqual(len(events), 1)

    def test_failure_is_audited(self):
        self.agent.process_event(TenantContext(tenant_id="alice"), _make_event())
        events = self.audit.query(agent_name="counter_proposal_agent")
        failure_events = [e for e in events if e.event_type == "clause_draft_failed"]
        self.assertEqual(len(failure_events), 1)
        self.assertEqual(failure_events[0].payload["clause_reference"], "1.1")

    def test_draft_failed_count_in_summary(self):
        self.agent.process_event(TenantContext(tenant_id="alice"), _make_event())
        doc = json.loads(self.storage.retrieve(_PROPOSALS_PATH).decode())
        self.assertEqual(doc["summary"]["draft_failed_count"], 1)


class NoDraftableClausesTests(unittest.TestCase):
    """When all clauses are accept/escalate, drafts list is empty but event is still emitted."""

    def setUp(self):
        self.storage = MockStorageAdapter()
        _seed_analysis(self.storage, [
            _rec("1.1", "accept", "Accept.", "Original.", "Counterparty."),
            _rec("2.2", "escalate", "Escalate.", "Original.", "Counterparty."),
        ])
        self.agent, self.audit, self.captured = _make_agent(
            self.storage, make_fixed_drafter("counter")
        )

    def test_drafts_list_is_empty(self):
        self.agent.process_event(TenantContext(tenant_id="alice"), _make_event())
        doc = json.loads(self.storage.retrieve(_PROPOSALS_PATH).decode())
        self.assertEqual(doc["drafts"], [])

    def test_event_still_emitted(self):
        self.agent.process_event(TenantContext(tenant_id="alice"), _make_event())
        events = [e for e in self.captured if e.event_type == EVENT_COUNTER_PROPOSALS_READY]
        self.assertEqual(len(events), 1)

    def test_total_drafted_is_zero(self):
        self.agent.process_event(TenantContext(tenant_id="alice"), _make_event())
        doc = json.loads(self.storage.retrieve(_PROPOSALS_PATH).decode())
        self.assertEqual(doc["summary"]["total_drafted"], 0)


class WrongEventTypeTests(unittest.TestCase):
    """Non-analysis-complete events are silently ignored."""

    def test_wrong_event_type_ignored(self):
        storage = MockStorageAdapter()
        agent, audit, captured = _make_agent(storage, make_fixed_drafter("counter"))
        wrong_event = StateEvent(
            event_type="some_other_event",
            tenant_id="alice",
            negotiation_id="neg-001",
            payload={},
            emitted_at=_EPOCH,
            emitted_by="other_agent",
        )
        agent.process_event(TenantContext(tenant_id="alice"), wrong_event)
        self.assertEqual(len(captured), 0)
        self.assertFalse(storage.exists(_PROPOSALS_PATH))


class AuditTrailTests(unittest.TestCase):
    """Audit events are written correctly."""

    def setUp(self):
        self.storage = MockStorageAdapter()
        _seed_analysis(self.storage, [
            _rec("1.1", "reject", "Reject reason.", "Net-30.", "Net-45."),
            _rec("2.2", "negotiate", "Negotiate reason.", "60-day.", "30-day."),
        ])
        self.agent, self.audit, self.captured = _make_agent(
            self.storage, ACME_INDUSTRIAL_DRAFTER
        )

    def test_drafting_completed_is_audited(self):
        self.agent.process_event(TenantContext(tenant_id="alice"), _make_event())
        events = self.audit.query(agent_name="counter_proposal_agent")
        completed = [e for e in events if e.event_type == "drafting_completed"]
        self.assertEqual(len(completed), 1)

    def test_each_clause_drafted_is_audited(self):
        self.agent.process_event(TenantContext(tenant_id="alice"), _make_event())
        events = self.audit.query(agent_name="counter_proposal_agent")
        drafted = [e for e in events if e.event_type == "clause_drafted"]
        self.assertEqual(len(drafted), 2)

    def test_missing_analysis_path_is_audited_as_warning(self):
        bad_event = StateEvent(
            event_type=EVENT_ANALYSIS_COMPLETE,
            tenant_id="alice",
            negotiation_id="neg-001",
            payload={"round_number": 1},  # no analysis_path
            emitted_at=_EPOCH,
            emitted_by="redline_analyzer",
        )
        self.agent.process_event(TenantContext(tenant_id="alice"), bad_event)
        events = self.audit.query(agent_name="counter_proposal_agent")
        warnings = [e for e in events if e.severity == "warning"]
        self.assertEqual(len(warnings), 1)

    def test_audit_events_carry_correct_tenant(self):
        self.agent.process_event(TenantContext(tenant_id="bob"), _make_event(tenant_id="bob"))
        events = self.audit.query(agent_name="counter_proposal_agent")
        for evt in events:
            self.assertEqual(evt.tenant_id, "bob")

    def test_playbook_context_is_passed_to_drafter(self):
        """Drafter receives the playbook_context from config."""
        received_contexts: list[str] = []

        def _context_capturing_drafter(
            clause_reference, recommendation, reasoning_from_analysis,
            original_text, counterparty_text, playbook_context,
        ):
            received_contexts.append(playbook_context)
            return CounterProposalDraft(
                clause_reference=clause_reference,
                based_on_recommendation=recommendation,
                original_text=original_text,
                counterparty_text=counterparty_text,
                counter_text="counter",
                reasoning="captured",
                tone="neutral",
                playbook_reference=None,
                requires_legal_review=False,
            )

        storage = MockStorageAdapter()
        _seed_analysis(storage, [
            _rec("1.1", "reject", "Reject.", "Original.", "Counterparty."),
        ])
        agent, _, _ = _make_agent(
            storage, _context_capturing_drafter, playbook_context="generic agreement playbook v3"
        )
        agent.process_event(TenantContext(tenant_id="alice"), _make_event())
        self.assertEqual(received_contexts, ["generic agreement playbook v3"])
