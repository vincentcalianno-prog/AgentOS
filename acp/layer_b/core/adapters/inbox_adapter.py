"""Abstract interface for inbox (email) backends.

Implementations live in layer_c_antora/adapters/ (production) or
layer_b/tests/fixtures/ (synthetic). layer_b code never imports concrete adapters.

Per Implementation Guide Section 3: every external integration in layer_b is
mediated by an abstract interface. The InboxAdapter decouples Agent 1
(Email Watcher) from any specific email provider.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class InboxMessage:
    """A single message retrieved from an inbox.

    Provider-neutral. GmailAdapter maps Gmail API responses to this type;
    any other inbox provider does the same. Agent 1 never knows which
    provider it is operating on.
    """
    message_id: str               # provider-assigned unique message identifier
    thread_id: str                # maps to inbox_thread_id on NegotiationRow
    sender: str                   # sender address or identifier
    subject: str
    received_at: datetime
    has_attachment: bool
    body_snippet: str             # short preview of body (not full text)
    attachment_ids: tuple[str, ...] = field(default_factory=tuple)
    # IDs of attachments on this message; used by get_attachment().
    # Empty tuple if has_attachment is False.


class InboxAdapter(ABC):
    """Read and mark-processed interface for a generic inbox.

    Deliberately narrow: Agent 1 only needs to poll for messages, fetch
    attachment bytes, and mark messages as processed. Everything else
    is the provider's concern.
    """

    @abstractmethod
    def fetch_messages(
        self,
        since: datetime,
        label_filter: Optional[str] = None,
    ) -> list[InboxMessage]:
        """Return messages received at or after the given timestamp.

        Args:
            since: Lower bound (inclusive) on received_at.
            label_filter: Optional provider-specific filter (e.g., a Gmail
                label name). Implementations that do not support label-based
                filtering ignore this parameter.

        Returns:
            Messages in ascending order of received_at. Empty list if none.
        """
        ...

    @abstractmethod
    def get_attachment(
        self,
        message_id: str,
        attachment_id: str,
    ) -> bytes:
        """Return raw bytes for the specified attachment.

        Args:
            message_id: The message that contains the attachment.
            attachment_id: Must be one of the IDs in InboxMessage.attachment_ids.

        Raises:
            ValueError: If the attachment is not found.
        """
        ...

    @abstractmethod
    def mark_processed(self, message_id: str) -> None:
        """Mark a message as processed to prevent re-ingestion.

        Called after Agent 1 emits the appropriate event for a message.
        Implementations apply whatever mechanism the provider supports
        (e.g., a Gmail label, a local database flag).

        Raises on failure — never silently swallows errors.
        """
        ...
