"""Agent 9: Portfolio Aggregator.

Per Architecture Spec v2.4 Section 5.9:
"Read from all trackers and produce consolidated team-level views. Agent 9 never
writes to individual trackers; it only reads and produces derived views."

Architecture Spec Section 4.3:
"All cross-tenant reads are read-only and go through Agent 9 (Portfolio Aggregator)."

Query interface only — no process_event(). Runs on-demand; Layer C schedules
refreshes (every 15 minutes during business hours, hourly off-hours per spec).

Cross-workflow by design: aggregates across all registered WorkItemSource
instances. Sources are injected at construction — no source = empty result,
not an error. A failing source is audited as an error and skipped; other
sources' results are still returned.

Audit events use workflow_id="platform" — Agent 9 is platform infrastructure
and may query multiple workflows simultaneously.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from acp.layer_b.core.adapters.audit_adapter import AuditEvent, AuditLogAdapter
from acp.layer_b.core.adapters.work_item_source import WorkItemSource
from acp.layer_b.core.types import (
    ROLE_PORTFOLIO_AGGREGATOR,
    PortfolioReadContext,
    WorkItem,
)
from acp.schemas.playbook_schemas import PlaybookEntry, ReviewerReaction


class PortfolioAggregatorAgent:
    """Read-only cross-tenant cross-workflow portfolio aggregator.

    Provides three query methods:
      - stalled_work_items()   — items with no recent activity
      - queue_depth_by_status() — item count grouped by status
      - throughput_by_owner()  — recently active items per owner

    All methods require a PortfolioReadContext with ROLE_PORTFOLIO_AGGREGATOR.
    Operational thresholds (stall days, throughput window) are caller-supplied;
    Agent 9 has no opinion on what "stalled" means — that is workflow-specific
    and configured in Layer C.
    """

    AGENT_NAME = "portfolio_aggregator"

    def __init__(
        self,
        sources: list[WorkItemSource],
        audit: AuditLogAdapter,
    ) -> None:
        """
        Args:
            sources: Ordered list of WorkItemSources to aggregate. May be empty —
                     queries return empty results rather than erroring.
            audit:   Append-only audit log. Every query is recorded.
        """
        self._sources = list(sources)
        self._audit = audit

    # ------------------------------------------------------------------ #
    # Public query interface                                               #
    # ------------------------------------------------------------------ #

    def stalled_work_items(
        self,
        context: PortfolioReadContext,
        threshold_days: int,
        workflow_id: Optional[str] = None,
        contract_type: Optional[str] = None,
    ) -> list[WorkItem]:
        """Return work items where last_activity_at is older than threshold_days.

        Items with last_activity_at=None are included (no activity = maximally stalled).
        Results are not sorted — callers sort by priority, age, etc. in Layer C.

        Args:
            context:        Portfolio read context with ROLE_PORTFOLIO_AGGREGATOR.
            threshold_days: Items inactive for at least this many days are returned.
            workflow_id:    If set, filter to items from this workflow only.
            contract_type:  If set, filter to items with this contract_type only.
        """
        self._require_portfolio_role(context)
        items = self._collect_all(context)
        now = datetime.now(timezone.utc)
        threshold = timedelta(days=threshold_days)

        result = [
            item for item in items
            if self._matches_filters(item, workflow_id, contract_type)
            and (
                item.last_activity_at is None
                or (now - item.last_activity_at) >= threshold
            )
        ]

        self._audit_write(context, "stalled_work_items_queried", {
            "threshold_days": threshold_days,
            "workflow_id": workflow_id,
            "contract_type": contract_type,
            "result_count": len(result),
        })
        return result

    def queue_depth_by_status(
        self,
        context: PortfolioReadContext,
        workflow_id: Optional[str] = None,
        contract_type: Optional[str] = None,
    ) -> dict[str, int]:
        """Return count of work items grouped by status string.

        Status strings are workflow-defined (e.g. "Negotiating", "On Hold").
        Agent 9 does not interpret them — callers map to display labels in Layer C.

        Args:
            context:       Portfolio read context with ROLE_PORTFOLIO_AGGREGATOR.
            workflow_id:   If set, filter to items from this workflow only.
            contract_type: If set, filter to items with this contract_type only.
        """
        self._require_portfolio_role(context)
        items = self._collect_all(context)

        counts: dict[str, int] = {}
        for item in items:
            if not self._matches_filters(item, workflow_id, contract_type):
                continue
            counts[item.status] = counts.get(item.status, 0) + 1

        self._audit_write(context, "queue_depth_queried", {
            "workflow_id": workflow_id,
            "contract_type": contract_type,
            "status_count": len(counts),
        })
        return counts

    def throughput_by_owner(
        self,
        context: PortfolioReadContext,
        days: int,
        workflow_id: Optional[str] = None,
        contract_type: Optional[str] = None,
    ) -> dict[str, int]:
        """Return count of work items with recent activity per owner.

        "Recent activity" means last_activity_at is within the past `days`.
        Items with last_activity_at=None are excluded (no activity = no throughput).
        This is a proxy for throughput; Layer C determines which statuses count
        as "completed" for workflow-specific throughput metrics.

        Args:
            context:       Portfolio read context with ROLE_PORTFOLIO_AGGREGATOR.
            days:          Activity window in days (inclusive of today).
            workflow_id:   If set, filter to items from this workflow only.
            contract_type: If set, filter to items with this contract_type only.
        """
        self._require_portfolio_role(context)
        items = self._collect_all(context)
        now = datetime.now(timezone.utc)
        window = timedelta(days=days)

        counts: dict[str, int] = {}
        for item in items:
            if not self._matches_filters(item, workflow_id, contract_type):
                continue
            if item.last_activity_at is None:
                continue
            if (now - item.last_activity_at) <= window:
                counts[item.owner] = counts.get(item.owner, 0) + 1

        self._audit_write(context, "throughput_queried", {
            "days": days,
            "workflow_id": workflow_id,
            "contract_type": contract_type,
            "owner_count": len(counts),
        })
        return counts

    def detect_playbook_update_candidates(
        self,
        entries: list[PlaybookEntry],
    ) -> list[tuple[str, int, str]]:
        """Surface PlaybookEntry candidates for playbook update review.

        An entry is a candidate when its recommendation_reviews list contains
        2 or more EDITED reactions from legal reviewers (reviewer_role starts
        with "legal:"). Multiple legal edits on the same clause type are the
        strongest signal that the playbook position needs recalibration.

        Returns a list of (entry_id, edit_count, sample_rationale) tuples.
        sample_rationale is the rationale from the first qualifying EDITED
        review, or "" if no rationale was provided.

        Does NOT update the playbook — surfaces candidates for Sandelin's
        review only. Phase 3 notification wiring goes here.

        # TODO Phase 3: wire to notification system
        """
        candidates = []
        for entry in entries:
            legal_edits = [
                r for r in entry.recommendation_reviews
                if r.reaction == ReviewerReaction.EDITED
                and r.reviewer_role.startswith("legal:")
            ]
            if len(legal_edits) >= 2:
                sample_rationale = legal_edits[0].rationale if legal_edits else ""
                candidates.append((entry.id, len(legal_edits), sample_rationale))
        return candidates

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _collect_all(self, context: PortfolioReadContext) -> list[WorkItem]:
        """Aggregate WorkItems from all registered sources.

        Source exceptions are caught, audited as errors, and skipped —
        partial results from other sources are still returned.
        """
        items: list[WorkItem] = []
        for source in self._sources:
            try:
                items.extend(source.get_work_items(context))
            except Exception as exc:
                self._audit_write(
                    context,
                    "source_error",
                    {"source_name": source.source_name, "error": str(exc)},
                    severity="error",
                )
        return items

    @staticmethod
    def _matches_filters(
        item: WorkItem,
        workflow_id: Optional[str],
        contract_type: Optional[str],
    ) -> bool:
        if workflow_id is not None and item.workflow_id != workflow_id:
            return False
        if contract_type is not None and item.contract_type != contract_type:
            return False
        return True

    def _require_portfolio_role(self, context: PortfolioReadContext) -> None:
        """Raise PermissionError if the context lacks ROLE_PORTFOLIO_AGGREGATOR."""
        if not context.has_role(ROLE_PORTFOLIO_AGGREGATOR):
            raise PermissionError(
                f"PortfolioAggregatorAgent requires role '{ROLE_PORTFOLIO_AGGREGATOR}'; "
                f"reader '{context.reader_id}' has roles: {context.roles}"
            )

    def _audit_write(
        self,
        context: PortfolioReadContext,
        event_type: str,
        payload: dict,
        severity: str = "info",
    ) -> None:
        self._audit.record(AuditEvent(
            event_id=str(uuid.uuid4()),
            tenant_id=context.reader_id,
            negotiation_id=None,
            workflow_id="platform",
            agent_name=self.AGENT_NAME,
            event_type=event_type,
            timestamp=datetime.now(timezone.utc),
            payload=payload,
            severity=severity,
        ))
