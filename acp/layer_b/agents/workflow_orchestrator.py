"""Agent 8: Workflow Orchestrator.

Per Architecture Spec v2.4 Section 5.8:
"Coordinate the end-to-end lifecycle of a contract negotiation workflow.
Agent 8 manages SLA monitoring, retry logic, inbox routing, and escalation;
it does not execute individual workflow steps (those belong to Agents 1–7).
Agent 8 is the operational spine: it detects when the pipeline stalls or
fails and takes corrective action."

Five public methods replace the traditional process_event() entry point for
externally-triggered operations:
  scan_sla_violations()  — SLA breach detection via Agent 9
  retry_failed_event()   — re-emit events that previously failed
  resolve_inbox_event()  — map inbox thread to known negotiation
  route_notification()   — fan-out NOTIFICATION_REQUIRED per matching route
  enter_degraded_mode()  — pause automation, alert stakeholders

process_event() is also present but handles only EVENT_NEGOTIATION_FAILED and
EVENT_RETRY_REQUIRED — not the full event fan-out of Agent 3 (State Manager).

Config is supplied at construction via WorkflowOrchestratorConfig. No
deployment-specific values are hard-coded here.

Audit events always use workflow_id="platform". StateEvents emitted to
downstream agents carry the negotiation's own workflow_id (propagated from
the source row or event).

RETRY BOUNDARY (Layer B / Layer C contract):
Layer B agents (5, 6, 7) catch their own exceptions and escalate locally
(e.g., recommendation="escalate") rather than emitting EVENT_NEGOTIATION_FAILED.
Which exception types should trigger Agent 8 retry vs. local escalation depends
on the real failure modes of the underlying LLM provider — information that only
exists in Layer C. Layer C wiring is responsible for emitting EVENT_NEGOTIATION_FAILED
when a provider error warrants a retry. Do not add EVENT_NEGOTIATION_FAILED emission
to Layer B agents.

WIRING CONTRACT (for Layer C operators):
Agent 8 emits multiple event types. Subscribers must route by event_type:
  EVENT_NEGOTIATION_PAUSED    → State Manager (so SM persists automation_status="Paused")
  EVENT_RETRY_REQUIRED        → State Manager (so SM re-dispatches to retry target)
  EVENT_NOTIFICATION_REQUIRED → Layer C notification service (NOT back to SM)

Routing all Agent 8 events unconditionally back to SM generates spurious
"unhandled_event_type" audit warnings for notification events. The integration
test test_orchestrator_pipeline.py demonstrates the correct filtering pattern.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Callable, Optional

from acp.layer_b.agents.portfolio_aggregator import PortfolioAggregatorAgent
from acp.layer_b.agents.workflow_orchestrator_config import WorkflowOrchestratorConfig
from acp.layer_b.core.adapters.audit_adapter import AuditEvent, AuditLogAdapter
from acp.layer_b.core.adapters.ledger_adapter import LedgerAdapter
from acp.layer_b.core.types import (
    EVENT_NEGOTIATION_FAILED,
    EVENT_NEGOTIATION_PAUSED,
    EVENT_NOTIFICATION_REQUIRED,
    EVENT_RETRY_EXHAUSTED,
    EVENT_RETRY_REQUIRED,
    EVENT_SLA_BREACH_DETECTED,
    EventRetryRow,
    PortfolioReadContext,
    StateEvent,
    TenantContext,
)


# Type alias for event subscribers
EventHandler = Callable[[StateEvent], None]


class WorkflowOrchestratorAgent:
    """Platform-level workflow coordinator for the ACP pipeline.

    Owns SLA monitoring, retry orchestration, inbox routing, notification
    fan-out, and degraded-mode lifecycle. Does not execute individual
    workflow steps — those belong to Agents 1–7.

    All public methods are externally scheduled (Layer C controls timing);
    Agent 8 has no internal scheduler. Layer C invokes:
      - scan_sla_violations() on polling_interval_seconds cadence
      - retry_failed_event()  on polling_interval_seconds cadence
      - resolve_inbox_event() on each inbound inbox event
      - process_event()       when SM forwards NEGOTIATION_FAILED / RETRY_REQUIRED
    """

    AGENT_NAME = "workflow_orchestrator"

    def __init__(
        self,
        config: WorkflowOrchestratorConfig,
        ledger: LedgerAdapter,
        audit: AuditLogAdapter,
        portfolio: PortfolioAggregatorAgent,
    ) -> None:
        """
        Args:
            config:    Complete deployment configuration for Agent 8.
            ledger:    Shared ledger adapter — used for retry state and thread resolution.
            audit:     Append-only audit log.
            portfolio: Agent 9 instance — called by scan_sla_violations() for cross-tenant reads.
        """
        self._config = config
        self._ledger = ledger
        self._audit = audit
        self._portfolio = portfolio
        self._subscribers: list[EventHandler] = []

    # ------------------------------------------------------------------ #
    # Subscription API                                                      #
    # ------------------------------------------------------------------ #

    def subscribe(self, handler: EventHandler) -> None:
        """Register a handler to be called for every event emitted by this agent."""
        self._subscribers.append(handler)

    # ------------------------------------------------------------------ #
    # Public interface                                                      #
    # ------------------------------------------------------------------ #

    def scan_sla_violations(self, context: PortfolioReadContext) -> list[StateEvent]:
        """Detect SLA breaches and route notifications for each violation.

        Iterates config.operational.sla_thresholds. For each
        (workflow_id, status_str) → threshold_days entry:
          1. Calls Agent 9 to retrieve stalled work items in that workflow.
          2. Filters to items whose status matches status_str.
          3. Routes notifications via route_notification() for each match.

        Returns the full list of NOTIFICATION_REQUIRED events emitted.
        Layer C invokes this on config.operational.polling_interval_seconds cadence.
        Agent 8 itself has no internal scheduler.

        Args:
            context: Portfolio read context with ROLE_PORTFOLIO_AGGREGATOR.
        """
        emitted: list[StateEvent] = []
        now = datetime.now(timezone.utc)

        for (workflow_id, status_str), threshold_days in self._config.operational.sla_thresholds.items():
            stalled = self._portfolio.stalled_work_items(
                context,
                threshold_days=threshold_days,
                workflow_id=workflow_id,
            )
            violations = [item for item in stalled if item.status == status_str]

            for item in violations:
                breach_event = StateEvent(
                    event_type=EVENT_SLA_BREACH_DETECTED,
                    tenant_id=item.tenant_id,
                    negotiation_id=item.work_item_id,
                    workflow_id=workflow_id,
                    payload={
                        "status": status_str,
                        "threshold_days": threshold_days,
                        "last_activity_at": (
                            item.last_activity_at.isoformat()
                            if item.last_activity_at else None
                        ),
                        "owner": item.owner,
                        "counterparty_name": item.counterparty_name,
                    },
                    emitted_at=now,
                    emitted_by=self.AGENT_NAME,
                )
                notifications = self.route_notification(breach_event)
                emitted.extend(notifications)

            if violations:
                self._audit_write(
                    context.reader_id, None, "sla_violations_detected",
                    {
                        "workflow_id": workflow_id,
                        "status": status_str,
                        "threshold_days": threshold_days,
                        "count": len(violations),
                    },
                )

        return emitted

    def retry_failed_event(self, context: PortfolioReadContext) -> None:
        """Re-emit pending retry rows; enter degraded mode when retries are exhausted.

        Scans all pending/in_progress retry rows across all tenants. For each:
          - If attempt_count >= max_retry_attempts: mark "exhausted", call
            enter_degraded_mode(), emit EVENT_RETRY_EXHAUSTED.
          - Otherwise: mark "in_progress", reconstruct the original event from
            payload_json, re-emit to subscribers, audit the attempt.

        Layer C invokes this on config.operational.polling_interval_seconds cadence.
        The reconstructed event carries the original payload plus a "retry_id" key
        so downstream agents can include it in any subsequent NEGOTIATION_FAILED
        payload for state continuity.

        Args:
            context: Portfolio read context (used for audit identity only;
                     cross-tenant ledger access is a platform operation).
        """
        pending = self._ledger.list_pending_retries()
        now = datetime.now(timezone.utc)

        for row in pending:
            tenant_ctx = TenantContext(tenant_id=row.tenant_id)

            if row.attempt_count >= self._config.operational.max_retry_attempts:
                # Mark exhausted and enter degraded mode
                exhausted = EventRetryRow(
                    retry_id=row.retry_id,
                    tenant_id=row.tenant_id,
                    negotiation_id=row.negotiation_id,
                    workflow_id=row.workflow_id,
                    event_type=row.event_type,
                    payload_json=row.payload_json,
                    attempt_count=row.attempt_count,
                    last_attempt_at=row.last_attempt_at,
                    last_error=row.last_error,
                    status="exhausted",
                )
                self._ledger.upsert_retry_state(exhausted)

                self.enter_degraded_mode(
                    tenant_ctx,
                    row.negotiation_id,
                    reason=(
                        f"Retry exhausted for '{row.event_type}' after "
                        f"{row.attempt_count} attempts: {row.last_error}"
                    ),
                )
                self._emit(StateEvent(
                    event_type=EVENT_RETRY_EXHAUSTED,
                    tenant_id=row.tenant_id,
                    negotiation_id=row.negotiation_id,
                    workflow_id=row.workflow_id,
                    payload={
                        "retry_id": row.retry_id,
                        "failed_event_type": row.event_type,
                        "attempt_count": row.attempt_count,
                        "last_error": row.last_error,
                    },
                    emitted_at=now,
                    emitted_by=self.AGENT_NAME,
                ))
                self._audit_write(
                    row.tenant_id, row.negotiation_id, "retry_exhausted",
                    {
                        "retry_id": row.retry_id,
                        "event_type": row.event_type,
                        "attempt_count": row.attempt_count,
                    },
                    severity="warning",
                )
                continue

            # Decode the original event payload
            try:
                original_payload = json.loads(row.payload_json)
            except (json.JSONDecodeError, ValueError):
                original_payload = {}
                self._audit_write(
                    row.tenant_id, row.negotiation_id, "retry_payload_decode_error",
                    {"retry_id": row.retry_id, "raw": row.payload_json[:200]},
                    severity="error",
                )

            # Mark in_progress before emitting to prevent a concurrent sweep
            # from picking up the same row
            in_progress = EventRetryRow(
                retry_id=row.retry_id,
                tenant_id=row.tenant_id,
                negotiation_id=row.negotiation_id,
                workflow_id=row.workflow_id,
                event_type=row.event_type,
                payload_json=row.payload_json,
                attempt_count=row.attempt_count,
                last_attempt_at=now,
                last_error=row.last_error,
                status="in_progress",
            )
            self._ledger.upsert_retry_state(in_progress)

            reconstructed = StateEvent(
                event_type=row.event_type,
                tenant_id=row.tenant_id,
                negotiation_id=row.negotiation_id,
                workflow_id=row.workflow_id,
                payload={**original_payload, "retry_id": row.retry_id},
                emitted_at=now,
                emitted_by=self.AGENT_NAME,
            )
            self._emit(reconstructed)
            self._audit_write(
                row.tenant_id, row.negotiation_id, "event_retried",
                {
                    "retry_id": row.retry_id,
                    "event_type": row.event_type,
                    "attempt_count": row.attempt_count,
                },
            )

    def resolve_inbox_event(self, event: StateEvent) -> Optional[str]:
        """Map an inbox thread to a known negotiation_id.

        Looks up event.payload["inbox_thread_id"] in the tenant's ledger.

        Resolution outcomes:
          Found     → return negotiation_id, audit resolved.
          Not found → apply config.organization.lookup_failure_policy:
            "notify_for_triage"       emit NOTIFICATION_REQUIRED, return None.
            "auto_create_negotiation" raise NotImplementedError (Phase 1 stub).
            "drop_silently"           audit warning, return None.

        Args:
            event: Inbound inbox event. Must carry inbox_thread_id in payload
                   and be scoped to a single tenant via event.tenant_id.

        Returns:
            negotiation_id string if resolved, else None.
        """
        thread_id = event.payload.get("inbox_thread_id")
        if not thread_id:
            self._audit_write(
                event.tenant_id, event.negotiation_id,
                "resolve_inbox_missing_thread_id",
                {"event_type": event.event_type},
                severity="warning",
            )
            return None

        row = self._ledger.get_row_by_thread_id(event.tenant_id, thread_id)
        if row is not None:
            self._audit_write(
                event.tenant_id, row.negotiation_id, "inbox_event_resolved",
                {"thread_id": thread_id, "resolved_to": row.negotiation_id},
            )
            return row.negotiation_id

        # Thread not found — apply policy
        policy = self._config.organization.lookup_failure_policy

        if policy == "auto_create_negotiation":
            raise NotImplementedError(
                "lookup_failure_policy='auto_create_negotiation' is not implemented in Phase 1"
            )

        if policy == "drop_silently":
            self._audit_write(
                event.tenant_id, None, "inbox_event_dropped",
                {"thread_id": thread_id, "policy": policy},
                severity="warning",
            )
            return None

        # Default: "notify_for_triage"
        triage_event = StateEvent(
            event_type=EVENT_NOTIFICATION_REQUIRED,
            tenant_id=event.tenant_id,
            negotiation_id=event.negotiation_id,
            workflow_id=event.workflow_id,
            payload={
                "reason": "unresolved_inbox_thread",
                "thread_id": thread_id,
                "original_event_type": event.event_type,
                "policy": policy,
            },
            emitted_at=datetime.now(timezone.utc),
            emitted_by=self.AGENT_NAME,
        )
        self._emit(triage_event)
        self._audit_write(
            event.tenant_id, None, "inbox_event_triaged",
            {"thread_id": thread_id, "policy": policy},
        )
        return None

    def route_notification(self, source_event: StateEvent) -> list[StateEvent]:
        """Fan-out NOTIFICATION_REQUIRED events to all matching notification routes.

        Matching rules (both must hold):
          1. route.event_pattern == source_event.event_type (exact match)
          2. route.workflow_id is None  (all workflows)  OR
             route.workflow_id == source_event.workflow_id

        All matching routes fire — not first-match-only. Each match produces
        one NOTIFICATION_REQUIRED event carrying recipient_id, channel_preference,
        and the full source event payload. Events are emitted via _emit() AND
        returned for caller inspection/testing.

        Args:
            source_event: The event that triggered the notification need.

        Returns:
            List of NOTIFICATION_REQUIRED StateEvents emitted (one per matched route).
        """
        now = datetime.now(timezone.utc)
        notifications: list[StateEvent] = []

        for route in self._config.organization.notification_routes:
            if route.event_pattern != source_event.event_type:
                continue
            if route.workflow_id is not None and route.workflow_id != source_event.workflow_id:
                continue

            n = StateEvent(
                event_type=EVENT_NOTIFICATION_REQUIRED,
                tenant_id=source_event.tenant_id,
                negotiation_id=source_event.negotiation_id,
                workflow_id=source_event.workflow_id,
                payload={
                    "recipient_id": route.recipient_id,
                    "channel_preference": route.channel_preference,
                    "source_event_type": source_event.event_type,
                    "source_payload": source_event.payload,
                },
                emitted_at=now,
                emitted_by=self.AGENT_NAME,
            )
            self._emit(n)
            notifications.append(n)

        return notifications

    def enter_degraded_mode(
        self,
        context: TenantContext,
        negotiation_id: str,
        reason: str,
    ) -> None:
        """Pause automation for a negotiation and notify stakeholders.

        Emits EVENT_NEGOTIATION_PAUSED → State Manager receives this and sets
        automation_status="Paused" on the negotiation row. Subsequent pipeline
        events for this negotiation are then gated out by the State Manager's
        re-emit handlers.

        Also routes notifications via route_notification() so any configured
        NotificationRoute entries with event_pattern="negotiation_paused" fire.

        Per Architecture Spec Principle 2.9 (Opt-Out): once paused, the
        negotiation does not receive further pipeline events until resumed
        by the operator via a manual EVENT_NEGOTIATION_RESUMED.

        Args:
            context:        Tenant context for the negotiation being paused.
            negotiation_id: The negotiation entering degraded mode.
            reason:         Human-readable explanation for audit and notification.
        """
        now = datetime.now(timezone.utc)
        paused_event = StateEvent(
            event_type=EVENT_NEGOTIATION_PAUSED,
            tenant_id=context.tenant_id,
            negotiation_id=negotiation_id,
            workflow_id="platform",
            payload={"reason": reason},
            emitted_at=now,
            emitted_by=self.AGENT_NAME,
        )
        self._emit(paused_event)
        self.route_notification(paused_event)

        self._audit_write(
            context.tenant_id, negotiation_id, "degraded_mode_entered",
            {"reason": reason},
            severity="warning",
        )

    def process_event(self, context: TenantContext, event: StateEvent) -> None:
        """Handle NEGOTIATION_FAILED and RETRY_REQUIRED events from the State Manager.

        Creates or updates retry state in the ledger. Routes notifications for
        the failure. Does NOT enter degraded mode here — exhaustion detection
        and degraded-mode entry happen in the retry_failed_event() sweep.

        Only EVENT_NEGOTIATION_FAILED and EVENT_RETRY_REQUIRED are handled;
        all other event types are audited as warnings and dropped.

        Expected payload contract for EVENT_NEGOTIATION_FAILED:
          failed_event_type         str  — event type that failed
          failed_event_payload_json str  — json.dumps() of the original event payload
          error                     str  — error message
          retry_id                  str? — existing retry_id for update (optional)

        EVENT_RETRY_REQUIRED uses the same payload contract.
        """
        if event.event_type in (EVENT_NEGOTIATION_FAILED, EVENT_RETRY_REQUIRED):
            self._handle_failure(context, event)
        else:
            self._audit_write(
                context.tenant_id, event.negotiation_id, "unhandled_event_type",
                {"event_type": event.event_type},
                severity="warning",
            )

    # ------------------------------------------------------------------ #
    # Internal event handlers                                              #
    # ------------------------------------------------------------------ #

    def _handle_failure(self, context: TenantContext, event: StateEvent) -> None:
        """Shared handler for NEGOTIATION_FAILED and RETRY_REQUIRED.

        If payload carries a known retry_id: update the existing retry row
        (increment attempt_count, update last_error). If the retry_id is stale
        or absent: create a new EventRetryRow.

        Routes notifications for the failure event in all cases.
        """
        payload = event.payload
        error = payload.get("error", "")
        now = datetime.now(timezone.utc)

        retry_id = payload.get("retry_id")
        if retry_id:
            existing = self._ledger.get_retry_state(retry_id)
            if existing is not None:
                updated = EventRetryRow(
                    retry_id=existing.retry_id,
                    tenant_id=existing.tenant_id,
                    negotiation_id=existing.negotiation_id,
                    workflow_id=existing.workflow_id,
                    event_type=existing.event_type,
                    payload_json=existing.payload_json,
                    attempt_count=existing.attempt_count + 1,
                    last_attempt_at=now,
                    last_error=error,
                    status="pending",
                )
                self._ledger.upsert_retry_state(updated)
                self._audit_write(
                    context.tenant_id, event.negotiation_id, "retry_state_updated",
                    {
                        "retry_id": retry_id,
                        "attempt_count": updated.attempt_count,
                        "failed_event_type": existing.event_type,
                    },
                )
                self.route_notification(event)
                return

        # New failure (or stale retry_id) — create a fresh retry row
        failed_event_type = payload.get("failed_event_type", "unknown")
        failed_event_payload_json = payload.get("failed_event_payload_json", "{}")
        new_retry_id = str(uuid.uuid4())
        row = EventRetryRow(
            retry_id=new_retry_id,
            tenant_id=event.tenant_id,
            negotiation_id=event.negotiation_id,
            workflow_id=event.workflow_id,
            event_type=failed_event_type,
            payload_json=failed_event_payload_json,
            attempt_count=1,
            last_attempt_at=now,
            last_error=error,
            status="pending",
        )
        self._ledger.upsert_retry_state(row)
        self._audit_write(
            context.tenant_id, event.negotiation_id, "retry_state_created",
            {
                "retry_id": new_retry_id,
                "failed_event_type": failed_event_type,
                "error": error,
            },
        )
        self.route_notification(event)

    # ------------------------------------------------------------------ #
    # Internal helpers                                                      #
    # ------------------------------------------------------------------ #

    def _emit(self, event: StateEvent) -> None:
        """Dispatch an event to all subscribers.

        Subscriber failures are caught and audited — a failing subscriber must
        not prevent other subscribers from receiving the event.
        """
        for handler in self._subscribers:
            try:
                handler(event)
            except Exception as exc:
                self._audit.record(AuditEvent(
                    event_id=str(uuid.uuid4()),
                    tenant_id=event.tenant_id,
                    negotiation_id=event.negotiation_id,
                    workflow_id="platform",
                    agent_name=self.AGENT_NAME,
                    event_type="subscriber_error",
                    timestamp=datetime.now(timezone.utc),
                    payload={
                        "subscriber": getattr(handler, "__qualname__", str(handler)),
                        "error": str(exc),
                        "original_event_type": event.event_type,
                    },
                    severity="error",
                ))

    def _audit_write(
        self,
        tenant_id: str,
        negotiation_id: Optional[str],
        event_type: str,
        payload: dict,
        severity: str = "info",
    ) -> None:
        """Record an audit event. Always uses workflow_id='platform'."""
        self._audit.record(AuditEvent(
            event_id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            negotiation_id=negotiation_id,
            workflow_id="platform",
            agent_name=self.AGENT_NAME,
            event_type=event_type,
            timestamp=datetime.now(timezone.utc),
            payload=payload,
            severity=severity,
        ))
