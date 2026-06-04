"""Generic email-attachment report source.

Polls Gmail for messages matching Layer C-supplied sender and subject rules.
Returns raw attachment bytes + metadata per matching message.

Match rules (sender pattern, subject pattern) are Layer C config — never
hardcoded here. The source is arrival-driven: it processes each matching
email once and marks it as processed to avoid double-processing.

Layer C config keys consumed by this module:
    source.match_sender  — exact sender address or glob pattern
    source.match_subject — subject substring or regex pattern
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ReportArrival:
    """Metadata and raw bytes for a single report email attachment.

    Returned by EmailReportSource.poll() for each unprocessed matching email.
    """
    message_id: str
    sender: str
    subject: str
    received_at: str       # ISO-8601 datetime string
    attachment_filename: str
    attachment_bytes: bytes
    run_id: str            # unique ID for this processing run


class EmailReportSource:
    """Generic email-attachment report source.

    Arrival-driven: polls Gmail for messages matching the Layer C sender
    and subject rules, returns raw attachment bytes for each unprocessed
    message. Marks messages processed after successful downstream handling
    to prevent double-processing across runs.

    Args:
        match_sender: sender address or glob pattern (from Layer C config).
        match_subject: subject substring or pattern (from Layer C config).
        credentials_path: path to Gmail OAuth2 credentials JSON.
        processed_label: Gmail label applied to mark a message as processed.
    """

    def __init__(
        self,
        match_sender: str,
        match_subject: str,
        credentials_path: Optional[str] = None,
        processed_label: str = "ACP/Processed",
    ) -> None:
        self._match_sender = match_sender
        self._match_subject = match_subject
        self._credentials_path = credentials_path
        self._processed_label = processed_label

    def poll(self) -> list[ReportArrival]:
        """Poll Gmail for unprocessed report attachments.

        Returns one ReportArrival per matching, unprocessed message.
        Returns an empty list when no new messages match.

        Raises:
            NotImplementedError: Gmail OAuth wiring not yet implemented.
                Wire in the same OAuth pass as Agent 1 (Email Watcher).
        """
        raise NotImplementedError(
            "EmailReportSource.poll() — Gmail wiring deferred. "
            "Implement alongside Agent 1 OAuth setup."
        )

    def mark_processed(self, message_id: str) -> None:
        """Apply the processed label to a Gmail message.

        Call after the full pipeline has successfully handled the attachment
        for this message to prevent re-processing on the next poll.

        Raises:
            NotImplementedError: Gmail OAuth wiring not yet implemented.
        """
        raise NotImplementedError(
            "EmailReportSource.mark_processed() — Gmail wiring deferred."
        )
