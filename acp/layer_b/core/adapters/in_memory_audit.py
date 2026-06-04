"""In-memory audit log adapter for development and testing.

For production, a persistent backend (e.g., append-only Drive log, Google Sheets,
or a dedicated audit database) is required. The InMemoryAuditLog respects the
same interface so swapping backends requires no agent code changes.
"""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Optional

from acp.layer_b.core.adapters.audit_adapter import AuditEvent, AuditLogAdapter


class InMemoryAuditLog(AuditLogAdapter):
    """Thread-safe in-memory append-only audit log."""

    def __init__(self):
        self._events: list[AuditEvent] = []
        self._lock = threading.Lock()

    def record(self, event: AuditEvent) -> None:
        with self._lock:
            self._events.append(event)

    def query(
        self,
        tenant_id: Optional[str] = None,
        negotiation_id: Optional[str] = None,
        agent_name: Optional[str] = None,
        since: Optional[datetime] = None,
        limit: int = 1000,
    ) -> list[AuditEvent]:
        with self._lock:
            results = []
            # Reverse iteration to get most-recent first
            for event in reversed(self._events):
                if tenant_id is not None and event.tenant_id != tenant_id:
                    continue
                if negotiation_id is not None and event.negotiation_id != negotiation_id:
                    continue
                if agent_name is not None and event.agent_name != agent_name:
                    continue
                if since is not None and event.timestamp < since:
                    continue
                results.append(event)
                if len(results) >= limit:
                    break
        return results

    def count(self) -> int:
        with self._lock:
            return len(self._events)
