"""Action cell: propose a PO note or status update in the ERP system.

Human-gated: the proposed update is surfaced to the supply chain manager
for approval before any write to the ERP system. The engine never writes
to the ERP autonomously.

Subclasses ActionExecutor from Layer B (acp/layer_b/report_triage/executor.py).
"""

from __future__ import annotations

from acp.layer_b.report_triage.executor import ActionExecutor
from acp.layer_b.report_triage.schemas import TrackerItem


class ERPNoteExecutor(ActionExecutor):
    """Draft and (after approval) write a PO note to the ERP system.

    The ERP system, field names, and API credentials are Layer C config.
    This cell is the concrete wiring; the engine calls the abstract interface.
    """

    def draft(self, item: TrackerItem) -> str:
        """Generate a draft PO note or status update proposal.

        The draft describes the proposed ERP change in human-readable form
        for review before execution.

        Args:
            item: The TrackerItem this note targets.

        Returns:
            Draft proposal text for human review.

        Raises:
            NotImplementedError: Implementation deferred to Phase 2.
        """
        raise NotImplementedError("ERPNoteExecutor.draft() — deferred to Phase 2.")

    def execute(self, item: TrackerItem, approval: bool) -> None:
        """Write the PO note to the ERP system if approved; no-op if rejected.

        Args:
            item: The TrackerItem this action targets.
            approval: True if the human approved the draft.

        Raises:
            NotImplementedError: Implementation deferred to Phase 2.
        """
        raise NotImplementedError("ERPNoteExecutor.execute() — deferred to Phase 2.")
