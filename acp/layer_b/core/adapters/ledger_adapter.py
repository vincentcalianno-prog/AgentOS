"""Abstract interface for ledger storage backends.

Implementations live in layer_c_antora/adapters/ (production) or
layer_b/tests/ (synthetic). layer_b code never imports concrete adapters.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from acp.layer_b.core.types import NegotiationRow


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
