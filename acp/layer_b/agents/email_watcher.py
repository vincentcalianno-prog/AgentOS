"""Agent 1: Email Watcher.

Per Architecture Spec v2.4 Section 5.1:
"Poll the operator's inbox for inbound messages relevant to active contract
negotiations. Classify each message as a counterparty redline, a non-redline
contract message, or an irrelevant message. Emit the appropriate state event.
Mark each processed message to prevent re-ingestion."

Haiku-tier LLM for classification. Deterministic for everything else.
No Antora-specific values. No knowledge of Gmail, Drive, or Slack.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Callable, Optional

from acp.layer_b.core.adapters.audit_adapter import AuditEvent, AuditLogAdapter
from acp.layer_b.core.adapters.inbox_adapter import InboxAdapter, InboxMessage
from acp.layer_b.core.types import (
    EVENT_INBOUND_NON_REDLINE,
    EVENT_INBOUND_REDLINE_RECEIVED,
    StateEvent,
    TenantContext,
)

# Type alias: the LLM classify function injected at construction.
# Receives subject + body_snippet, returns one of the CLASSIFICATION_* constants.
ClassifyFn = Callable[[str, str], str]

CLASSIFICATION_REDLINE = "redline"
CLASSIFICATION_NON_REDLINE_CONTRACT = "non_redline_contract"
CLASSIFICATION_IRRELEVANT = "irrelevant"

_VALID_CLASSIFICATIONS = {
    CLASSIFICATION_REDLINE,
    CLASSIFICATION_NON_REDLINE_CONTRACT,
    CLASSIFICATION_IRRELEVANT,
}

# Type alias: the event handler that downstream agents (State Manager) register.
EventHandler = Callable[[StateEvent], None]


class EmailWatcher:
    """Polls an inbox, classifies messages, and emits state events.

    Stateless between poll() calls except for last_polled_at, which callers
    may persist externally if desired. The watcher itself does not manage
    persistent poll state — that is a deployment concern.
    """

    AGENT_NAME = "email_watcher"

    def __init__(
        self,
        inbox: InboxAdapter,
        classify: ClassifyFn,
        audit: AuditLogAdapter,
        config: dict,
    ):
        """
        Args:
            inbox: Provider-neutral inbox adapter.
            classify: LLM-backed function that takes (subject, body_snippet)
                and returns a CLASSIFICATION_* constant. Injected so tests
                can substitute a deterministic stub without touching the LLM.
            audit: Append-only audit log.
            config: Agent configuration dict. Recognised keys:
                - label_filter (str, optional): passed to inbox.fetch_messages()
                - automation_active_statuses (list[str]): negotiation
                  automation_status values treated as active. Defaults to
                  ["Active"]. Passed in from deployment config so the set
                  of active statuses is not hardcoded here.
        """
        self._inbox = inbox
        self._classify = classify
        self._audit = audit
        self._label_filter: Optional[str] = config.get("label_filter")
        self._active_statuses: set[str] = set(
            config.get("automation_active_statuses", ["Active"])
        )
        self._subscribers: list[EventHandler] = []

    # ============================================================
    # Subscription API
    # ============================================================

    def subscribe(self, handler: EventHandler) -> None:
        """Register a downstream handler (e.g., State Manager.process_event)."""
        self._subscribers.append(handler)

    # ============================================================
    # Poll API
    # ============================================================

    def poll(
        self,
        context: TenantContext,
        since: datetime,
        active_thread_ids: set[str],
    ) -> int:
        """Poll the inbox and emit events for relevant messages.

        Args:
            context: The tenant this poll is scoped to.
            since: Only consider messages received at or after this time.
            active_thread_ids: inbox_thread_id values of negotiations whose
                automation_status is Active for this tenant. Messages whose
                thread_id is not in this set are classified but not emitted
                as state events — Principle 2.9 (Operator Opt-Out).

        Returns:
            Number of messages processed (classified + marked).
        """
        messages = self._inbox.fetch_messages(
            since=since,
            label_filter=self._label_filter,
        )

        processed = 0
        for msg in messages:
            self._process_message(context, msg, active_thread_ids)
            processed += 1

        self._audit_write(
            context,
            negotiation_id=None,
            event_type="poll_completed",
            payload={
                "since": since.isoformat(),
                "messages_fetched": len(messages),
                "messages_processed": processed,
            },
        )
        return processed

    # ============================================================
    # Internal
    # ============================================================

    def _process_message(
        self,
        context: TenantContext,
        msg: InboxMessage,
        active_thread_ids: set[str],
    ) -> None:
        """Classify a single message and emit the appropriate event."""
        classification = self._safe_classify(context, msg)

        # Principle 2.9: only emit state events for threads whose automation
        # is active. Log that we saw the message regardless.
        is_tracked = msg.thread_id in active_thread_ids

        self._audit_write(
            context,
            negotiation_id=None,  # we do not know negotiation_id from thread alone here
            event_type="message_classified",
            payload={
                "message_id": msg.message_id,
                "thread_id": msg.thread_id,
                "sender": msg.sender,
                "subject": msg.subject,
                "classification": classification,
                "has_attachment": msg.has_attachment,
                "is_tracked_thread": is_tracked,
            },
        )

        if not is_tracked:
            # Thread not in active automation scope; mark and move on.
            self._inbox.mark_processed(msg.message_id)
            return

        if classification == CLASSIFICATION_REDLINE:
            self._emit_redline_event(context, msg)
        elif classification == CLASSIFICATION_NON_REDLINE_CONTRACT:
            self._emit_non_redline_event(context, msg)
        # IRRELEVANT: no event emitted; fall through to mark_processed.

        self._inbox.mark_processed(msg.message_id)

    def _safe_classify(
        self,
        context: TenantContext,
        msg: InboxMessage,
    ) -> str:
        """Call the injected classify function, defaulting to irrelevant on error."""
        try:
            result = self._classify(msg.subject, msg.body_snippet)
            if result not in _VALID_CLASSIFICATIONS:
                self._audit_write(
                    context,
                    negotiation_id=None,
                    event_type="classification_invalid_result",
                    payload={
                        "message_id": msg.message_id,
                        "returned": result,
                    },
                    severity="warning",
                )
                return CLASSIFICATION_IRRELEVANT
            return result
        except Exception as exc:
            self._audit_write(
                context,
                negotiation_id=None,
                event_type="classification_error",
                payload={
                    "message_id": msg.message_id,
                    "error": str(exc),
                },
                severity="error",
            )
            return CLASSIFICATION_IRRELEVANT

    def _emit_redline_event(
        self,
        context: TenantContext,
        msg: InboxMessage,
    ) -> None:
        event = StateEvent(
            event_type=EVENT_INBOUND_REDLINE_RECEIVED,
            tenant_id=context.tenant_id,
            negotiation_id=msg.thread_id,  # State Manager resolves thread → negotiation
            payload={
                "inbox_message_id": msg.message_id,
                "inbox_thread_id": msg.thread_id,
                "sender": msg.sender,
                "subject": msg.subject,
                "has_attachment": msg.has_attachment,
                "attachment_ids": list(msg.attachment_ids),
            },
            emitted_at=datetime.now(timezone.utc),
            emitted_by=self.AGENT_NAME,
        )
        self._emit(context, event)

    def _emit_non_redline_event(
        self,
        context: TenantContext,
        msg: InboxMessage,
    ) -> None:
        event = StateEvent(
            event_type=EVENT_INBOUND_NON_REDLINE,
            tenant_id=context.tenant_id,
            negotiation_id=msg.thread_id,
            payload={
                "inbox_message_id": msg.message_id,
                "inbox_thread_id": msg.thread_id,
                "sender": msg.sender,
                "subject": msg.subject,
            },
            emitted_at=datetime.now(timezone.utc),
            emitted_by=self.AGENT_NAME,
        )
        self._emit(context, event)

    def _emit(self, context: TenantContext, event: StateEvent) -> None:
        """Dispatch to all subscribers. Subscriber failures are logged, not raised."""
        for handler in self._subscribers:
            try:
                handler(event)
            except Exception as exc:
                self._audit_write(
                    context,
                    negotiation_id=event.negotiation_id,
                    event_type="subscriber_error",
                    payload={
                        "subscriber": getattr(handler, "__qualname__", str(handler)),
                        "error": str(exc),
                        "original_event_type": event.event_type,
                    },
                    severity="error",
                )

    def _audit_write(
        self,
        context: TenantContext,
        negotiation_id: Optional[str],
        event_type: str,
        payload: dict,
        severity: str = "info",
    ) -> None:
        self._audit.record(AuditEvent(
            event_id=str(uuid.uuid4()),
            tenant_id=context.tenant_id,
            negotiation_id=negotiation_id,
            agent_name=self.AGENT_NAME,
            event_type=event_type,
            timestamp=datetime.now(timezone.utc),
            payload=payload,
            severity=severity,
        ))
