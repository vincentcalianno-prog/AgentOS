"""Concrete Google Sheets storage adapter for the report triage tracker and repository.

Implements StorageAdapter (Layer B abstract base):
    acp/layer_b/report_triage/storage_adapter.py

Uses the underlying Sheets I/O infrastructure (gspread or Google API client)
that will be wired in the same OAuth pass as the existing SheetsLedger.
Tab names and workbook ID are loaded from sheets_config.yaml — never hardcoded.
The workbook ID itself is loaded from the ANTORA_SHEETS_WORKBOOK_ID environment
variable at runtime — never committed to the repo.

Tracker tab:  upsert by item_key (update row if exists, insert if new).
Repository tab: append-only (never update existing rows).

# ---------------------------------------------------------------------------
# GAP FLAGS — address before Phase 2 implementation sprint
# ---------------------------------------------------------------------------
# GAP (a) — Upsert by item_key:
#   The existing SheetsLedger (acp/layer_c_antora/adapters/sheets_ledger.py)
#   has upsert_row() but it is typed to NegotiationRow (Workflow #1 domain).
#   This adapter needs its own upsert implementation keyed on item_key.
#   Do NOT reuse SheetsLedger.upsert_row() — wrong type, wrong tab layout.
#   Implementation plan: read tracker tab to find row by item_key column,
#   then update in place or append if not found.
#
# GAP (b) — Append-only writes (repository tab):
#   SheetsLedger has no append_row() method. This adapter needs one.
#   Implementation plan: find last populated row in repository tab,
#   then write to the next row. Never overwrite existing rows.
# ---------------------------------------------------------------------------
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml

from acp.layer_b.report_triage.schemas import RepositoryItem, TrackerItem
from acp.layer_b.report_triage.storage_adapter import StorageAdapter


def _load_sheets_config() -> dict:
    """Load sheets_config.yaml from the report_triage Layer C config directory."""
    config_path = Path(__file__).parent.parent / "sheets_config.yaml"
    with config_path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


class SheetsTrackerAdapter(StorageAdapter):
    """Google Sheets storage adapter for report triage tracker and repository.

    Reads workbook_id from ANTORA_SHEETS_WORKBOOK_ID environment variable.
    Tab names (tracker_tab, repository_tab) from sheets_config.yaml.

    Phase 1: all methods raise NotImplementedError.
    Wire alongside the SheetsLedger OAuth setup (Agent 1 pass).
    """

    def __init__(self, credentials_path: Optional[str] = None) -> None:
        config = _load_sheets_config()
        self._tracker_tab = config["tracker_tab"]
        self._repository_tab = config["repository_tab"]
        self._workbook_id = os.environ.get("ANTORA_SHEETS_WORKBOOK_ID", "")
        self._credentials_path = credentials_path
        # In the live implementation, instantiate gspread / Google API client here.
        # See GAP (a) and GAP (b) comments in module docstring before implementing.

    def upsert_tracker_item(self, item: TrackerItem) -> None:
        """Upsert TrackerItem to the tracker tab by item_key.

        Update the existing row if item_key is found; insert a new row otherwise.
        Never writes to the human_notes or human_status_override columns.

        See GAP (a) in module docstring for implementation notes.

        Raises:
            NotImplementedError: Sheets wiring deferred to Phase 2.
        """
        raise NotImplementedError(
            "SheetsTrackerAdapter.upsert_tracker_item() — "
            "Sheets wiring deferred. See GAP (a) in module docstring."
        )

    def append_repository_item(self, item: RepositoryItem) -> None:
        """Append RepositoryItem to the repository tab (append-only).

        Never updates an existing row. Finds the last occupied row in the
        repository tab and writes to the next row.

        See GAP (b) in module docstring for implementation notes.

        Raises:
            NotImplementedError: Sheets wiring deferred to Phase 2.
        """
        raise NotImplementedError(
            "SheetsTrackerAdapter.append_repository_item() — "
            "Sheets wiring deferred. See GAP (b) in module docstring."
        )

    def get_tracker_items(self, report_source: str) -> list[TrackerItem]:
        """Return all TrackerItems for a given report_source from the tracker tab.

        Raises:
            NotImplementedError: Sheets wiring deferred to Phase 2.
        """
        raise NotImplementedError(
            "SheetsTrackerAdapter.get_tracker_items() — Sheets wiring deferred."
        )

    def get_tracker_item(self, item_key: str) -> Optional[TrackerItem]:
        """Return a single TrackerItem by item_key, or None if not found.

        Raises:
            NotImplementedError: Sheets wiring deferred to Phase 2.
        """
        raise NotImplementedError(
            "SheetsTrackerAdapter.get_tracker_item() — Sheets wiring deferred."
        )
