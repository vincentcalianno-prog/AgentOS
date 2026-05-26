"""Unit tests for Agent 4 (Structural Diff).

Per Implementation Guide Section 7.1: synthetic fixtures only.
    Counterparty: Acme Industrial
    Tenant owners: alice, bob, carol
"""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone

from acp.layer_b.agents.structural_diff import DIFF_FILENAME, Clause, StructuralDiff
from acp.layer_b.core.adapters.in_memory_audit import InMemoryAuditLog
from acp.layer_b.core.types import (
    EVENT_DIFF_COMPLETE,
    EVENT_ROUND_READY_FOR_ANALYSIS,
    StateEvent,
    TenantContext,
)
from acp.layer_b.tests.fixtures.mock_document_parser import (
    COUNTERPARTY_CLAUSES,
    IDENTICAL_CLAUSES,
    OUTBOUND_CLAUSES,
    SINGLE_CLAUSE_COUNTERPARTY,
    SINGLE_CLAUSE_OUTBOUND,
    make_parser_for,
)
from acp.layer_b.tests.fixtures.mock_storage import MockStorageAdapter

_EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)
_STORAGE_FOLDER = "tenant-root/generic-agreement/acme-industrial/round_1"
_COUNTERPARTY_PATH = f"{_STORAGE_FOLDER}/20260101T000000Z_att-001.bin"
_OUTBOUND_PATH = "tenant-root/generic-agreement/acme-industrial/round_0/20251201T000000Z_outbound.bin"


def _alice() -> TenantContext:
    return TenantContext(tenant_id="alice")


def _make_agent(
    storage: MockStorageAdapter,
    outbound_clauses: list[Clause] | None = None,
    counterparty_clauses: list[Clause] | None = None,
) -> tuple[StructuralDiff, InMemoryAuditLog, list[StateEvent]]:
    audit = InMemoryAuditLog()
    captured: list[StateEvent] = []

    # Single parser handles both paths by returning the respective clause list.
    # In tests we route via storage content — but since parse_document ignores
    # bytes, we use a combined parser keyed on call order via closure.
    _call_count = [0]
    _out = outbound_clauses or []
    _cp = counterparty_clauses or []

    def _parser(content: bytes) -> list[Clause]:
        # First call = counterparty, second call = outbound (matches process_event order)
        idx = _call_count[0]
        _call_count[0] += 1
        return _cp if idx == 0 else _out

    agent = StructuralDiff(
        storage=storage,
        audit=audit,
        config={},
        parse_document=_parser,
    )
    agent.subscribe(captured.append)
    return agent, audit, captured


def _make_event(
    negotiation_id: str = "neg-acme-001",
    tenant_id: str = "alice",
    counterparty_path: str = _COUNTERPARTY_PATH,
    outbound_path: str | None = _OUTBOUND_PATH,
    storage_folder: str = _STORAGE_FOLDER,
    round_number: int = 1,
) -> StateEvent:
    return StateEvent(
        event_type=EVENT_ROUND_READY_FOR_ANALYSIS,
        tenant_id=tenant_id,
        negotiation_id=negotiation_id,
        workflow_id="contract_redline",
        payload={
            "counterparty_document_path": counterparty_path,
            "outbound_document_path": outbound_path,
            "storage_folder_path": storage_folder,
            "round_number": round_number,
        },
        emitted_at=_EPOCH,
        emitted_by="state_manager",
    )


def _seed_storage(
    storage: MockStorageAdapter,
    counterparty_path: str = _COUNTERPARTY_PATH,
    outbound_path: str | None = _OUTBOUND_PATH,
) -> None:
    storage.store(counterparty_path, b"COUNTERPARTY_BYTES")
    if outbound_path:
        storage.store(outbound_path, b"OUTBOUND_BYTES")


class UnchangedClausesTests(unittest.TestCase):
    """All clauses identical — diff should show only 'unchanged' entries."""

    def setUp(self):
        self.storage = MockStorageAdapter()
        _seed_storage(self.storage)
        self.agent, self.audit, self.events = _make_agent(
            self.storage,
            outbound_clauses=IDENTICAL_CLAUSES,
            counterparty_clauses=IDENTICAL_CLAUSES,
        )

    def test_all_entries_are_unchanged(self):
        self.agent.process_event(_alice(), _make_event())
        diff = self._load_diff()
        self.assertTrue(all(e["change_type"] == "unchanged" for e in diff["entries"]))

    def test_entry_count_matches_clause_count(self):
        self.agent.process_event(_alice(), _make_event())
        diff = self._load_diff()
        self.assertEqual(len(diff["entries"]), len(IDENTICAL_CLAUSES))

    def test_character_delta_is_zero_for_unchanged(self):
        self.agent.process_event(_alice(), _make_event())
        diff = self._load_diff()
        self.assertTrue(all(e["character_delta"] == 0 for e in diff["entries"]))

    def _load_diff(self) -> dict:
        path = f"{_STORAGE_FOLDER}/{DIFF_FILENAME}"
        return json.loads(self.storage.retrieve(path).decode())


class ModifiedClauseTests(unittest.TestCase):
    """A single clause changed between outbound and counterparty versions."""

    def setUp(self):
        self.storage = MockStorageAdapter()
        _seed_storage(self.storage)
        self.agent, self.audit, self.events = _make_agent(
            self.storage,
            outbound_clauses=SINGLE_CLAUSE_OUTBOUND,
            counterparty_clauses=SINGLE_CLAUSE_COUNTERPARTY,
        )

    def test_entry_is_modified(self):
        self.agent.process_event(_alice(), _make_event())
        diff = self._load_diff()
        self.assertEqual(diff["entries"][0]["change_type"], "modified")

    def test_original_text_is_outbound_text(self):
        self.agent.process_event(_alice(), _make_event())
        diff = self._load_diff()
        self.assertEqual(diff["entries"][0]["original_text"], SINGLE_CLAUSE_OUTBOUND[0].text)

    def test_counterparty_text_is_counterparty_text(self):
        self.agent.process_event(_alice(), _make_event())
        diff = self._load_diff()
        self.assertEqual(diff["entries"][0]["counterparty_text"], SINGLE_CLAUSE_COUNTERPARTY[0].text)

    def test_character_delta_is_correct(self):
        self.agent.process_event(_alice(), _make_event())
        diff = self._load_diff()
        expected = len(SINGLE_CLAUSE_COUNTERPARTY[0].text) - len(SINGLE_CLAUSE_OUTBOUND[0].text)
        self.assertEqual(diff["entries"][0]["character_delta"], expected)

    def _load_diff(self) -> dict:
        path = f"{_STORAGE_FOLDER}/{DIFF_FILENAME}"
        return json.loads(self.storage.retrieve(path).decode())


class AddedClauseTests(unittest.TestCase):
    """Counterparty introduces a clause not present in the outbound version."""

    def setUp(self):
        self.storage = MockStorageAdapter()
        _seed_storage(self.storage)
        # outbound has no clauses; counterparty adds one
        self.agent, self.audit, self.events = _make_agent(
            self.storage,
            outbound_clauses=[],
            counterparty_clauses=SINGLE_CLAUSE_COUNTERPARTY,
        )

    def test_entry_is_added(self):
        self.agent.process_event(_alice(), _make_event())
        diff = self._load_diff()
        self.assertEqual(diff["entries"][0]["change_type"], "added")

    def test_original_text_is_empty_for_added(self):
        self.agent.process_event(_alice(), _make_event())
        diff = self._load_diff()
        self.assertEqual(diff["entries"][0]["original_text"], "")

    def _load_diff(self) -> dict:
        path = f"{_STORAGE_FOLDER}/{DIFF_FILENAME}"
        return json.loads(self.storage.retrieve(path).decode())


class DeletedClauseTests(unittest.TestCase):
    """Counterparty removes a clause present in the outbound version."""

    def setUp(self):
        self.storage = MockStorageAdapter()
        _seed_storage(self.storage)
        # outbound has one clause; counterparty removes it
        self.agent, self.audit, self.events = _make_agent(
            self.storage,
            outbound_clauses=SINGLE_CLAUSE_OUTBOUND,
            counterparty_clauses=[],
        )

    def test_entry_is_deleted(self):
        self.agent.process_event(_alice(), _make_event())
        diff = self._load_diff()
        self.assertEqual(diff["entries"][0]["change_type"], "deleted")

    def test_counterparty_text_is_empty_for_deleted(self):
        self.agent.process_event(_alice(), _make_event())
        diff = self._load_diff()
        self.assertEqual(diff["entries"][0]["counterparty_text"], "")

    def _load_diff(self) -> dict:
        path = f"{_STORAGE_FOLDER}/{DIFF_FILENAME}"
        return json.loads(self.storage.retrieve(path).decode())


class MixedDiffTests(unittest.TestCase):
    """Full Acme Industrial scenario: 2 modified, 2 unchanged, 1 deleted, 1 added."""

    def setUp(self):
        self.storage = MockStorageAdapter()
        _seed_storage(self.storage)
        self.agent, self.audit, self.events = _make_agent(
            self.storage,
            outbound_clauses=OUTBOUND_CLAUSES,
            counterparty_clauses=COUNTERPARTY_CLAUSES,
        )
        self.agent.process_event(_alice(), _make_event())
        diff_path = f"{_STORAGE_FOLDER}/{DIFF_FILENAME}"
        self.diff = json.loads(self.storage.retrieve(diff_path).decode())
        self.entries_by_ref = {e["clause_reference"]: e for e in self.diff["entries"]}

    def test_clause_1_1_is_modified(self):
        self.assertEqual(self.entries_by_ref["1.1"]["change_type"], "modified")

    def test_clause_1_2_is_unchanged(self):
        self.assertEqual(self.entries_by_ref["1.2"]["change_type"], "unchanged")

    def test_clause_2_1_is_unchanged(self):
        self.assertEqual(self.entries_by_ref["2.1"]["change_type"], "unchanged")

    def test_clause_2_2_is_modified(self):
        self.assertEqual(self.entries_by_ref["2.2"]["change_type"], "modified")

    def test_clause_3_1_is_deleted(self):
        self.assertEqual(self.entries_by_ref["3.1"]["change_type"], "deleted")

    def test_clause_4_1_is_added(self):
        self.assertEqual(self.entries_by_ref["4.1"]["change_type"], "added")

    def test_total_entry_count(self):
        # 5 counterparty + 1 deletion = 6 entries
        self.assertEqual(len(self.diff["entries"]), 6)


class RoundOneNoOutboundTests(unittest.TestCase):
    """Round 1: no outbound document path — all counterparty clauses are additions."""

    def setUp(self):
        self.storage = MockStorageAdapter()
        # Only seed counterparty; no outbound
        self.storage.store(_COUNTERPARTY_PATH, b"COUNTERPARTY_BYTES")
        self.agent, self.audit, self.events = _make_agent(
            self.storage,
            outbound_clauses=[],
            counterparty_clauses=SINGLE_CLAUSE_COUNTERPARTY,
        )

    def test_all_entries_are_added_when_no_outbound(self):
        event = _make_event(outbound_path=None)
        self.agent.process_event(_alice(), event)
        diff_path = f"{_STORAGE_FOLDER}/{DIFF_FILENAME}"
        diff = json.loads(self.storage.retrieve(diff_path).decode())
        self.assertTrue(all(e["change_type"] == "added" for e in diff["entries"]))

    def test_diff_is_persisted_when_no_outbound(self):
        event = _make_event(outbound_path=None)
        self.agent.process_event(_alice(), event)
        diff_path = f"{_STORAGE_FOLDER}/{DIFF_FILENAME}"
        self.assertTrue(self.storage.exists(diff_path))


class StoragePersistenceTests(unittest.TestCase):
    """structural_diff.json is written to the correct path."""

    def test_diff_written_to_storage_folder(self):
        storage = MockStorageAdapter()
        _seed_storage(storage)
        agent, _, _ = _make_agent(storage, IDENTICAL_CLAUSES, IDENTICAL_CLAUSES)
        agent.process_event(_alice(), _make_event())
        expected_path = f"{_STORAGE_FOLDER}/{DIFF_FILENAME}"
        self.assertTrue(storage.exists(expected_path))

    def test_diff_json_contains_negotiation_id(self):
        storage = MockStorageAdapter()
        _seed_storage(storage)
        agent, _, _ = _make_agent(storage, IDENTICAL_CLAUSES, IDENTICAL_CLAUSES)
        agent.process_event(_alice(), _make_event(negotiation_id="neg-acme-001"))
        diff_path = f"{_STORAGE_FOLDER}/{DIFF_FILENAME}"
        diff = json.loads(storage.retrieve(diff_path).decode())
        self.assertEqual(diff["negotiation_id"], "neg-acme-001")

    def test_diff_json_contains_round_number(self):
        storage = MockStorageAdapter()
        _seed_storage(storage)
        agent, _, _ = _make_agent(storage, IDENTICAL_CLAUSES, IDENTICAL_CLAUSES)
        agent.process_event(_alice(), _make_event(round_number=2))
        diff_path = f"{_STORAGE_FOLDER}/{DIFF_FILENAME}"
        diff = json.loads(storage.retrieve(diff_path).decode())
        self.assertEqual(diff["round_number"], 2)


class EventEmissionTests(unittest.TestCase):
    """EVENT_DIFF_COMPLETE is emitted with correct payload."""

    def setUp(self):
        self.storage = MockStorageAdapter()
        _seed_storage(self.storage)
        self.agent, self.audit, self.events = _make_agent(
            self.storage,
            outbound_clauses=OUTBOUND_CLAUSES,
            counterparty_clauses=COUNTERPARTY_CLAUSES,
        )
        self.agent.process_event(_alice(), _make_event())

    def test_diff_complete_event_is_emitted(self):
        self.assertEqual(len(self.events), 1)
        self.assertEqual(self.events[0].event_type, EVENT_DIFF_COMPLETE)

    def test_event_carries_diff_path(self):
        expected = f"{_STORAGE_FOLDER}/{DIFF_FILENAME}"
        self.assertEqual(self.events[0].payload["diff_path"], expected)

    def test_event_carries_round_number(self):
        self.assertEqual(self.events[0].payload["round_number"], 1)

    def test_event_carries_total_clauses(self):
        self.assertIn("total_clauses", self.events[0].payload)
        self.assertGreater(self.events[0].payload["total_clauses"], 0)

    def test_event_carries_changed_clauses_count(self):
        # 2 modified + 1 deleted + 1 added = 4 changed
        self.assertEqual(self.events[0].payload["changed_clauses"], 4)

    def test_event_carries_correct_tenant_and_negotiation(self):
        self.assertEqual(self.events[0].tenant_id, "alice")
        self.assertEqual(self.events[0].negotiation_id, "neg-acme-001")


class AuditTrailTests(unittest.TestCase):
    """Audit log captures diff lifecycle events."""

    def test_successful_diff_is_audited(self):
        storage = MockStorageAdapter()
        _seed_storage(storage)
        agent, audit, _ = _make_agent(storage, IDENTICAL_CLAUSES, IDENTICAL_CLAUSES)
        agent.process_event(_alice(), _make_event())
        completed = [
            e for e in audit.query(agent_name="structural_diff")
            if e.event_type == "diff_completed"
        ]
        self.assertEqual(len(completed), 1)

    def test_missing_counterparty_path_is_audited_as_warning(self):
        storage = MockStorageAdapter()
        agent, audit, _ = _make_agent(storage, [], [])
        event = StateEvent(
            event_type=EVENT_ROUND_READY_FOR_ANALYSIS,
            tenant_id="alice",
            negotiation_id="neg-acme-001",
            workflow_id="contract_redline",
            payload={"storage_folder_path": _STORAGE_FOLDER, "round_number": 1},
            emitted_at=_EPOCH,
            emitted_by="state_manager",
        )
        agent.process_event(_alice(), event)
        warnings = [
            e for e in audit.query(agent_name="structural_diff")
            if e.severity == "warning"
        ]
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0].event_type, "diff_skipped_missing_payload")

    def test_audit_events_carry_correct_tenant(self):
        storage = MockStorageAdapter()
        _seed_storage(storage)
        agent, audit, _ = _make_agent(storage, IDENTICAL_CLAUSES, IDENTICAL_CLAUSES)
        agent.process_event(
            TenantContext(tenant_id="bob"),
            _make_event(tenant_id="bob"),
        )
        events = audit.query(tenant_id="bob", agent_name="structural_diff")
        self.assertTrue(len(events) > 0)
        self.assertTrue(all(e.tenant_id == "bob" for e in events))


class WrongEventTypeTests(unittest.TestCase):
    """Non-analysis events are silently ignored."""

    def test_wrong_event_type_emits_nothing(self):
        storage = MockStorageAdapter()
        agent, _, events = _make_agent(storage, [], [])
        agent.process_event(_alice(), StateEvent(
            event_type="some_other_event",
            tenant_id="alice",
            negotiation_id="neg-001",
            workflow_id="contract_redline",
            payload={},
            emitted_at=_EPOCH,
            emitted_by="state_manager",
        ))
        self.assertEqual(len(events), 0)
        self.assertEqual(len(storage.stored_paths), 0)
