"""Abstract interface for the immutable audit log.

Per Architecture Spec Principle 2.5 (Immutable Audit Trail), every agent decision,
input, and output is logged to an append-only store.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class AuditEvent:
    """An entry in the audit log.

    Append-only. Once written, never modified.
    """
    event_id: str  # unique per event
    tenant_id: str
    negotiation_id: Optional[str]  # may be None for cross-cutting events
    workflow_id: str  # which workflow this event belongs to (e.g., "contract_redline")
    agent_name: str
    event_type: str
    timestamp: datetime
    payload: dict  # arbitrary structured data
    severity: str = "info"  # info / warning / error / violation


class AuditLogAdapter(ABC):
    """Append-only audit log."""

    @abstractmethod
    def record(self, event: AuditEvent) -> None:
        """Append an event to the audit log. Raises on failure (never silent)."""
        ...

    @abstractmethod
    def query(
        self,
        tenant_id: Optional[str] = None,
        negotiation_id: Optional[str] = None,
        agent_name: Optional[str] = None,
        since: Optional[datetime] = None,
        limit: int = 1000,
    ) -> list[AuditEvent]:
        """Query audit events with optional filters."""
        ...
