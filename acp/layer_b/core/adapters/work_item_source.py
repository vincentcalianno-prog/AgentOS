"""Abstract interface for WorkItem sources consumed by Agent 9 (Portfolio Aggregator).

Each workflow registers a WorkItemSource implementation that maps its domain
objects to the workflow-agnostic WorkItem schema. Agent 9 receives a list of
sources via dependency injection and aggregates across all of them.

Per Architecture Spec Section 4.3: all cross-tenant reads are read-only and go
through Agent 9. Sources may be queried in any order; Agent 9 aggregates
best-effort (a failing source does not abort the query).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from acp.layer_b.core.types import PortfolioReadContext, WorkItem


class WorkItemSource(ABC):
    """Abstract interface for providing WorkItems to Agent 9.

    Implementations:
      - acp.layer_b.agents.contract_redline_source.ContractRedlineWorkItemSource
      - Future workflows register their own implementations in Layer C.

    Contract:
      - get_work_items() must return an empty list on error rather than raising.
        Log/audit internally; Agent 9 does not crash on source failures.
      - source_name must be stable across calls (used in audit records).
    """

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Stable human-readable identifier for this source (e.g. "contract_redline").

        Used in audit events and error messages. Must not change between calls.
        """
        ...

    @abstractmethod
    def get_work_items(self, context: PortfolioReadContext) -> list[WorkItem]:
        """Return all current WorkItems visible to this source.

        Args:
            context: The portfolio read context. Implementations may inspect
                     context.reader_id for audit purposes.

        Returns:
            A list of WorkItems. Empty list if no items exist or on error.
        """
        ...
