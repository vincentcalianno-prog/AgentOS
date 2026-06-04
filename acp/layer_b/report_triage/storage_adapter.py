"""Abstract storage adapter interface for report triage tracker and repository.

Concrete implementation (Google Sheets) lives in Layer C:
    acp/layer_c_antora/report_triage/storage/sheets_tracker_adapter.py

Tracker tab:  upsert by item_key — update row if exists, insert if new.
Repository tab: append-only — never update existing rows.

Read methods (get_tracker_items, get_tracker_item) are required so
tracker.py can diff against prior state without coupling to a specific
storage backend.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from acp.layer_b.report_triage.schemas import RepositoryItem, TrackerItem


class StorageAdapter(ABC):
    """Abstract storage adapter for the report triage workflow.

    Layer B engine components (tracker.py) depend on this interface.
    Concrete implementations are Layer C cells.
    """

    @abstractmethod
    def upsert_tracker_item(self, item: TrackerItem) -> None:
        """Write a TrackerItem to the tracker tab.

        If a row with item.item_key already exists, update it in place.
        If no such row exists, insert a new row.

        Never writes to human_notes or human_status_override columns —
        those are agent-immutable (see Layer A behavioral contract).

        Args:
            item: The TrackerItem to persist.
        """

    @abstractmethod
    def append_repository_item(self, item: RepositoryItem) -> None:
        """Append a RepositoryItem to the repository tab.

        The repository tab is append-only. This method must never update
        an existing row — each call adds a new row at the end of the tab.

        Args:
            item: The resolved RepositoryItem to archive.
        """

    @abstractmethod
    def get_tracker_items(self, report_source: str) -> list[TrackerItem]:
        """Return all TrackerItems for a given report_source.

        Used by tracker.py to load prior state for diffing. Returns an
        empty list if no items exist for this report_source.

        Args:
            report_source: The report identifier to filter by.

        Returns:
            List of TrackerItems currently in the tracker tab for this source.
        """

    @abstractmethod
    def get_tracker_item(self, item_key: str) -> Optional[TrackerItem]:
        """Return a single TrackerItem by item_key, or None if not found.

        Args:
            item_key: The composite key identifying the item.

        Returns:
            The TrackerItem if found, None otherwise.
        """
