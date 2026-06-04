"""Action cell: draft buyer nudge email for report triage items.

Template-first implementation — no LLM call unless template output is
demonstrably insufficient. The template is filled from TrackerItem fields;
if the result is clear and actionable, the LLM path is skipped entirely.

Human-gated: the draft email is proposed to the supply chain manager for
approval before send. The engine never sends email autonomously.

Subclasses ActionExecutor from Layer B (acp/layer_b/report_triage/executor.py).
"""

from __future__ import annotations

from acp.layer_b.report_triage.executor import ActionExecutor
from acp.layer_b.report_triage.schemas import TrackerItem


# ---------------------------------------------------------------------------
# Email template — fill from TrackerItem fields.
# TODO: refine subject line and body once column_map is populated.
# ---------------------------------------------------------------------------
_EMAIL_SUBJECT_TEMPLATE = (
    "Action Required: {description} — PO outstanding"
)

_EMAIL_BODY_TEMPLATE = """\
Hi {owner},

This is a reminder that the following item remains outstanding on the {report_source} report:

  Description:  {description}
  Amount:       {dollar_amount}
  First seen:   {first_seen}
  Days open:    {days_open}

Please take action or update the tracker with your status.

Thank you.
"""


class BuyerEmailExecutor(ActionExecutor):
    """Draft and (after approval) send a buyer nudge email.

    Template-first: fills _EMAIL_BODY_TEMPLATE from TrackerItem fields.
    LLM path not yet wired — to be added in Phase 2 if template proves
    insufficient for complex items.
    """

    def draft(self, item: TrackerItem) -> str:
        """Generate a draft nudge email for the buyer assigned to this item.

        Fills the template from item fields. Returns the full email text
        (subject + body) for human review.

        Args:
            item: The TrackerItem to draft a nudge for.

        Returns:
            Draft email text for human review.

        Raises:
            NotImplementedError: Implementation deferred to Phase 2.
        """
        raise NotImplementedError("BuyerEmailExecutor.draft() — deferred to Phase 2.")

    def execute(self, item: TrackerItem, approval: bool) -> None:
        """Send the nudge email if approved; no-op if rejected.

        Args:
            item: The TrackerItem this action targets.
            approval: True if the human approved the draft.

        Raises:
            NotImplementedError: Implementation deferred to Phase 2.
        """
        raise NotImplementedError("BuyerEmailExecutor.execute() — deferred to Phase 2.")
