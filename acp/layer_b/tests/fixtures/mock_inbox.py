"""MockInboxAdapter — synthetic inbox fixture for layer_b tests.

Per Implementation Guide Section 7.1: fixtures use only made-up data.
    Synthetic counterparty names: Acme Industrial, Beta Manufacturing,
                                  Gamma Components, Delta Systems, Epsilon Labs
    Tenant owners: alice, bob, carol

This module provides:
    MockInboxAdapter  — configurable InboxAdapter for unit and integration tests
    make_redline_message()  — factory for synthetic redline InboxMessages
    make_non_redline_message()  — factory for synthetic non-redline InboxMessages
    make_irrelevant_message()  — factory for synthetic irrelevant InboxMessages
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from acp.layer_b.core.adapters.inbox_adapter import InboxAdapter, InboxMessage


def _now() -> datetime:
    return datetime.now(timezone.utc)


def make_redline_message(
    message_id: str = "msg-001",
    thread_id: str = "thread-acme-001",
    sender: str = "contracts@acmeindustrial.example",
    subject: str = "Re: Master Agreement - Acme Industrial - Redlined",
    received_at: Optional[datetime] = None,
    attachment_ids: tuple[str, ...] = ("att-001",),
) -> InboxMessage:
    """Synthetic message that should classify as a counterparty redline."""
    return InboxMessage(
        message_id=message_id,
        thread_id=thread_id,
        sender=sender,
        subject=subject,
        received_at=received_at or _now(),
        has_attachment=True,
        body_snippet=(
            "Please find attached our redlined version of the agreement. "
            "We have proposed modifications to several clauses including "
            "limitation of liability and payment terms."
        ),
        attachment_ids=attachment_ids,
    )


def make_non_redline_message(
    message_id: str = "msg-002",
    thread_id: str = "thread-beta-001",
    sender: str = "legal@betamanufacturing.example",
    subject: str = "Re: Master Agreement - Beta Manufacturing - Query",
    received_at: Optional[datetime] = None,
) -> InboxMessage:
    """Synthetic message that should classify as non-redline contract correspondence."""
    return InboxMessage(
        message_id=message_id,
        thread_id=thread_id,
        sender=sender,
        subject=subject,
        received_at=received_at or _now(),
        has_attachment=False,
        body_snippet=(
            "Thank you for sending over the agreement. We have a few questions "
            "about Section 8 before we return our redlines. Could we schedule "
            "a call this week to discuss?"
        ),
        attachment_ids=(),
    )


def make_irrelevant_message(
    message_id: str = "msg-003",
    thread_id: str = "thread-unrelated-001",
    sender: str = "newsletter@tradeshow.example",
    subject: str = "Industry News: Q2 Equipment Market Update",
    received_at: Optional[datetime] = None,
) -> InboxMessage:
    """Synthetic message that should classify as irrelevant."""
    return InboxMessage(
        message_id=message_id,
        thread_id=thread_id,
        sender=sender,
        subject=subject,
        received_at=received_at or _now(),
        has_attachment=False,
        body_snippet=(
            "This month's equipment market report is now available. "
            "Click here to download the Q2 summary."
        ),
        attachment_ids=(),
    )


class MockInboxAdapter(InboxAdapter):
    """Configurable in-memory InboxAdapter for tests.

    Usage:
        inbox = MockInboxAdapter(messages=[make_redline_message()])
        # After poll: inbox.processed == {"msg-001"}
    """

    def __init__(self, messages: Optional[list[InboxMessage]] = None):
        self._messages: list[InboxMessage] = list(messages or [])
        self.processed: set[str] = set()
        self._attachments: dict[str, bytes] = {}

    def add_message(self, msg: InboxMessage) -> None:
        """Add a message to the mock inbox (supports building up incrementally)."""
        self._messages.append(msg)

    def add_attachment(self, attachment_id: str, content: bytes) -> None:
        """Register raw bytes for a given attachment_id."""
        self._attachments[attachment_id] = content

    # ============================================================
    # InboxAdapter implementation
    # ============================================================

    def fetch_messages(
        self,
        since: datetime,
        label_filter: Optional[str] = None,
    ) -> list[InboxMessage]:
        """Return messages with received_at >= since, in received_at order."""
        filtered = [m for m in self._messages if m.received_at >= since]
        return sorted(filtered, key=lambda m: m.received_at)

    def get_attachment(self, message_id: str, attachment_id: str) -> bytes:
        if attachment_id not in self._attachments:
            raise ValueError(
                f"Attachment '{attachment_id}' not found in mock inbox "
                f"(message_id='{message_id}')"
            )
        return self._attachments[attachment_id]

    def mark_processed(self, message_id: str) -> None:
        self.processed.add(message_id)
