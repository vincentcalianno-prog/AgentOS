"""Core types for ACP.

Generic, contract-type-agnostic, domain-agnostic. No deployment-specific values.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


# ============================================================
# State Machine
# ============================================================

class NegotiationState(str, Enum):
    """Negotiation lifecycle states. Per Architecture Spec Section 6.4."""
    NOT_STARTED = "Not Started"
    REQUESTED = "Requested"
    CONTRACT_SENT = "Contract Sent"  # generic; deployments may display as a contract-type-specific label
    REDLINES_RECEIVED = "Redlines Received"
    NEGOTIATING = "Negotiating"
    PENDING_SIGNATURE = "Pending Signature"
    EXECUTED_ACTIVE = "Executed / Active"
    ON_HOLD = "On Hold"
    WILL_NOT_EXECUTE = "Will Not Execute"


# Allowed transitions. Keys are source state; values are reachable destination states.
# Terminal states have no outbound transitions except to ON_HOLD or WILL_NOT_EXECUTE.
_ALLOWED_TRANSITIONS: dict[NegotiationState, set[NegotiationState]] = {
    NegotiationState.NOT_STARTED: {
        NegotiationState.REQUESTED,
        NegotiationState.ON_HOLD,
        NegotiationState.WILL_NOT_EXECUTE,
    },
    NegotiationState.REQUESTED: {
        NegotiationState.CONTRACT_SENT,
        NegotiationState.ON_HOLD,
        NegotiationState.WILL_NOT_EXECUTE,
    },
    NegotiationState.CONTRACT_SENT: {
        NegotiationState.REDLINES_RECEIVED,
        NegotiationState.NEGOTIATING,  # counterparty may accept and counter-sign with minor changes
        NegotiationState.PENDING_SIGNATURE,  # counterparty accepts as-is
        NegotiationState.ON_HOLD,
        NegotiationState.WILL_NOT_EXECUTE,
    },
    NegotiationState.REDLINES_RECEIVED: {
        NegotiationState.NEGOTIATING,
        NegotiationState.ON_HOLD,
        NegotiationState.WILL_NOT_EXECUTE,
    },
    NegotiationState.NEGOTIATING: {
        NegotiationState.NEGOTIATING,  # multi-round; stays in this state
        NegotiationState.REDLINES_RECEIVED,  # new round arrived
        NegotiationState.PENDING_SIGNATURE,
        NegotiationState.ON_HOLD,
        NegotiationState.WILL_NOT_EXECUTE,
    },
    NegotiationState.PENDING_SIGNATURE: {
        NegotiationState.EXECUTED_ACTIVE,
        NegotiationState.NEGOTIATING,  # signature blocked, back to negotiation
        NegotiationState.ON_HOLD,
        NegotiationState.WILL_NOT_EXECUTE,
    },
    NegotiationState.EXECUTED_ACTIVE: set(),  # terminal
    NegotiationState.ON_HOLD: {
        # Re-entry to active flow
        NegotiationState.NOT_STARTED,
        NegotiationState.REQUESTED,
        NegotiationState.NEGOTIATING,
        NegotiationState.WILL_NOT_EXECUTE,
    },
    NegotiationState.WILL_NOT_EXECUTE: set(),  # terminal
}


def is_valid_transition(src: NegotiationState, dst: NegotiationState) -> bool:
    """Return True if transitioning from src to dst is allowed by the state machine.

    Same-state "transitions" are allowed (idempotent updates).
    """
    if src == dst:
        return True
    return dst in _ALLOWED_TRANSITIONS.get(src, set())


def allowed_next_states(src: NegotiationState) -> set[NegotiationState]:
    """Return the set of states reachable from src."""
    return _ALLOWED_TRANSITIONS.get(src, set()) | {src}


# ============================================================
# Tenant Context
# ============================================================

@dataclass(frozen=True)
class TenantContext:
    """Identifies the tenant making an operation. Passed explicitly to every state op.

    Architecture Spec Section 4.1: per-tenant write surfaces; Agent 9 reads cross-tenant.
    """
    tenant_id: str
    roles: frozenset[str] = field(default_factory=frozenset)

    def has_role(self, role: str) -> bool:
        return role in self.roles


# Singleton-style role names used by the tenancy enforcer
ROLE_PORTFOLIO_AGGREGATOR = "portfolio_aggregator"
ROLE_AUDIT_READER = "audit_reader"


# ============================================================
# Negotiation Row
# ============================================================

@dataclass
class NegotiationRow:
    """A single row in a tenant's tracker.

    Generic: contract-type-agnostic and domain-agnostic. The deploying
    organization configures human-readable labels (e.g., "Contract Manager",
    "Supply Chain Manager", "Deal Lead") in Layer C; the data model uses
    neutral names.

    All fields except negotiation_id and owner are optional / nullable to
    accommodate rows in progress.
    """
    # Identity
    negotiation_id: str  # internal stable ID; not the # column (that's display-only)
    row_number: int  # the # column (display-only)
    owner: str  # the tenant who owns this row (e.g., a Contract Manager identifier)
    workflow_id: str  # which workflow this negotiation belongs to (e.g., "contract_redline")

    # Human-writable narrative fields
    category: Optional[str] = None
    priority: Optional[str] = None
    counterparty_description: Optional[str] = None
    whos_court: Optional[str] = None
    status: NegotiationState = NegotiationState.NOT_STARTED
    comments: Optional[str] = None
    action_next_steps: Optional[str] = None

    # Configuration and state fields (mix of human + agent writable)
    contract_type: Optional[str] = None  # deployment-defined values
    round_number: int = 0
    last_outbound_version_sent: Optional[str] = None  # storage path to most recent outbound version
    last_counterparty_version: Optional[str] = None  # storage path to most recent counterparty version
    last_activity_date: Optional[datetime] = None
    inbox_thread_id: Optional[str] = None  # generic: maps to Gmail thread ID, Outlook conversation ID, etc.
    storage_folder_path: Optional[str] = None  # generic: maps to Drive folder, OneDrive folder, etc.
    review_package_status: Optional[str] = None  # status of the legal review package for the current round
    counterparty_profile_ref: Optional[str] = None
    last_review_package_sent_date: Optional[datetime] = None
    automation_status: str = "Manual Only"  # Active / Paused / Manual Only
    audit_log_ref: Optional[str] = None


# ============================================================
# Events
# ============================================================

@dataclass(frozen=True)
class StateEvent:
    """An event emitted by an agent that requires State Manager processing.

    Generic, contract-type-agnostic. Specific event types defined as string constants.
    """
    event_type: str
    tenant_id: str  # the tenant scope this event belongs to
    negotiation_id: str
    workflow_id: str  # which workflow this event belongs to (e.g., "contract_redline")
    payload: dict
    emitted_at: datetime
    emitted_by: str  # agent identifier


# Event type constants
EVENT_OUTBOUND_CONTRACT_SENT = "outbound_contract_sent"
EVENT_INBOUND_REDLINE_RECEIVED = "inbound_redline_received"
EVENT_INBOUND_NON_REDLINE = "inbound_non_redline"
EVENT_DOCUMENT_EXTRACTED = "document_extracted"
EVENT_DOCUMENT_EXTRACTION_REQUIRED = "document_extraction_required"
EVENT_ROUND_READY_FOR_ANALYSIS = "round_ready_for_analysis"
EVENT_DIFF_COMPLETE = "diff_complete"
EVENT_ANALYSIS_COMPLETE = "analysis_complete"
EVENT_COUNTER_PROPOSALS_READY = "counter_proposals_ready"
EVENT_LRS_DELIVERED = "lrs_delivered"
EVENT_LRS_APPROVED = "lrs_approved"
EVENT_LRS_RETURNED = "lrs_returned"
EVENT_NEGOTIATION_PAUSED = "negotiation_paused"
EVENT_NEGOTIATION_RESUMED = "negotiation_resumed"


# ============================================================
# Exceptions
# ============================================================

class StateManagerError(Exception):
    """Base exception for State Manager."""


class InvalidTransitionError(StateManagerError):
    """Raised when a requested state transition is not allowed."""


class TenancyViolation(StateManagerError):
    """Raised when a tenant attempts to access another tenant's data."""


class NegotiationNotFoundError(StateManagerError):
    """Raised when a negotiation_id is not found in the tenant's scope."""


class ConcurrencyError(StateManagerError):
    """Raised on optimistic concurrency control failure (stale write)."""
