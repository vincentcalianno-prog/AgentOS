"""Unit tests for Agent 1 (Email Watcher).

Per Implementation Guide Section 7.1: synthetic fixtures only.
    Counterparties: Acme Industrial, Beta Manufacturing, Gamma Components
    Tenant owners: alice, bob, carol
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from acp.layer_b.agents.email_watcher import (
    CLASSIFICATION_IRRELEVANT,
    CLASSIFICATION_NON_REDLINE_CONTRACT,
    CLASSIFICATION_REDLINE,
    EmailWatcher,
)
from acp.layer_b.core.adapters.in_memory_audit import InMemoryAuditLog
from acp.layer_b.core.types import (
    EVENT_INBOUND_NON_REDLINE,
    EVENT_INBOUND_REDLINE_RECEIVED,
    StateEvent,
    TenantContext,
)
from acp.layer_b.tests.fixtures.mock_inbox import (
    MockInboxAdapter,
    make_irrelevant_message,
    make_non_redline_message,
    make_redline_message,
)

_EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _make_watcher(
    inbox: MockInboxAdapter,
    classify_fn=None,
    config: dict | None = None,
) -> tuple[EmailWatcher, InMemoryAuditLog, list[StateEvent]]:
    """Return (watcher, audit_log, captured_events)."""
    audit = InMemoryAuditLog()
    captured: list[StateEvent] = []

    if classify_fn is None:
        classify_fn = lambda subject, snippet: CLASSIFICATION_IRRELEVANT

    watcher = EmailWatcher(
        inbox=inbox,
        classify=classify_fn,
        audit=audit,
        config=config or {},
    )
    watcher.subscribe(captured.append)
    return watcher, audit, captured


def _alice() -> TenantContext:
    return TenantContext(tenant_id="alice")


class ClassificationRoutingTests(unittest.TestCase):
    """Correct event type is emitted for each classification outcome."""

    def test_redline_message_emits_inbound_redline_event(self):
        msg = make_redline_message(thread_id="thread-acme-001")
        inbox = MockInboxAdapter([msg])
        watcher, _, events = _make_watcher(
            inbox,
            classify_fn=lambda s, b: CLASSIFICATION_REDLINE,
        )
        watcher.poll(_alice(), since=_EPOCH, active_thread_ids={"thread-acme-001"})

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, EVENT_INBOUND_REDLINE_RECEIVED)

    def test_non_redline_message_emits_non_redline_event(self):
        msg = make_non_redline_message(thread_id="thread-beta-001")
        inbox = MockInboxAdapter([msg])
        watcher, _, events = _make_watcher(
            inbox,
            classify_fn=lambda s, b: CLASSIFICATION_NON_REDLINE_CONTRACT,
        )
        watcher.poll(_alice(), since=_EPOCH, active_thread_ids={"thread-beta-001"})

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, EVENT_INBOUND_NON_REDLINE)

    def test_irrelevant_message_emits_no_event(self):
        msg = make_irrelevant_message(thread_id="thread-unrelated-001")
        inbox = MockInboxAdapter([msg])
        watcher, _, events = _make_watcher(
            inbox,
            classify_fn=lambda s, b: CLASSIFICATION_IRRELEVANT,
        )
        watcher.poll(_alice(), since=_EPOCH, active_thread_ids={"thread-unrelated-001"})

        self.assertEqual(len(events), 0)

    def test_irrelevant_message_is_still_marked_processed(self):
        msg = make_irrelevant_message(message_id="msg-irr-01", thread_id="thread-unrelated-001")
        inbox = MockInboxAdapter([msg])
        watcher, _, _ = _make_watcher(
            inbox,
            classify_fn=lambda s, b: CLASSIFICATION_IRRELEVANT,
        )
        watcher.poll(_alice(), since=_EPOCH, active_thread_ids={"thread-unrelated-001"})

        self.assertIn("msg-irr-01", inbox.processed)


class EventShapeTests(unittest.TestCase):
    """Emitted events carry the correct payload fields."""

    def test_redline_event_payload_fields(self):
        msg = make_redline_message(
            message_id="msg-r-01",
            thread_id="thread-acme-001",
            sender="contracts@acmeindustrial.example",
            attachment_ids=("att-001", "att-002"),
        )
        inbox = MockInboxAdapter([msg])
        watcher, _, events = _make_watcher(
            inbox,
            classify_fn=lambda s, b: CLASSIFICATION_REDLINE,
        )
        watcher.poll(_alice(), since=_EPOCH, active_thread_ids={"thread-acme-001"})

        payload = events[0].payload
        self.assertEqual(payload["inbox_message_id"], "msg-r-01")
        self.assertEqual(payload["inbox_thread_id"], "thread-acme-001")
        self.assertEqual(payload["sender"], "contracts@acmeindustrial.example")
        self.assertTrue(payload["has_attachment"])
        self.assertEqual(payload["attachment_ids"], ["att-001", "att-002"])

    def test_redline_event_tenant_and_emitter(self):
        msg = make_redline_message(thread_id="thread-acme-001")
        inbox = MockInboxAdapter([msg])
        watcher, _, events = _make_watcher(
            inbox,
            classify_fn=lambda s, b: CLASSIFICATION_REDLINE,
        )
        watcher.poll(_alice(), since=_EPOCH, active_thread_ids={"thread-acme-001"})

        self.assertEqual(events[0].tenant_id, "alice")
        self.assertEqual(events[0].emitted_by, "email_watcher")

    def test_non_redline_event_payload_fields(self):
        msg = make_non_redline_message(
            message_id="msg-nr-01",
            thread_id="thread-beta-001",
            sender="legal@betamanufacturing.example",
        )
        inbox = MockInboxAdapter([msg])
        watcher, _, events = _make_watcher(
            inbox,
            classify_fn=lambda s, b: CLASSIFICATION_NON_REDLINE_CONTRACT,
        )
        watcher.poll(_alice(), since=_EPOCH, active_thread_ids={"thread-beta-001"})

        payload = events[0].payload
        self.assertEqual(payload["inbox_message_id"], "msg-nr-01")
        self.assertEqual(payload["inbox_thread_id"], "thread-beta-001")
        self.assertEqual(payload["sender"], "legal@betamanufacturing.example")


class MarkProcessedTests(unittest.TestCase):
    """Every fetched message is marked processed exactly once."""

    def test_redline_message_is_marked_processed(self):
        msg = make_redline_message(message_id="msg-r-01", thread_id="thread-acme-001")
        inbox = MockInboxAdapter([msg])
        watcher, _, _ = _make_watcher(
            inbox, classify_fn=lambda s, b: CLASSIFICATION_REDLINE,
        )
        watcher.poll(_alice(), since=_EPOCH, active_thread_ids={"thread-acme-001"})
        self.assertIn("msg-r-01", inbox.processed)

    def test_non_redline_message_is_marked_processed(self):
        msg = make_non_redline_message(message_id="msg-nr-01", thread_id="thread-beta-001")
        inbox = MockInboxAdapter([msg])
        watcher, _, _ = _make_watcher(
            inbox, classify_fn=lambda s, b: CLASSIFICATION_NON_REDLINE_CONTRACT,
        )
        watcher.poll(_alice(), since=_EPOCH, active_thread_ids={"thread-beta-001"})
        self.assertIn("msg-nr-01", inbox.processed)

    def test_multiple_messages_all_marked_processed(self):
        msgs = [
            make_redline_message(message_id="msg-01", thread_id="thread-acme-001"),
            make_non_redline_message(message_id="msg-02", thread_id="thread-beta-001"),
            make_irrelevant_message(message_id="msg-03", thread_id="thread-unrelated-001"),
        ]
        inbox = MockInboxAdapter(msgs)
        watcher, _, _ = _make_watcher(
            inbox,
            classify_fn=lambda s, b: CLASSIFICATION_IRRELEVANT,
        )
        watcher.poll(
            _alice(), since=_EPOCH,
            active_thread_ids={"thread-acme-001", "thread-beta-001", "thread-unrelated-001"},
        )
        self.assertEqual(inbox.processed, {"msg-01", "msg-02", "msg-03"})


class OptOutTests(unittest.TestCase):
    """Principle 2.9: messages on non-active threads are not emitted as state events."""

    def test_redline_on_inactive_thread_emits_no_event(self):
        msg = make_redline_message(thread_id="thread-acme-001")
        inbox = MockInboxAdapter([msg])
        watcher, _, events = _make_watcher(
            inbox, classify_fn=lambda s, b: CLASSIFICATION_REDLINE,
        )
        # thread-acme-001 is NOT in active_thread_ids
        watcher.poll(_alice(), since=_EPOCH, active_thread_ids=set())
        self.assertEqual(len(events), 0)

    def test_inactive_thread_message_is_still_marked_processed(self):
        msg = make_redline_message(message_id="msg-r-01", thread_id="thread-acme-001")
        inbox = MockInboxAdapter([msg])
        watcher, _, _ = _make_watcher(
            inbox, classify_fn=lambda s, b: CLASSIFICATION_REDLINE,
        )
        watcher.poll(_alice(), since=_EPOCH, active_thread_ids=set())
        self.assertIn("msg-r-01", inbox.processed)

    def test_active_and_inactive_threads_mixed(self):
        """Active thread emits; inactive thread does not."""
        active_msg = make_redline_message(
            message_id="msg-active", thread_id="thread-acme-001",
        )
        inactive_msg = make_redline_message(
            message_id="msg-inactive", thread_id="thread-gamma-001",
        )
        inbox = MockInboxAdapter([active_msg, inactive_msg])
        watcher, _, events = _make_watcher(
            inbox, classify_fn=lambda s, b: CLASSIFICATION_REDLINE,
        )
        watcher.poll(
            _alice(), since=_EPOCH,
            active_thread_ids={"thread-acme-001"},  # only acme is active
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].payload["inbox_thread_id"], "thread-acme-001")
        # Both still marked processed
        self.assertIn("msg-active", inbox.processed)
        self.assertIn("msg-inactive", inbox.processed)


class SinceFilterTests(unittest.TestCase):
    """Messages older than `since` are not fetched."""

    def test_message_before_since_is_not_processed(self):
        old_time = datetime(2025, 6, 1, tzinfo=timezone.utc)
        since = datetime(2026, 1, 1, tzinfo=timezone.utc)
        msg = make_redline_message(
            message_id="msg-old", thread_id="thread-acme-001",
            received_at=old_time,
        )
        inbox = MockInboxAdapter([msg])
        watcher, _, events = _make_watcher(
            inbox, classify_fn=lambda s, b: CLASSIFICATION_REDLINE,
        )
        watcher.poll(_alice(), since=since, active_thread_ids={"thread-acme-001"})
        self.assertEqual(len(events), 0)
        self.assertNotIn("msg-old", inbox.processed)


class ClassifierFailureTests(unittest.TestCase):
    """Classifier errors and invalid returns default to irrelevant; are audited."""

    def test_classifier_exception_defaults_to_irrelevant(self):
        def bad_classify(subject, snippet):
            raise RuntimeError("LLM timeout")

        msg = make_redline_message(thread_id="thread-acme-001")
        inbox = MockInboxAdapter([msg])
        watcher, audit, events = _make_watcher(inbox, classify_fn=bad_classify)
        watcher.poll(_alice(), since=_EPOCH, active_thread_ids={"thread-acme-001"})

        self.assertEqual(len(events), 0)
        error_events = audit.query(agent_name="email_watcher")
        types = [e.event_type for e in error_events]
        self.assertIn("classification_error", types)

    def test_classifier_invalid_return_defaults_to_irrelevant(self):
        def bad_classify(subject, snippet):
            return "definitely_not_valid"

        msg = make_redline_message(thread_id="thread-acme-001")
        inbox = MockInboxAdapter([msg])
        watcher, audit, events = _make_watcher(inbox, classify_fn=bad_classify)
        watcher.poll(_alice(), since=_EPOCH, active_thread_ids={"thread-acme-001"})

        self.assertEqual(len(events), 0)
        warn_events = [
            e for e in audit.query(agent_name="email_watcher")
            if e.event_type == "classification_invalid_result"
        ]
        self.assertEqual(len(warn_events), 1)

    def test_classifier_exception_still_marks_message_processed(self):
        def bad_classify(subject, snippet):
            raise RuntimeError("LLM timeout")

        msg = make_redline_message(
            message_id="msg-r-01", thread_id="thread-acme-001",
        )
        inbox = MockInboxAdapter([msg])
        watcher, _, _ = _make_watcher(inbox, classify_fn=bad_classify)
        watcher.poll(_alice(), since=_EPOCH, active_thread_ids={"thread-acme-001"})
        self.assertIn("msg-r-01", inbox.processed)


class AuditTrailTests(unittest.TestCase):
    """Every poll and classification is recorded in the audit log."""

    def test_poll_completed_event_is_audited(self):
        inbox = MockInboxAdapter([])
        watcher, audit, _ = _make_watcher(inbox)
        watcher.poll(_alice(), since=_EPOCH, active_thread_ids=set())

        events = audit.query(agent_name="email_watcher")
        types = [e.event_type for e in events]
        self.assertIn("poll_completed", types)

    def test_message_classified_event_is_audited(self):
        msg = make_redline_message(thread_id="thread-acme-001")
        inbox = MockInboxAdapter([msg])
        watcher, audit, _ = _make_watcher(
            inbox, classify_fn=lambda s, b: CLASSIFICATION_REDLINE,
        )
        watcher.poll(_alice(), since=_EPOCH, active_thread_ids={"thread-acme-001"})

        classified = [
            e for e in audit.query(agent_name="email_watcher")
            if e.event_type == "message_classified"
        ]
        self.assertEqual(len(classified), 1)
        self.assertEqual(classified[0].payload["classification"], CLASSIFICATION_REDLINE)

    def test_poll_completed_payload_contains_counts(self):
        msgs = [
            make_redline_message(message_id="msg-01", thread_id="thread-acme-001"),
            make_non_redline_message(message_id="msg-02", thread_id="thread-beta-001"),
        ]
        inbox = MockInboxAdapter(msgs)
        watcher, audit, _ = _make_watcher(
            inbox, classify_fn=lambda s, b: CLASSIFICATION_IRRELEVANT,
        )
        watcher.poll(_alice(), since=_EPOCH, active_thread_ids=set())

        completed = [
            e for e in audit.query(agent_name="email_watcher")
            if e.event_type == "poll_completed"
        ]
        self.assertEqual(completed[0].payload["messages_fetched"], 2)
        self.assertEqual(completed[0].payload["messages_processed"], 2)

    def test_audit_events_carry_correct_tenant_id(self):
        inbox = MockInboxAdapter([])
        watcher, audit, _ = _make_watcher(inbox)
        watcher.poll(TenantContext(tenant_id="bob"), since=_EPOCH, active_thread_ids=set())

        events = audit.query(tenant_id="bob", agent_name="email_watcher")
        self.assertTrue(len(events) > 0)
        self.assertTrue(all(e.tenant_id == "bob" for e in events))


class PollReturnValueTests(unittest.TestCase):
    """poll() returns the count of messages processed."""

    def test_poll_returns_zero_when_inbox_empty(self):
        inbox = MockInboxAdapter([])
        watcher, _, _ = _make_watcher(inbox)
        count = watcher.poll(_alice(), since=_EPOCH, active_thread_ids=set())
        self.assertEqual(count, 0)

    def test_poll_returns_count_of_all_fetched_messages(self):
        msgs = [
            make_redline_message(message_id="msg-01", thread_id="thread-acme-001"),
            make_non_redline_message(message_id="msg-02", thread_id="thread-beta-001"),
            make_irrelevant_message(message_id="msg-03", thread_id="thread-unrelated-001"),
        ]
        inbox = MockInboxAdapter(msgs)
        watcher, _, _ = _make_watcher(
            inbox, classify_fn=lambda s, b: CLASSIFICATION_IRRELEVANT,
        )
        count = watcher.poll(_alice(), since=_EPOCH, active_thread_ids=set())
        self.assertEqual(count, 3)
