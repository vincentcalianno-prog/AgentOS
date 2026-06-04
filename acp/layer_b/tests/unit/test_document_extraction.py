"""Unit tests for Agent 2 (Document Extraction).

Per Implementation Guide Section 7.1: synthetic fixtures only.
    Counterparties: Acme Industrial, Beta Manufacturing, Gamma Components
    Tenant owners: alice, bob, carol
"""

from __future__ import annotations

import hashlib
import unittest
from datetime import datetime, timezone

from acp.layer_b.agents.document_extraction import DocumentExtractor
from acp.layer_b.core.adapters.in_memory_audit import InMemoryAuditLog
from acp.layer_b.core.types import (
    EVENT_DOCUMENT_EXTRACTED,
    EVENT_DOCUMENT_EXTRACTION_REQUIRED,
    StateEvent,
    TenantContext,
)
from acp.layer_b.tests.fixtures.mock_inbox import MockInboxAdapter
from acp.layer_b.tests.fixtures.mock_storage import MockStorageAdapter

_EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)
_SYNTHETIC_CONTENT = b"SYNTHETIC CONTRACT DOCUMENT BYTES - ACME INDUSTRIAL"
_SYNTHETIC_CONTENT_2 = b"SYNTHETIC CONTRACT DOCUMENT BYTES - SECOND ATTACHMENT"


def _make_extractor(
    inbox: MockInboxAdapter,
    storage: MockStorageAdapter,
    config: dict | None = None,
    extract_metadata=None,
) -> tuple[DocumentExtractor, InMemoryAuditLog, list[StateEvent]]:
    audit = InMemoryAuditLog()
    captured: list[StateEvent] = []

    extractor = DocumentExtractor(
        inbox=inbox,
        storage=storage,
        audit=audit,
        config=config or {"storage_root": "tenant-root"},
        extract_metadata=extract_metadata or (lambda b: (0, 0, 0)),
    )
    extractor.subscribe(captured.append)
    return extractor, audit, captured


def _make_extraction_event(
    negotiation_id: str = "neg-acme-001",
    tenant_id: str = "alice",
    message_id: str = "msg-001",
    attachment_ids: list | None = None,
    round_number: int = 1,
    contract_type: str = "generic-agreement",
    counterparty_ref: str = "acme-industrial",
) -> StateEvent:
    return StateEvent(
        event_type=EVENT_DOCUMENT_EXTRACTION_REQUIRED,
        tenant_id=tenant_id,
        negotiation_id=negotiation_id,
        workflow_id="contract_redline",
        payload={
            "inbox_message_id": message_id,
            "inbox_thread_id": negotiation_id,
            "attachment_ids": attachment_ids if attachment_ids is not None else ["att-001"],
            "round_number": round_number,
            "contract_type": contract_type,
            "counterparty_ref": counterparty_ref,
        },
        emitted_at=_EPOCH,
        emitted_by="state_manager",
    )


def _alice() -> TenantContext:
    return TenantContext(tenant_id="alice")


class HappyPathTests(unittest.TestCase):
    """Attachment is fetched, stored, fingerprinted, and event emitted."""

    def setUp(self):
        self.inbox = MockInboxAdapter()
        self.inbox.add_attachment("att-001", _SYNTHETIC_CONTENT)
        self.storage = MockStorageAdapter()
        self.extractor, self.audit, self.events = _make_extractor(
            self.inbox, self.storage
        )

    def test_file_is_stored(self):
        self.extractor.process_event(_alice(), _make_extraction_event())
        self.assertEqual(len(self.storage.stored_paths), 1)

    def test_stored_content_matches_original(self):
        self.extractor.process_event(_alice(), _make_extraction_event())
        path = next(iter(self.storage.stored_paths))
        self.assertEqual(self.storage.retrieve(path), _SYNTHETIC_CONTENT)

    def test_document_extracted_event_is_emitted(self):
        self.extractor.process_event(_alice(), _make_extraction_event())
        self.assertEqual(len(self.events), 1)
        self.assertEqual(self.events[0].event_type, EVENT_DOCUMENT_EXTRACTED)

    def test_emitted_event_carries_storage_path(self):
        self.extractor.process_event(_alice(), _make_extraction_event())
        path = next(iter(self.storage.stored_paths))
        self.assertEqual(self.events[0].payload["storage_path"], path)

    def test_emitted_event_carries_correct_tenant_and_negotiation(self):
        self.extractor.process_event(_alice(), _make_extraction_event(
            negotiation_id="neg-acme-001", tenant_id="alice"
        ))
        self.assertEqual(self.events[0].tenant_id, "alice")
        self.assertEqual(self.events[0].negotiation_id, "neg-acme-001")

    def test_emitted_event_carries_round_number(self):
        self.extractor.process_event(_alice(), _make_extraction_event(round_number=3))
        self.assertEqual(self.events[0].payload["round_number"], 3)

    def test_emitted_event_carries_storage_folder_path(self):
        self.extractor.process_event(_alice(), _make_extraction_event())
        path = self.events[0].payload["storage_path"]
        folder = self.events[0].payload["storage_folder_path"]
        self.assertTrue(path.startswith(folder))
        self.assertNotEqual(path, folder)


class PathStructureTests(unittest.TestCase):
    """Canonical path contains expected components."""

    def setUp(self):
        self.inbox = MockInboxAdapter()
        self.inbox.add_attachment("att-001", _SYNTHETIC_CONTENT)
        self.storage = MockStorageAdapter()
        self.extractor, _, _ = _make_extractor(
            self.inbox, self.storage,
            config={"storage_root": "tenant-root"},
        )

    def test_path_starts_with_storage_root(self):
        self.extractor.process_event(_alice(), _make_extraction_event(
            contract_type="generic-agreement",
            counterparty_ref="acme-industrial",
            round_number=1,
        ))
        path = next(iter(self.storage.stored_paths))
        self.assertTrue(path.startswith("tenant-root/"))

    def test_path_contains_slugified_contract_type(self):
        self.extractor.process_event(_alice(), _make_extraction_event(
            contract_type="Generic Agreement",
        ))
        path = next(iter(self.storage.stored_paths))
        self.assertIn("generic-agreement", path)

    def test_path_contains_slugified_counterparty_ref(self):
        self.extractor.process_event(_alice(), _make_extraction_event(
            counterparty_ref="Acme Industrial",
        ))
        path = next(iter(self.storage.stored_paths))
        self.assertIn("acme-industrial", path)

    def test_path_contains_round_directory(self):
        self.extractor.process_event(_alice(), _make_extraction_event(round_number=2))
        path = next(iter(self.storage.stored_paths))
        self.assertIn("round_2", path)

    def test_path_ends_with_bin_extension(self):
        self.extractor.process_event(_alice(), _make_extraction_event())
        path = next(iter(self.storage.stored_paths))
        self.assertTrue(path.endswith(".bin"))


class FingerprintTests(unittest.TestCase):
    """Fingerprint in emitted event matches the stored content."""

    def test_sha256_matches_content(self):
        inbox = MockInboxAdapter()
        inbox.add_attachment("att-001", _SYNTHETIC_CONTENT)
        storage = MockStorageAdapter()
        extractor, _, events = _make_extractor(inbox, storage)
        extractor.process_event(_alice(), _make_extraction_event())

        expected_hash = hashlib.sha256(_SYNTHETIC_CONTENT).hexdigest()
        self.assertEqual(events[0].payload["fingerprint"]["sha256_hash"], expected_hash)

    def test_file_size_matches_content_length(self):
        inbox = MockInboxAdapter()
        inbox.add_attachment("att-001", _SYNTHETIC_CONTENT)
        storage = MockStorageAdapter()
        extractor, _, events = _make_extractor(inbox, storage)
        extractor.process_event(_alice(), _make_extraction_event())

        self.assertEqual(
            events[0].payload["fingerprint"]["file_size_bytes"],
            len(_SYNTHETIC_CONTENT),
        )

    def test_injected_metadata_extractor_is_used(self):
        inbox = MockInboxAdapter()
        inbox.add_attachment("att-001", _SYNTHETIC_CONTENT)
        storage = MockStorageAdapter()
        extractor, _, events = _make_extractor(
            inbox, storage,
            extract_metadata=lambda b: (12, 3, 500),
        )
        extractor.process_event(_alice(), _make_extraction_event())

        fp = events[0].payload["fingerprint"]
        self.assertEqual(fp["clause_count"], 12)
        self.assertEqual(fp["page_count"], 3)
        self.assertEqual(fp["word_count"], 500)

    def test_metadata_extractor_failure_defaults_to_zeros(self):
        def bad_extractor(content):
            raise RuntimeError("docx parse failed")

        inbox = MockInboxAdapter()
        inbox.add_attachment("att-001", _SYNTHETIC_CONTENT)
        storage = MockStorageAdapter()
        extractor, _, events = _make_extractor(
            inbox, storage, extract_metadata=bad_extractor,
        )
        extractor.process_event(_alice(), _make_extraction_event())

        fp = events[0].payload["fingerprint"]
        self.assertEqual(fp["clause_count"], 0)
        self.assertEqual(fp["page_count"], 0)
        self.assertEqual(fp["word_count"], 0)
        # Event is still emitted — extractor failure is non-fatal
        self.assertEqual(len(events), 1)


class MultipleAttachmentTests(unittest.TestCase):
    """Multiple attachments in one event are each stored and emitted independently."""

    def test_two_attachments_produce_two_stored_files(self):
        inbox = MockInboxAdapter()
        inbox.add_attachment("att-001", _SYNTHETIC_CONTENT)
        inbox.add_attachment("att-002", _SYNTHETIC_CONTENT_2)
        storage = MockStorageAdapter()
        extractor, _, events = _make_extractor(inbox, storage)

        extractor.process_event(_alice(), _make_extraction_event(
            attachment_ids=["att-001", "att-002"]
        ))
        self.assertEqual(len(storage.stored_paths), 2)

    def test_two_attachments_produce_two_events(self):
        inbox = MockInboxAdapter()
        inbox.add_attachment("att-001", _SYNTHETIC_CONTENT)
        inbox.add_attachment("att-002", _SYNTHETIC_CONTENT_2)
        storage = MockStorageAdapter()
        extractor, _, events = _make_extractor(inbox, storage)

        extractor.process_event(_alice(), _make_extraction_event(
            attachment_ids=["att-001", "att-002"]
        ))
        self.assertEqual(len(events), 2)
        self.assertTrue(all(e.event_type == EVENT_DOCUMENT_EXTRACTED for e in events))

    def test_two_attachments_stored_at_distinct_paths(self):
        inbox = MockInboxAdapter()
        inbox.add_attachment("att-001", _SYNTHETIC_CONTENT)
        inbox.add_attachment("att-002", _SYNTHETIC_CONTENT_2)
        storage = MockStorageAdapter()
        extractor, _, events = _make_extractor(inbox, storage)

        extractor.process_event(_alice(), _make_extraction_event(
            attachment_ids=["att-001", "att-002"]
        ))
        paths = [e.payload["storage_path"] for e in events]
        self.assertEqual(len(set(paths)), 2)

    def test_one_failed_attachment_does_not_block_others(self):
        inbox = MockInboxAdapter()
        # att-001 is missing — fetch will raise
        inbox.add_attachment("att-002", _SYNTHETIC_CONTENT_2)
        storage = MockStorageAdapter()
        extractor, audit, events = _make_extractor(inbox, storage)

        extractor.process_event(_alice(), _make_extraction_event(
            attachment_ids=["att-001", "att-002"]
        ))
        # att-002 still stored despite att-001 failure
        self.assertEqual(len(events), 1)
        self.assertEqual(len(storage.stored_paths), 1)


class NoAttachmentTests(unittest.TestCase):
    """Empty attachment list is handled gracefully."""

    def test_no_attachments_emits_no_event(self):
        inbox = MockInboxAdapter()
        storage = MockStorageAdapter()
        extractor, _, events = _make_extractor(inbox, storage)

        extractor.process_event(_alice(), _make_extraction_event(attachment_ids=[]))
        self.assertEqual(len(events), 0)

    def test_no_attachments_is_audited_as_warning(self):
        inbox = MockInboxAdapter()
        storage = MockStorageAdapter()
        extractor, audit, _ = _make_extractor(inbox, storage)

        extractor.process_event(_alice(), _make_extraction_event(attachment_ids=[]))
        warnings = [
            e for e in audit.query(agent_name="document_extractor")
            if e.severity == "warning"
        ]
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0].event_type, "extraction_skipped_no_attachments")


class FetchFailureTests(unittest.TestCase):
    """Inbox fetch failures are audited and skipped."""

    def test_missing_attachment_is_audited(self):
        inbox = MockInboxAdapter()  # att-001 not registered
        storage = MockStorageAdapter()
        extractor, audit, _ = _make_extractor(inbox, storage)

        extractor.process_event(_alice(), _make_extraction_event())
        errors = [
            e for e in audit.query(agent_name="document_extractor")
            if e.event_type == "attachment_fetch_failed"
        ]
        self.assertEqual(len(errors), 1)

    def test_missing_attachment_emits_no_extracted_event(self):
        inbox = MockInboxAdapter()
        storage = MockStorageAdapter()
        extractor, _, events = _make_extractor(inbox, storage)

        extractor.process_event(_alice(), _make_extraction_event())
        self.assertEqual(len(events), 0)

    def test_missing_attachment_stores_nothing(self):
        inbox = MockInboxAdapter()
        storage = MockStorageAdapter()
        extractor, _, _ = _make_extractor(inbox, storage)

        extractor.process_event(_alice(), _make_extraction_event())
        self.assertEqual(len(storage.stored_paths), 0)


class WrongEventTypeTests(unittest.TestCase):
    """Non-extraction events are silently ignored."""

    def test_wrong_event_type_is_ignored(self):
        inbox = MockInboxAdapter()
        storage = MockStorageAdapter()
        extractor, _, events = _make_extractor(inbox, storage)

        wrong_event = StateEvent(
            event_type="some_other_event",
            tenant_id="alice",
            negotiation_id="neg-001",
            workflow_id="contract_redline",
            payload={},
            emitted_at=_EPOCH,
            emitted_by="state_manager",
        )
        extractor.process_event(_alice(), wrong_event)
        self.assertEqual(len(events), 0)
        self.assertEqual(len(storage.stored_paths), 0)


class AuditTrailTests(unittest.TestCase):
    """Audit log captures extraction lifecycle events."""

    def test_successful_extraction_is_audited(self):
        inbox = MockInboxAdapter()
        inbox.add_attachment("att-001", _SYNTHETIC_CONTENT)
        storage = MockStorageAdapter()
        extractor, audit, _ = _make_extractor(inbox, storage)

        extractor.process_event(_alice(), _make_extraction_event())
        stored_events = [
            e for e in audit.query(agent_name="document_extractor")
            if e.event_type == "attachment_stored"
        ]
        self.assertEqual(len(stored_events), 1)

    def test_extraction_completed_summary_is_audited(self):
        inbox = MockInboxAdapter()
        inbox.add_attachment("att-001", _SYNTHETIC_CONTENT)
        storage = MockStorageAdapter()
        extractor, audit, _ = _make_extractor(inbox, storage)

        extractor.process_event(_alice(), _make_extraction_event())
        completed = [
            e for e in audit.query(agent_name="document_extractor")
            if e.event_type == "extraction_completed"
        ]
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0].payload["attachments_stored"], 1)

    def test_audit_events_carry_correct_tenant(self):
        inbox = MockInboxAdapter()
        storage = MockStorageAdapter()
        extractor, audit, _ = _make_extractor(inbox, storage)

        extractor.process_event(
            TenantContext(tenant_id="carol"),
            _make_extraction_event(tenant_id="carol", attachment_ids=[]),
        )
        events = audit.query(tenant_id="carol", agent_name="document_extractor")
        self.assertTrue(len(events) > 0)
        self.assertTrue(all(e.tenant_id == "carol" for e in events))
