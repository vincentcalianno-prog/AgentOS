"""WorkItemSource implementation for the contract_redline workflow.

Maps NegotiationRows from the ledger to workflow-agnostic WorkItems for
consumption by Agent 9 (Portfolio Aggregator).

Cross-tenant read pattern:
  1. ledger.list_all_owners() → {negotiation_id: tenant_id} across all tenants
  2. Derive unique tenant_ids from the result
  3. ledger.list_rows(tenant_id) per tenant → list[NegotiationRow]
  4. Map each NegotiationRow → WorkItem

This bypasses StateManager and TenancyEnforcer intentionally — read-only
cross-tenant access is the entire purpose of Agent 9. The PortfolioReadContext
passed to get_work_items() carries ROLE_PORTFOLIO_AGGREGATOR, which authorises
the cross-tenant read at the Agent 9 level. Access is audited by the caller
(PortfolioAggregatorAgent._collect_all).

NegotiationRow has no created_at field, so WorkItem.created_at maps to None.
Layer C deployments can subclass and override _map_row() if a creation
timestamp is added to the ledger schema in a future release.
"""

from __future__ import annotations

from acp.layer_b.core.adapters.ledger_adapter import LedgerAdapter
from acp.layer_b.core.adapters.work_item_source import WorkItemSource
from acp.layer_b.core.types import PortfolioReadContext, WorkItem


class ContractRedlineWorkItemSource(WorkItemSource):
    """Provides WorkItems from the contract_redline workflow.

    Reads NegotiationRows across all tenants via the ledger's cross-tenant
    index (list_all_owners + list_rows). No LLM, no storage access, no events.
    """

    def __init__(self, ledger: LedgerAdapter) -> None:
        """
        Args:
            ledger: The shared ledger adapter. Must support list_all_owners()
                    and list_rows(tenant_id) — both defined on LedgerAdapter.
        """
        self._ledger = ledger

    @property
    def source_name(self) -> str:
        return "contract_redline"

    def get_work_items(self, context: PortfolioReadContext) -> list[WorkItem]:
        """Return all NegotiationRows across all tenants as WorkItems.

        Errors from the ledger propagate to the caller (PortfolioAggregatorAgent
        catches and audits them as source_error). Returns an empty list if the
        ledger has no rows.
        """
        owner_map = self._ledger.list_all_owners()
        tenant_ids = set(owner_map.values())

        items: list[WorkItem] = []
        for tenant_id in tenant_ids:
            rows = self._ledger.list_rows(tenant_id)
            for row in rows:
                items.append(self._map_row(row, tenant_id))
        return items

    def _map_row(self, row, tenant_id: str) -> WorkItem:
        """Map a NegotiationRow to a WorkItem.

        Field mapping:
            work_item_id    ← negotiation_id
            tenant_id       ← caller-supplied tenant_id (from list_all_owners)
            workflow_id     ← row.workflow_id
            owner           ← row.owner
            status          ← row.status.value  (NegotiationState enum → string)
            created_at      ← None  (NegotiationRow has no creation timestamp)
            last_activity_at← row.last_activity_date
            counterparty_name← row.counterparty_description
            contract_type   ← row.contract_type
            payload_summary ← {round_number, priority, automation_status}
        """
        return WorkItem(
            work_item_id=row.negotiation_id,
            tenant_id=tenant_id,
            workflow_id=row.workflow_id,
            owner=row.owner,
            status=row.status.value,
            created_at=None,
            last_activity_at=row.last_activity_date,
            counterparty_name=row.counterparty_description,
            contract_type=row.contract_type,
            payload_summary={
                "round_number": row.round_number,
                "priority": row.priority,
                "automation_status": row.automation_status,
            },
        )
