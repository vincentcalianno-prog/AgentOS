"""Unit tests for Agent 5 (Redline Analysis).

Per Implementation Guide Section 7.1: synthetic fixtures only.
    Counterparties: Acme Industrial, Beta Manufacturing, Gamma Components
    Tenant owners: alice, bob, carol
"""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone

from acp.layer_b.agents.redline_analysis import (
    ANALYSIS_FILENAME,
    ClauseRecommendation,
    RedlineAnalyzer,
)
from acp.layer_b.core.adapters.in_memory_audit import InMemoryAuditLog
from acp.layer_b.core.types import (
    EVENT_ANALYSIS_COMPLETE,
    EVENT_DIFF_COMPLETE,
    StateEvent,
    TenantContext,
)
from acp.layer_b.tests.fixtures.mock_llm import (
    ACCEPT_ALL,
    ACME_INDUSTRIAL_ANALYZER,
    ESCALATE_ALL,
    NEGOTIATE_ALL,
    REJECT_ALL,
    make_fixed_analyzer,
)
from acp.layer_b.tests.fixtures.mock_storage import MockStorageAdapter

_EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)
_STORAGE_FOLDER = "tenant-root/generic-agreement/acme-industrial/round_1"
_DIFF_PATH = f"{_STORAGE_FOLDER}/structural_diff.json"
_ANALYSIS_PATH = f"{_STORAGE_FOLDER}/{ANALYSIS_FILENAME}"


def _alice() -> TenantContext:
    return TenantContext(tenant_id="alice")


def _make_agent(
    storage: MockStorageAdapter,
    analyze_clause=None,
    playbook_context: str = "",
) -> tuple[RedlineAnalyzer, InMemoryAuditLog, list[StateEvent]]:
    audit = InMemoryAuditLog()
    captured: list[StateEvent] = []
    agent = RedlineAnalyzer(
        storage=storage,
        audit=audit,
        config={"playbook_context": playbook_context},
        analyze_clause=analyze_clause or REJECT_ALL,
    )
    agent.subscribe(captured.append)
    return agent, audit, captured


def _make_event(
    negotiation_id: str = "neg-acme-001",
    tenant_id: str = "alice",
    diff_path: str = _DIFF_PATH,
    round_number: int = 1,
) -> StateEvent:
    return StateEvent(
        event_type=EVENT_DIFF_COMPLETE,
        tenant_id=tenant_id,
        negotiation_id=negotiation_id,
        payload={"diff_path": diff_path, "round_number": round_number},
        emitted_at=_EPOCH,
        emitted_by="structural_diff",
    )


def _seed_diff(
    storage: MockStorageAdapter,
    entries: list[dict],
    negotiation_id: str = "neg-acme-001",
    round_number: int = 1,
) -> None:
    """Write a synthetic structural_diff.json to storage."""
    diff_doc = {
        "negotiation_id": negotiation_id,
        "round_number": round_number,
        "counterparty_document_path": f"{_STORAGE_FOLDER}/cp.bin",
        "outbound_document_path": f"{_STORAGE_FOLDER}/out.bin",
        "entries": entries,
    }
    storage.store(_DIFF_PATH, json.dumps(diff_doc).encode())


def _modified_entry(ref: str, original: str = "Original.", counterparty: str = "Modified.") -> dict:
    return {
        "clause_reference": ref,
        "change_type": "modified",
        "original_text": original,
        "counterparty_text": counterparty,
        "surrounding_context": "",
        "character_delta": len(counterparty) - len(original),
    }


def _unchanged_entry(ref: str, text: str = "Same text.") -> dict:
    return {
        "clause_reference": ref,
        "change_type": "unchanged",
        "original_text": text,
        "counterparty_text": text,
        "surrounding_context": "",
        "character_delta": 0,
    }


def _added_entry(ref: str, text: str = "New clause.") -> dict:
    return {
        "clause_reference": ref,
        "change_type": "added",
        "original_text": "",
        "counterparty_text": text,
        "surrounding_context": "",
        "character_delta": len(text),
    }


def _deleted_entry(ref: str, text: str = "Removed clause.") -> dict:
    return {
        "clause_reference": ref,
        "change_type": "deleted",
        "original_text": text,
        "counterparty_text": "",
        "surrounding_context": "",
        "character_delta": -len(text),
    }


class HappyPathTests(unittest.TestCase):
    """Changed clauses are analyzed, JSON written, event emitted."""

    def setUp(self):
        self.storage = MockStorageAdapter()
        _seed_diff(self.storage, [
            _modified_entry("1.1"),
            _unchanged_entry("1.2"),
            _added_entry("4.1"),
        ])
        self.agent, self.audit, self.events = _make_agent(self.storage, REJECT_ALL)

    def test_analysis_json_is_written(self):
        self.agent.process_event(_alice(), _make_event())
        self.assertTrue(self.storage.exists(_ANALYSIS_PATH))

    def test_event_is_emitted(self):
        self.agent.process_event(_alice(), _make_event())
        self.assertEqual(len(self.events), 1)
        self.assertEqual(self.events[0].event_type, EVENT_ANALYSIS_COMPLETE)

    def test_event_carries_analysis_path(self):
        self.agent.process_event(_alice(), _make_event())
        self.assertEqual(self.events[0].payload["analysis_path"], _ANALYSIS_PATH)

    def test_event_carries_round_number(self):
        self.agent.process_event(_alice(), _make_event(round_number=2))
        self.assertEqual(self.events[0].payload["round_number"], 2)

    def test_event_carries_correct_tenant_and_negotiation(self):
        self.agent.process_event(_alice(), _make_event(
            tenant_id="alice", negotiation_id="neg-acme-001"
        ))
        self.assertEqual(self.events[0].tenant_id, "alice")
        self.assertEqual(self.events[0].negotiation_id, "neg-acme-001")


class UnchangedClausesSkippedTests(unittest.TestCase):
    """Unchanged clauses are not passed to analyze_clause."""

    def test_analyze_clause_not_called_for_unchanged(self):
        call_log: list[str] = []

        def tracking_analyzer(ref, change_type, orig, cp, ctx):
            call_log.append(ref)
            return ClauseRecommendation(
                clause_reference=ref,
                recommendation="accept",
                reasoning="tracked",
                playbook_reference=None,
                confidence="high",
                requires_legal_review=False,
            )

        storage = MockStorageAdapter()
        _seed_diff(storage, [
            _unchanged_entry("1.1"),
            _unchanged_entry("1.2"),
            _modified_entry("2.1"),
        ])
        agent, _, _ = _make_agent(storage, tracking_analyzer)
        agent.process_event(_alice(), _make_event())
        self.assertNotIn("1.1", call_log)
        self.assertNotIn("1.2", call_log)
        self.assertIn("2.1", call_log)

    def test_only_changed_clauses_appear_in_recommendations(self):
        storage = MockStorageAdapter()
        _seed_diff(storage, [
            _unchanged_entry("1.1"),
            _modified_entry("2.1"),
        ])
        agent, _, _ = _make_agent(storage, REJECT_ALL)
        agent.process_event(_alice(), _make_event())
        doc = json.loads(storage.retrieve(_ANALYSIS_PATH).decode())
        refs = [r["clause_reference"] for r in doc["recommendations"]]
        self.assertNotIn("1.1", refs)
        self.assertIn("2.1", refs)


class StoragePersistenceTests(unittest.TestCase):
    """redline_analysis.json is written to the correct path."""

    def test_analysis_written_alongside_diff(self):
        storage = MockStorageAdapter()
        _seed_diff(storage, [_modified_entry("1.1")])
        agent, _, _ = _make_agent(storage, ACCEPT_ALL)
        agent.process_event(_alice(), _make_event())
        self.assertTrue(storage.exists(_ANALYSIS_PATH))

    def test_analysis_json_contains_negotiation_id(self):
        storage = MockStorageAdapter()
        _seed_diff(storage, [_modified_entry("1.1")], negotiation_id="neg-acme-001")
        agent, _, _ = _make_agent(storage, ACCEPT_ALL)
        agent.process_event(_alice(), _make_event(negotiation_id="neg-acme-001"))
        doc = json.loads(storage.retrieve(_ANALYSIS_PATH).decode())
        self.assertEqual(doc["negotiation_id"], "neg-acme-001")

    def test_analysis_json_contains_round_number(self):
        storage = MockStorageAdapter()
        _seed_diff(storage, [_modified_entry("1.1")], round_number=3)
        agent, _, _ = _make_agent(storage, ACCEPT_ALL)
        agent.process_event(_alice(), _make_event(round_number=3))
        doc = json.loads(storage.retrieve(_ANALYSIS_PATH).decode())
        self.assertEqual(doc["round_number"], 3)

    def test_analysis_json_contains_diff_path(self):
        storage = MockStorageAdapter()
        _seed_diff(storage, [_modified_entry("1.1")])
        agent, _, _ = _make_agent(storage, ACCEPT_ALL)
        agent.process_event(_alice(), _make_event())
        doc = json.loads(storage.retrieve(_ANALYSIS_PATH).decode())
        self.assertEqual(doc["diff_path"], _DIFF_PATH)


class SummaryCountsTests(unittest.TestCase):
    """Summary counts in JSON and event payload match actual recommendations."""

    def setUp(self):
        self.storage = MockStorageAdapter()
        # 2 modified + 1 added + 1 deleted = 4 changed clauses
        _seed_diff(self.storage, [
            _modified_entry("1.1"),
            _modified_entry("2.2"),
            _added_entry("4.1"),
            _deleted_entry("3.1"),
            _unchanged_entry("1.2"),
        ])

    def test_summary_counts_with_acme_analyzer(self):
        agent, _, events = _make_agent(self.storage, ACME_INDUSTRIAL_ANALYZER)
        agent.process_event(_alice(), _make_event())
        summary = events[0].payload["summary"]
        self.assertEqual(summary["total_analysed"], 4)
        self.assertEqual(summary["reject"], 1)
        self.assertEqual(summary["negotiate"], 1)
        self.assertEqual(summary["accept"], 1)
        self.assertEqual(summary["escalate"], 1)

    def test_summary_requires_legal_review_count(self):
        agent, _, events = _make_agent(self.storage, ACME_INDUSTRIAL_ANALYZER)
        agent.process_event(_alice(), _make_event())
        summary = events[0].payload["summary"]
        # Only 4.1 requires legal review in Acme Industrial scenario
        self.assertEqual(summary["requires_legal_review"], 1)

    def test_summary_with_reject_all(self):
        agent, _, events = _make_agent(self.storage, REJECT_ALL)
        agent.process_event(_alice(), _make_event())
        summary = events[0].payload["summary"]
        self.assertEqual(summary["total_analysed"], 4)
        self.assertEqual(summary["reject"], 4)
        self.assertEqual(summary["accept"], 0)

    def test_summary_in_json_matches_event_payload(self):
        agent, _, events = _make_agent(self.storage, NEGOTIATE_ALL)
        agent.process_event(_alice(), _make_event())
        doc = json.loads(self.storage.retrieve(_ANALYSIS_PATH).decode())
        self.assertEqual(doc["summary"], events[0].payload["summary"])


class LLMFailureTests(unittest.TestCase):
    """analyze_clause raising is non-fatal; clause gets escalation; others still processed."""

    def setUp(self):
        self.storage = MockStorageAdapter()
        _seed_diff(self.storage, [
            _modified_entry("1.1"),
            _modified_entry("2.2"),
        ])

    def test_failing_clause_gets_escalate_recommendation(self):
        def flaky_analyzer(ref, change_type, orig, cp, ctx):
            if ref == "1.1":
                raise RuntimeError("LLM timeout")
            return ClauseRecommendation(
                clause_reference=ref,
                recommendation="accept",
                reasoning="ok",
                playbook_reference=None,
                confidence="high",
                requires_legal_review=False,
            )

        agent, _, _ = _make_agent(self.storage, flaky_analyzer)
        agent.process_event(_alice(), _make_event())
        doc = json.loads(self.storage.retrieve(_ANALYSIS_PATH).decode())
        recs = {r["clause_reference"]: r for r in doc["recommendations"]}
        self.assertEqual(recs["1.1"]["recommendation"], "escalate")
        self.assertTrue(recs["1.1"]["requires_legal_review"])

    def test_other_clauses_still_processed_after_failure(self):
        def flaky_analyzer(ref, change_type, orig, cp, ctx):
            if ref == "1.1":
                raise RuntimeError("LLM timeout")
            return ClauseRecommendation(
                clause_reference=ref,
                recommendation="accept",
                reasoning="ok",
                playbook_reference=None,
                confidence="high",
                requires_legal_review=False,
            )

        agent, _, events = _make_agent(self.storage, flaky_analyzer)
        agent.process_event(_alice(), _make_event())
        doc = json.loads(self.storage.retrieve(_ANALYSIS_PATH).decode())
        recs = {r["clause_reference"]: r for r in doc["recommendations"]}
        self.assertEqual(recs["2.2"]["recommendation"], "accept")

    def test_event_still_emitted_after_partial_failure(self):
        def flaky_analyzer(ref, change_type, orig, cp, ctx):
            if ref == "1.1":
                raise RuntimeError("LLM timeout")
            return ClauseRecommendation(
                clause_reference=ref,
                recommendation="accept",
                reasoning="ok",
                playbook_reference=None,
                confidence="high",
                requires_legal_review=False,
            )

        agent, _, events = _make_agent(self.storage, flaky_analyzer)
        agent.process_event(_alice(), _make_event())
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, EVENT_ANALYSIS_COMPLETE)

    def test_failure_is_audited(self):
        def bad_analyzer(ref, change_type, orig, cp, ctx):
            raise RuntimeError("LLM error")

        storage = MockStorageAdapter()
        _seed_diff(storage, [_modified_entry("1.1")])
        agent, audit, _ = _make_agent(storage, bad_analyzer)
        agent.process_event(_alice(), _make_event())
        errors = [
            e for e in audit.query(agent_name="redline_analyzer")
            if e.event_type == "clause_analysis_failed"
        ]
        self.assertEqual(len(errors), 1)


class EmptyDiffTests(unittest.TestCase):
    """Diff with no changed clauses — empty recommendations, event still emitted."""

    def test_all_unchanged_produces_empty_recommendations(self):
        storage = MockStorageAdapter()
        _seed_diff(storage, [_unchanged_entry("1.1"), _unchanged_entry("1.2")])
        agent, _, events = _make_agent(storage, REJECT_ALL)
        agent.process_event(_alice(), _make_event())
        doc = json.loads(storage.retrieve(_ANALYSIS_PATH).decode())
        self.assertEqual(doc["recommendations"], [])

    def test_all_unchanged_still_emits_event(self):
        storage = MockStorageAdapter()
        _seed_diff(storage, [_unchanged_entry("1.1")])
        agent, _, events = _make_agent(storage, REJECT_ALL)
        agent.process_event(_alice(), _make_event())
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, EVENT_ANALYSIS_COMPLETE)

    def test_all_unchanged_summary_total_is_zero(self):
        storage = MockStorageAdapter()
        _seed_diff(storage, [_unchanged_entry("1.1")])
        agent, _, events = _make_agent(storage, REJECT_ALL)
        agent.process_event(_alice(), _make_event())
        self.assertEqual(events[0].payload["summary"]["total_analysed"], 0)


class WrongEventTypeTests(unittest.TestCase):
    """Non-diff-complete events are silently ignored."""

    def test_wrong_event_type_emits_nothing(self):
        storage = MockStorageAdapter()
        agent, _, events = _make_agent(storage, REJECT_ALL)
        agent.process_event(_alice(), StateEvent(
            event_type="some_other_event",
            tenant_id="alice",
            negotiation_id="neg-001",
            payload={},
            emitted_at=_EPOCH,
            emitted_by="state_manager",
        ))
        self.assertEqual(len(events), 0)
        self.assertEqual(len(storage.stored_paths), 0)


class AuditTrailTests(unittest.TestCase):
    """Audit log captures analysis lifecycle."""

    def test_analysis_completed_is_audited(self):
        storage = MockStorageAdapter()
        _seed_diff(storage, [_modified_entry("1.1")])
        agent, audit, _ = _make_agent(storage, ACCEPT_ALL)
        agent.process_event(_alice(), _make_event())
        completed = [
            e for e in audit.query(agent_name="redline_analyzer")
            if e.event_type == "analysis_completed"
        ]
        self.assertEqual(len(completed), 1)

    def test_each_clause_analysis_is_audited(self):
        storage = MockStorageAdapter()
        _seed_diff(storage, [_modified_entry("1.1"), _added_entry("4.1")])
        agent, audit, _ = _make_agent(storage, ACCEPT_ALL)
        agent.process_event(_alice(), _make_event())
        clause_events = [
            e for e in audit.query(agent_name="redline_analyzer")
            if e.event_type == "clause_analysed"
        ]
        self.assertEqual(len(clause_events), 2)

    def test_missing_diff_path_is_audited_as_warning(self):
        storage = MockStorageAdapter()
        agent, audit, _ = _make_agent(storage, REJECT_ALL)
        event = StateEvent(
            event_type=EVENT_DIFF_COMPLETE,
            tenant_id="alice",
            negotiation_id="neg-acme-001",
            payload={"round_number": 1},  # no diff_path
            emitted_at=_EPOCH,
            emitted_by="structural_diff",
        )
        agent.process_event(_alice(), event)
        warnings = [
            e for e in audit.query(agent_name="redline_analyzer")
            if e.severity == "warning"
        ]
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0].event_type, "analysis_skipped_missing_diff_path")

    def test_audit_events_carry_correct_tenant(self):
        storage = MockStorageAdapter()
        _seed_diff(storage, [_modified_entry("1.1")])
        agent, audit, _ = _make_agent(storage, ACCEPT_ALL)
        agent.process_event(
            TenantContext(tenant_id="carol"),
            _make_event(tenant_id="carol"),
        )
        events = audit.query(tenant_id="carol", agent_name="redline_analyzer")
        self.assertTrue(len(events) > 0)
        self.assertTrue(all(e.tenant_id == "carol" for e in events))

    def test_playbook_context_is_passed_to_analyzer(self):
        received_contexts: list[str] = []

        def tracking_analyzer(ref, change_type, orig, cp, ctx):
            received_contexts.append(ctx)
            return ClauseRecommendation(
                clause_reference=ref,
                recommendation="accept",
                reasoning="ok",
                playbook_reference=None,
                confidence="high",
                requires_legal_review=False,
            )

        storage = MockStorageAdapter()
        _seed_diff(storage, [_modified_entry("1.1")])
        agent, _, _ = _make_agent(storage, tracking_analyzer, playbook_context="generic agreement playbook v3")
        agent.process_event(_alice(), _make_event())
        self.assertEqual(received_contexts, ["generic agreement playbook v3"])
