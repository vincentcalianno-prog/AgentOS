"""Abstract interface for ledger storage backends.

Implementations live in layer_c_antora/adapters/ (production) or
layer_b/tests/ (synthetic). layer_b code never imports concrete adapters.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from acp.layer_b.core.types import EventRetryRow, NegotiationRow


class LedgerAdapter(ABC):
    """Tenant-scoped persistent storage for negotiation rows.

    Each tenant has their own ledger. The same adapter can serve multiple
    tenants by namespacing on tenant_id at the storage layer.
    """

    @abstractmethod
    def get_row(self, tenant_id: str, negotiation_id: str) -> Optional[NegotiationRow]:
        """Return the row for the given negotiation, or None if not found."""
        ...

    @abstractmethod
    def list_rows(self, tenant_id: str) -> list[NegotiationRow]:
        """Return all rows in the tenant's ledger."""
        ...

    @abstractmethod
    def upsert_row(self, tenant_id: str, row: NegotiationRow) -> None:
        """Insert or update the row in the tenant's ledger.

        Implementations must enforce that the row is written only to the
        named tenant's storage scope.
        """
        ...

    @abstractmethod
    def get_owner(self, negotiation_id: str) -> Optional[str]:
        """Return the tenant_id that owns this negotiation, or None.

        Used by the tenancy enforcer to verify write authority.
        """
        ...

    @abstractmethod
    def list_all_owners(self) -> dict[str, str]:
        """Return mapping of negotiation_id -> owning tenant_id, across all tenants.

        Used by Agent 9 (Portfolio Aggregator). Read-only operation.
        """
        ...

    @abstractmethod
    def get_row_by_thread_id(self, tenant_id: str, thread_id: str) -> Optional[NegotiationRow]:
        """Return the row whose inbox_thread_id matches thread_id, or None.

        Used by Agent 8 (Workflow Orchestrator) to resolve an inbox thread to a
        known negotiation. Scoped to a single tenant — cross-tenant resolution
        is not supported (each tenant owns their own inbox scope).
        """
        ...

    # ------------------------------------------------------------------ #
    # Retry state                                                          #
    # ------------------------------------------------------------------ #

    @abstractmethod
    def get_retry_state(self, retry_id: str) -> Optional[EventRetryRow]:
        """Return the retry row for the given retry_id, or None if not found."""
        ...

    @abstractmethod
    def upsert_retry_state(self, row: EventRetryRow) -> None:
        """Insert or update a retry row.

        Uses retry_id as the primary key. Callers update attempt_count,
        last_attempt_at, last_error, and status in place.
        """
        ...

    @abstractmethod
    def list_pending_retries(self, tenant_id: Optional[str] = None) -> list[EventRetryRow]:
        """Return all retry rows with status "pending" or "in_progress".

        If tenant_id is provided, filter to that tenant only.
        If tenant_id is None, return pending retries across all tenants
        (used by Agent 8's retry_failed_event sweep).
        """
        ...
