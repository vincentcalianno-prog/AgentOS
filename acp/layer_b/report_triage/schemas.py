"""Canonical dataclasses for the report triage workflow engine.

TrackerItem  — mutable working state for an open item across runs.
RepositoryItem — immutable record written when an item is resolved.

These schemas are the Layer B data contract. Layer C column_map config
translates report-specific source columns into these canonical field names.
No report names, buyer names, or org-specific column names appear here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional


# ---------------------------------------------------------------------------
# AGENT-IMMUTABLE FIELDS
# human_notes and human_status_override are read-only from the engine's
# perspective. tracker.py must never write to these fields.
# This is a Layer A behavioral constraint — see:
#   acp/layer_a/behaviors/report_triage_lifecycle.md §3
# ---------------------------------------------------------------------------


@dataclass(frozen=False)
class TrackerItem:
    """Mutable working state for a single tracked item across runs.

    One TrackerItem exists per unique item_key in the active tracker tab.
    The engine reads and updates most fields each run; human_notes and
    human_status_override are AGENT-IMMUTABLE — the engine reads them for
    conflict detection but never overwrites them.

    status values: "new" | "aging" | "escalated" | "conflict" | "manually_closed"
    """
    item_key: str
    report_source: str
    owner: str
    first_seen: date
    last_seen: date
    run_count: int
    status: str          # "new" | "aging" | "escalated" | "conflict" | "manually_closed"
    entity_name: str     # the trading-partner / entity this item concerns
    description: str
    dollar_amount: Optional[float]
    expected_receipt_date: Optional[date]
    agent_summary: Optional[str]
    last_run_id: str
    conflict_flag: bool
    conflict_detail: Optional[str]

    # AGENT-IMMUTABLE — the engine reads these but must never overwrite them.
    # Set only by humans via the tracker tab.
    human_notes: Optional[str] = field(default=None)
    human_status_override: Optional[str] = field(default=None)


@dataclass(frozen=True)
class RepositoryItem:
    """Immutable record written to the repository tab when an item is resolved.

    Once written, a RepositoryItem is never updated — the repository tab is
    append-only. resolution_type classifies how the item left the tracker.

    resolution_type values:
        "dropped_off_report"   — item no longer appears in latest report run
        "manually_closed"      — human set human_status_override to a closed state
        "conflict_resolved"    — conflict_flag was set and human resolved it
    """
    item_key: str
    report_source: str
    owner: str
    entity_name: str     # the trading-partner / entity this item concerned
    description: str
    dollar_amount: Optional[float]
    first_seen: date
    resolved_date: date
    resolution_type: str   # "dropped_off_report" | "manually_closed" | "conflict_resolved"
    resolved_by: str       # "agent" or human name
    total_runs_open: int
    total_days_open: int
    human_notes: Optional[str]
    archived_run_id: str
