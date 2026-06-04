"""Abstract ActionExecutor interface for report triage.

Concrete implementations live in Layer C (e.g. buyer_email.py,
netsuite_update.py). Each implementation targets a specific action type
(send email, propose system update, etc.).

All actions are human-gated: the agent drafts or proposes an action,
a human approves it, then execute() carries it out. The engine never
autonomously writes to any external system.

Autonomy gate: recommend → approve → execute.
See acp/layer_a/behaviors/report_triage_lifecycle.md §2.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from acp.layer_b.report_triage.schemas import TrackerItem


class ActionExecutor(ABC):
    """Abstract base for report triage action executors.

    Concrete implementations live in Layer C. Each executor targets one
    action type (email, system update, etc.) and one deployment context.

    All actions are human-gated: draft() generates a proposal for human
    review; execute() carries it out only after human approval is confirmed.
    """

    @abstractmethod
    def draft(self, item: TrackerItem) -> str:
        """Generate a human-readable draft action proposal for this item.

        The draft is shown to a human for review before any external action
        is taken. The format is executor-specific (email body, note text, etc.).

        Args:
            item: The TrackerItem this action targets.

        Returns:
            A human-readable string representing the proposed action.
            The human reviews and either approves or rejects it.
        """

    @abstractmethod
    def execute(self, item: TrackerItem, approval: bool) -> None:
        """Execute the action for this item, contingent on human approval.

        Called after the human has reviewed the draft. If approval is False,
        the executor must NOT perform any external write — it may log the
        rejection but must take no other action.

        Args:
            item: The TrackerItem this action targets.
            approval: True if the human approved the draft, False otherwise.
        """
