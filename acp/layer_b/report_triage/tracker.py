"""Cross-run item tracker for report triage.

Diffs the current normalized records against persisted tracker state.
Classifies each item as: new / aging / resolved / conflict.
Escalates items exceeding the Layer C staleness_threshold_days.

Conflict detection (Option C): if human_status_override indicates closure
but the item still appears in the current run, set conflict_flag=True and
write conflict_detail. Never resolves the conflict autonomously — surfaces it
for human review.

Resolution-by-absence: an item is considered resolved when it no longer
appears in the current report run. The tracker does NOT write back to any
source system to detect resolution — absence from the report is the signal.
Resolved items are archived to the repository via the storage adapter.

Agent-immutable fields: human_notes and human_status_override are read from
the tracker tab for conflict detection but are NEVER written by this module.
See acp/layer_a/behaviors/report_triage_lifecycle.md §3.

Layer C config keys consumed:
    staleness_threshold_days — int; items older than this are escalated
    escalation_owner         — recipient_id for escalation notifications
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from acp.layer_b.report_triage.schemas import RepositoryItem, TrackerItem


class Tracker:
    """Cross-run item tracker.

    Args:
        staleness_threshold_days: Items with run_count or age exceeding this
                                  value are escalated. From Layer C config.
        escalation_owner: Opaque recipient_id for escalation events.
                          From Layer C config.
        storage: StorageAdapter implementation (injected by Layer C).
    """

    def __init__(
        self,
        staleness_threshold_days: int,
        escalation_owner: str,
        storage: object,   # StorageAdapter — typed as object to avoid circular import
    ) -> None:
        self._threshold = staleness_threshold_days
        self._escalation_owner = escalation_owner
        self._storage = storage

    def diff(
        self,
        current_items: list[TrackerItem],
        report_source: str,
        run_date: date,
        run_id: str,
    ) -> tuple[list[TrackerItem], list[TrackerItem]]:
        """Diff current items against persisted tracker state.

        Loads existing TrackerItems for report_source from the storage adapter,
        then computes:
          - present_items: items in current_items (new or updated)
          - absent_items:  items previously tracked but absent this run
                           (resolution candidates)

        Args:
            current_items: Normalized items from this run's report.
            report_source: Identifies which report to scope the diff to.
            run_date: Date of this run.
            run_id: Unique run identifier.

        Returns:
            (present_items, absent_items) tuple of TrackerItem lists.

        Raises:
            NotImplementedError: Implementation deferred to Phase 2.
        """
        raise NotImplementedError("Tracker.diff() — deferred to Phase 2.")

    def classify(
        self,
        item: TrackerItem,
        existing: Optional[TrackerItem],
        run_date: date,
    ) -> TrackerItem:
        """Classify a present item and update its tracker fields.

        Determines status ("new" | "aging" | "escalated" | "conflict") based
        on prior state, run_count, age, staleness_threshold_days, and the
        human_status_override field (read-only conflict detection).

        Never writes human_notes or human_status_override.

        Args:
            item: The normalized item from the current run.
            existing: The prior TrackerItem from storage, or None if new.
            run_date: Date of this run.

        Returns:
            Updated TrackerItem with status, run_count, last_seen, and
            conflict fields set appropriately.

        Raises:
            NotImplementedError: Implementation deferred to Phase 2.
        """
        raise NotImplementedError("Tracker.classify() — deferred to Phase 2.")

    def escalate(self, item: TrackerItem, run_date: date) -> TrackerItem:
        """Mark an aging item as escalated if threshold is exceeded.

        Compares (run_date - item.first_seen).days against
        staleness_threshold_days. If exceeded, sets status="escalated".
        Does not notify — notification is a Layer C action cell concern.

        Args:
            item: TrackerItem with status already set to "aging" or "new".
            run_date: Date of this run.

        Returns:
            TrackerItem with status possibly updated to "escalated".

        Raises:
            NotImplementedError: Implementation deferred to Phase 2.
        """
        raise NotImplementedError("Tracker.escalate() — deferred to Phase 2.")

    def archive(
        self,
        item: TrackerItem,
        resolution_type: str,
        resolved_by: str,
        resolved_date: date,
        run_id: str,
    ) -> RepositoryItem:
        """Convert a resolved TrackerItem to a RepositoryItem and archive it.

        Writes the RepositoryItem to the repository tab via storage adapter
        (append-only), then removes the TrackerItem from the tracker tab.

        Args:
            item: The TrackerItem being resolved.
            resolution_type: One of "dropped_off_report" | "manually_closed"
                             | "conflict_resolved".
            resolved_by: "agent" or human name.
            resolved_date: Date resolution was detected.
            run_id: Run identifier for the archiving run.

        Returns:
            The RepositoryItem that was written.

        Raises:
            NotImplementedError: Implementation deferred to Phase 2.
        """
        raise NotImplementedError("Tracker.archive() — deferred to Phase 2.")
