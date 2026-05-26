"""Agent 3: State Manager.

Per Architecture Spec v2.4 Section 5.3:
"Maintain the canonical source of truth for every active contract negotiation
owned by an operator across all operator tenants. The State Manager instantiates
a logical scope per operator; writes are serialized within each tenant scope
but proceed in parallel across tenants. Owns the tracker schemas and enforces
valid state machine transitions; emits state events to downstream agents;
rejects cross-tenant write attempts at the API level."

This is the system spine. Every state-modifying operation goes through here.
Deterministic — no LLM.
"""

from __future__ import annotations

import re
import threading
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from typing import Callable, Optional

from acp.layer_b.core.adapters.audit_adapter import AuditEvent, AuditLogAdapter
from acp.layer_b.core.adapters.ledger_adapter import LedgerAdapter
from acp.layer_b.core.tenancy import TenancyEnforcer
from acp.layer_b.core.types import (
    EVENT_ANALYSIS_COMPLETE,
    EVENT_COUNTER_PROPOSALS_READY,
    EVENT_DIFF_COMPLETE,
    EVENT_LRS_READY,
    EVENT_DOCUMENT_EXTRACTED,
    EVENT_DOCUMENT_EXTRACTION_REQUIRED,
    EVENT_INBOUND_REDLINE_RECEIVED,
    EVENT_LRS_APPROVED,
    EVENT_LRS_DELIVERED,
    EVENT_LRS_RETURNED,
    EVENT_NEGOTIATION_PAUSED,
    EVENT_NEGOTIATION_RESUMED,
    EVENT_OUTBOUND_CONTRACT_SENT,
    EVENT_ROUND_READY_FOR_ANALYSIS,
    InvalidTransitionError,
    NegotiationNotFoundError,
    NegotiationRow,
    NegotiationState,
    StateEvent,
    TenantContext,
    is_valid_transition,
)


# Type alias for event subscribers
EventHandler = Callable[[StateEvent], None]


def _slugify(text: str) -> str:
    """Convert text to a path-safe lowercase slug. Generic — no deployment-specific logic."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text[:64] or "unknown"


class StateManager:
    """Owns the canonical state for all negotiations across all tenants.

    Thread-safe per tenant. Writes within a tenant scope are serialized;
    writes across tenants proceed in parallel.
    """

    def __init__(
        self,
        ledger: LedgerAdapter,
        tenancy: TenancyEnforcer,
        audit: AuditLogAdapter,
    ):
        self._ledger = ledger
        self._tenancy = tenancy
        self._audit = audit

        # Per-tenant locks for write serialization
        self._tenant_locks: dict[str, threading.Lock] = {}
        self._locks_mutex = threading.Lock()

        # Event subscribers (Agent 4, Agent 2, etc. register here)
        self._subscribers: list[EventHandler] = []

    # ============================================================
    # Subscription API (downstream agents register interest)
    # ============================================================

    def subscribe(self, handler: EventHandler) -> None:
        """Register a handler to be called for every emitted state event."""
        self._subscribers.append(handler)

    # ============================================================
    # Read API
    # ============================================================

    def get_negotiation(
        self,
        context: TenantContext,
        negotiation_id: str,
    ) -> NegotiationRow:
        """Return the negotiation row. Raises if not found or if access denied."""
        owner = self._ledger.get_owner(negotiation_id)
        if owner is None:
            raise NegotiationNotFoundError(
                f"Negotiation '{negotiation_id}' not found"
            )
        self._tenancy.assert_can_read(context, owner)
        row = self._ledger.get_row(owner, negotiation_id)
        if row is None:
            raise NegotiationNotFoundError(
                f"Negotiation '{negotiation_id}' not found in tenant '{owner}'"
            )
        return row

    def list_negotiations(
        self,
        context: TenantContext,
        target_tenant: Optional[str] = None,
    ) -> list[NegotiationRow]:
        """List all negotiations in the target tenant's scope.

        If target_tenant is None, defaults to the caller's own tenant.
        Cross-tenant listing requires the portfolio_aggregator role.
        """
        if target_tenant is None:
            target_tenant = context.tenant_id
        self._tenancy.assert_can_read(context, target_tenant)
        return self._ledger.list_rows(target_tenant)

    def list_all_negotiations_cross_tenant(
        self,
        context: TenantContext,
    ) -> dict[str, list[NegotiationRow]]:
        """Return all negotiations across all tenants. Portfolio Aggregator only.

        Returns mapping of tenant_id -> list of rows.
        """
        self._tenancy.assert_can_read_cross_tenant(context)
        owners = self._ledger.list_all_owners()
        tenant_ids = set(owners.values())
        return {tid: self._ledger.list_rows(tid) for tid in tenant_ids}

    # ============================================================
    # Write API
    # ============================================================

    def create_negotiation(
        self,
        context: TenantContext,
        row: NegotiationRow,
    ) -> NegotiationRow:
        """Create a new negotiation in the caller's tenant scope."""
        self._tenancy.assert_can_write(context, row.owner)

        # Verify it doesn't already exist
        existing = self._ledger.get_owner(row.negotiation_id)
        if existing is not None:
            raise ValueError(
                f"Negotiation '{row.negotiation_id}' already exists "
                f"(owned by tenant '{existing}')"
            )

        lock = self._get_tenant_lock(row.owner)
        with lock:
            # Set defaults
            updated = replace(
                row,
                last_activity_date=row.last_activity_date or datetime.now(timezone.utc),
            )
            self._ledger.upsert_row(row.owner, updated)

        self._audit_write(context, row.negotiation_id, "create_negotiation", {
            "initial_status": updated.status.value,
            "contract_type": updated.contract_type,
            "counterparty": updated.counterparty_description,
        })
        return updated

    def transition_state(
        self,
        context: TenantContext,
        negotiation_id: str,
        new_state: NegotiationState,
        reason: Optional[str] = None,
    ) -> NegotiationRow:
        """Transition a negotiation to a new state.

        Validates the transition against the state machine. Raises
        InvalidTransitionError if the transition is not allowed.
        """
        owner = self._ledger.get_owner(negotiation_id)
        if owner is None:
            raise NegotiationNotFoundError(
                f"Negotiation '{negotiation_id}' not found"
            )
        self._tenancy.assert_can_write(context, owner)

        lock = self._get_tenant_lock(owner)
        with lock:
            row = self._ledger.get_row(owner, negotiation_id)
            if row is None:
                raise NegotiationNotFoundError(
                    f"Negotiation '{negotiation_id}' not found"
                )

            old_state = row.status
            if not is_valid_transition(old_state, new_state):
                self._audit_write(context, negotiation_id, "invalid_transition_rejected", {
                    "from_state": old_state.value,
                    "to_state": new_state.value,
                    "reason": reason,
                }, severity="warning")
                raise InvalidTransitionError(
                    f"Cannot transition from '{old_state.value}' to '{new_state.value}'"
                )

            updated = replace(
                row,
                status=new_state,
                last_activity_date=datetime.now(timezone.utc),
            )
            self._ledger.upsert_row(owner, updated)

        self._audit_write(context, negotiation_id, "state_transition", {
            "from_state": old_state.value,
            "to_state": new_state.value,
            "reason": reason,
        })
        return updated

    def update_fields(
        self,
        context: TenantContext,
        negotiation_id: str,
        updates: dict,
    ) -> NegotiationRow:
        """Update one or more non-state fields on a negotiation.

        State changes must go through transition_state(); attempts to update
        'status' through this method are rejected.
        """
        if "status" in updates:
            raise ValueError(
                "Cannot update 'status' via update_fields(); use transition_state()"
            )

        owner = self._ledger.get_owner(negotiation_id)
        if owner is None:
            raise NegotiationNotFoundError(
                f"Negotiation '{negotiation_id}' not found"
            )
        self._tenancy.assert_can_write(context, owner)

        lock = self._get_tenant_lock(owner)
        with lock:
            row = self._ledger.get_row(owner, negotiation_id)
            if row is None:
                raise NegotiationNotFoundError(
                    f"Negotiation '{negotiation_id}' not found"
                )

            # Apply updates
            valid_fields = {f for f in row.__dataclass_fields__.keys()}
            unknown_fields = set(updates.keys()) - valid_fields
            if unknown_fields:
                raise ValueError(f"Unknown fields: {unknown_fields}")

            # Disallow mutating identity fields
            for protected in ("negotiation_id", "owner"):
                if protected in updates and updates[protected] != getattr(row, protected):
                    raise ValueError(
                        f"Cannot modify identity field '{protected}'"
                    )

            updates_with_activity = dict(updates)
            updates_with_activity["last_activity_date"] = datetime.now(timezone.utc)
            updated = replace(row, **updates_with_activity)
            self._ledger.upsert_row(owner, updated)

        self._audit_write(context, negotiation_id, "fields_updated", {
            "fields": list(updates.keys()),
        })
        return updated

    def increment_round(
        self,
        context: TenantContext,
        negotiation_id: str,
    ) -> NegotiationRow:
        """Increment the round number. Called when a new counterparty version arrives."""
        owner = self._ledger.get_owner(negotiation_id)
        if owner is None:
            raise NegotiationNotFoundError(
                f"Negotiation '{negotiation_id}' not found"
            )
        self._tenancy.assert_can_write(context, owner)

        lock = self._get_tenant_lock(owner)
        with lock:
            row = self._ledger.get_row(owner, negotiation_id)
            if row is None:
                raise NegotiationNotFoundError(
                    f"Negotiation '{negotiation_id}' not found"
                )
            updated = replace(
                row,
                round_number=row.round_number + 1,
                last_activity_date=datetime.now(timezone.utc),
            )
            self._ledger.upsert_row(owner, updated)

        self._audit_write(context, negotiation_id, "round_incremented", {
            "from_round": row.round_number,
            "to_round": updated.round_number,
        })
        return updated

    # ============================================================
    # Event Processing
    # ============================================================

    def process_event(
        self,
        context: TenantContext,
        event: StateEvent,
    ) -> None:
        """Process an incoming state event from an upstream agent.

        Dispatches to the appropriate handler based on event type.
        Re-emits derived events to downstream subscribers.
        """
        self._tenancy.assert_can_write(context, event.tenant_id)

        handler = self._event_handlers().get(event.event_type)
        if handler is None:
            self._audit_write(context, event.negotiation_id, "unknown_event_type", {
                "event_type": event.event_type,
                "payload": event.payload,
            }, severity="warning")
            return

        handler(context, event)

    def _event_handlers(self):
        return {
            EVENT_OUTBOUND_CONTRACT_SENT: self._handle_outbound_contract_sent,
            EVENT_INBOUND_REDLINE_RECEIVED: self._handle_inbound_redline,
            EVENT_DOCUMENT_EXTRACTED: self._handle_document_extracted,
            EVENT_DIFF_COMPLETE: self._handle_diff_complete,
            EVENT_ANALYSIS_COMPLETE: self._handle_analysis_complete,
            EVENT_COUNTER_PROPOSALS_READY: self._handle_counter_proposals_ready,
            EVENT_LRS_READY: self._handle_lrs_ready,
            EVENT_LRS_DELIVERED: self._handle_lrs_delivered,
            EVENT_LRS_APPROVED: self._handle_lrs_approved,
            EVENT_LRS_RETURNED: self._handle_lrs_returned,
            EVENT_NEGOTIATION_PAUSED: self._handle_negotiation_paused,
            EVENT_NEGOTIATION_RESUMED: self._handle_negotiation_resumed,
        }

    def _handle_outbound_contract_sent(self, context: TenantContext, event: StateEvent) -> None:
        """An outbound contract was sent to the counterparty. Move to CONTRACT_SENT."""
        self.transition_state(
            context, event.negotiation_id,
            NegotiationState.CONTRACT_SENT,
            reason=f"Outbound contract sent (event from {event.emitted_by})",
        )
        # Optionally record the storage path of the sent version
        if "storage_path" in event.payload:
            self.update_fields(
                context, event.negotiation_id,
                {"last_outbound_version_sent": event.payload["storage_path"]},
            )

    def _handle_inbound_redline(self, context: TenantContext, event: StateEvent) -> None:
        """A counterparty redline arrived. Move to REDLINES_RECEIVED and increment round."""
        self.transition_state(
            context, event.negotiation_id,
            NegotiationState.REDLINES_RECEIVED,
            reason=f"Inbound redline received (event from {event.emitted_by})",
        )
        self.increment_round(context, event.negotiation_id)

        # Update the whos_court since the row owner now owns the next move
        row = self.get_negotiation(context, event.negotiation_id)
        self.update_fields(
            context, event.negotiation_id,
            {"whos_court": row.owner},
        )

        # Emit a derived event: document extraction required
        self._emit(StateEvent(
            event_type=EVENT_DOCUMENT_EXTRACTION_REQUIRED,
            tenant_id=event.tenant_id,
            negotiation_id=event.negotiation_id,
            workflow_id=event.workflow_id,
            payload={
                "inbox_message_id": event.payload.get("inbox_message_id"),
                "inbox_thread_id": event.payload.get("inbox_thread_id"),
                "attachment_ids": event.payload.get("attachment_ids", []),
                "round_number": row.round_number,  # row already reflects the incremented value
                "contract_type": row.contract_type,
                "counterparty_ref": (
                    row.counterparty_profile_ref
                    or _slugify(row.counterparty_description or "unknown")
                ),
            },
            emitted_at=datetime.now(timezone.utc),
            emitted_by="state_manager",
        ))

    def _handle_lrs_delivered(self, context: TenantContext, event: StateEvent) -> None:
        """The LRS was delivered to the Legal Reviewer."""
        self.update_fields(
            context, event.negotiation_id,
            {
                "review_package_status": "Awaiting Legal Review",
                "last_review_package_sent_date": datetime.now(timezone.utc),
                "whos_court": "Legal",
            },
        )

    def _handle_lrs_approved(self, context: TenantContext, event: StateEvent) -> None:
        """The Legal Reviewer approved the LRS."""
        self.update_fields(
            context, event.negotiation_id,
            {"review_package_status": "Approved", "whos_court": self.get_negotiation(context, event.negotiation_id).owner},
        )

    def _handle_lrs_returned(self, context: TenantContext, event: StateEvent) -> None:
        """The Legal Reviewer returned the LRS for revision."""
        self.update_fields(
            context, event.negotiation_id,
            {"review_package_status": "Returned for Revision", "whos_court": self.get_negotiation(context, event.negotiation_id).owner},
        )

    def _handle_document_extracted(self, context: TenantContext, event: StateEvent) -> None:
        """A counterparty document was persisted to storage. Update tracker and trigger analysis."""
        updates = {}
        if "storage_path" in event.payload:
            updates["last_counterparty_version"] = event.payload["storage_path"]
        if "storage_folder_path" in event.payload:
            updates["storage_folder_path"] = event.payload["storage_folder_path"]
        if updates:
            self.update_fields(context, event.negotiation_id, updates)

        # Fetch row after updates to get current outbound path and folder path
        row = self.get_negotiation(context, event.negotiation_id)

        # Emit: round is ready for structural diff (Agent 4 subscribes to this)
        self._emit(StateEvent(
            event_type=EVENT_ROUND_READY_FOR_ANALYSIS,
            tenant_id=event.tenant_id,
            negotiation_id=event.negotiation_id,
            workflow_id=event.workflow_id,
            payload={
                "counterparty_document_path": event.payload.get("storage_path"),
                "outbound_document_path": row.last_outbound_version_sent,
                "storage_folder_path": row.storage_folder_path,
                "round_number": event.payload.get("round_number"),
                "fingerprint": event.payload.get("fingerprint"),
            },
            emitted_at=datetime.now(timezone.utc),
            emitted_by="state_manager",
        ))

    def _handle_diff_complete(self, context: TenantContext, event: StateEvent) -> None:
        """Structural diff is complete. Transition negotiation to NEGOTIATING and re-emit."""
        self.transition_state(
            context, event.negotiation_id,
            NegotiationState.NEGOTIATING,
            reason=f"Structural diff complete, round {event.payload.get('round_number')} (event from {event.emitted_by})",
        )
        self._audit_write(context, event.negotiation_id, "diff_complete_received", event.payload)
        # Re-emit so Agent 5 can subscribe to State Manager like all other downstream agents
        self._emit(event)

    def _handle_analysis_complete(self, context: TenantContext, event: StateEvent) -> None:
        """Redline analysis is complete. Audit and re-emit for Agent 6."""
        self._audit_write(context, event.negotiation_id, "analysis_complete_received", event.payload)
        self._emit(event)

    def _handle_counter_proposals_ready(self, context: TenantContext, event: StateEvent) -> None:
        """Counter-proposals have been drafted. Enrich payload from ledger and re-emit for Agent 7.

        Enriches with contract_type and counterparty_description from the NegotiationRow so
        Agent 7 does not need to derive these from the storage path convention.
        """
        row = self.get_negotiation(context, event.negotiation_id)
        self._audit_write(context, event.negotiation_id, "counter_proposals_ready_received", event.payload)
        self._emit(StateEvent(
            event_type=event.event_type,
            tenant_id=event.tenant_id,
            negotiation_id=event.negotiation_id,
            workflow_id=event.workflow_id,
            payload={
                **event.payload,
                "contract_type": row.contract_type,
                "counterparty_description": row.counterparty_description,
            },
            emitted_at=datetime.now(timezone.utc),
            emitted_by="state_manager",
        ))

    def _handle_lrs_ready(self, context: TenantContext, event: StateEvent) -> None:
        """LRS document has been generated. Audit and re-emit for Agent 8 (delivery)."""
        self._audit_write(context, event.negotiation_id, "lrs_ready_received", event.payload)
        self._emit(event)

    def _handle_negotiation_paused(self, context: TenantContext, event: StateEvent) -> None:
        """The row owner has paused automation on this negotiation. Principle 2.9 (Opt-Out)."""
        self.update_fields(
            context, event.negotiation_id,
            {"automation_status": "Paused"},
        )

    def _handle_negotiation_resumed(self, context: TenantContext, event: StateEvent) -> None:
        """The row owner has resumed automation on this negotiation."""
        self.update_fields(
            context, event.negotiation_id,
            {"automation_status": "Active"},
        )

    # ============================================================
    # Internal helpers
    # ============================================================

    def _emit(self, event: StateEvent) -> None:
        """Dispatch a state event to all subscribers."""
        for handler in self._subscribers:
            try:
                handler(event)
            except Exception as exc:
                # Subscriber failures must not break State Manager.
                # Log and continue.
                self._audit.record(AuditEvent(
                    event_id=str(uuid.uuid4()),
                    tenant_id=event.tenant_id,
                    negotiation_id=event.negotiation_id,
                    workflow_id=event.workflow_id,
                    agent_name="state_manager",
                    event_type="subscriber_error",
                    timestamp=datetime.now(timezone.utc),
                    payload={
                        "subscriber": getattr(handler, "__qualname__", str(handler)),
                        "error": str(exc),
                        "original_event_type": event.event_type,
                    },
                    severity="error",
                ))

    def _get_tenant_lock(self, tenant_id: str) -> threading.Lock:
        """Return (creating if needed) the write lock for the given tenant."""
        with self._locks_mutex:
            if tenant_id not in self._tenant_locks:
                self._tenant_locks[tenant_id] = threading.Lock()
            return self._tenant_locks[tenant_id]

    def _audit_write(
        self,
        context: TenantContext,
        negotiation_id: Optional[str],
        event_type: str,
        payload: dict,
        severity: str = "info",
    ) -> None:
        """Record an audit event."""
        self._audit.record(AuditEvent(
            event_id=str(uuid.uuid4()),
            tenant_id=context.tenant_id,
            negotiation_id=negotiation_id,
            workflow_id="contract_redline",
            agent_name="state_manager",
            event_type=event_type,
            timestamp=datetime.now(timezone.utc),
            payload=payload,
            severity=severity,
        ))
