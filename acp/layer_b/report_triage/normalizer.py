"""Column-map-driven normalizer for report triage.

Accepts raw row dicts (from parser.py) plus a Layer C column_map config.
Maps arbitrary source columns to canonical TrackerItem fields.

Handles edge cases driven by Layer C config:
  - Junk dates: 1900-01-01 Excel sentinel → treat as None/missing
  - Missing owner field: triggers the Layer C owner_fallback_rule lookup
  - Per-PO vs per-PO-line grain: controlled by Layer C grain config
    ("per_po" | "per_po_line")

No source column names are hardcoded here. All column semantics come
from the column_map supplied at call time.

Layer C config keys consumed by this module:
    column_map        — {source_col: canonical_field} mapping dict
    grain             — "per_po" | "per_po_line"
    owner_field       — source column that identifies the item owner
    owner_fallback_rule — rule applied when owner_field is absent/sentinel
    item_key_fields   — list of canonical fields that form the composite key
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from acp.layer_b.report_triage.schemas import TrackerItem


# Sentinel date produced by Excel when a date cell is blank or zero-valued.
# Normalizer treats this as missing (None).
_EXCEL_EPOCH_SENTINEL = date(1900, 1, 1)


class Normalizer:
    """Column-map-driven normalizer.

    Maps raw row dicts → TrackerItem instances using a Layer C column_map.
    All source-column knowledge lives in the column_map; this class has no
    awareness of any specific report layout.

    Args:
        column_map: dict mapping source column names to canonical TrackerItem
                    field names. Supplied from Layer C report config.
        item_key_fields: list of canonical field names used to build the
                         composite item_key. Supplied from Layer C config.
        grain: "per_po" | "per_po_line" — controls deduplication strategy.
        owner_fallback_rule: opaque rule string; interpretation is Layer C
                             concern. The normalizer passes it to
                             resolve_owner() which Layer C must provide.
        report_source: identifier for the source report (from Layer C config).
    """

    def __init__(
        self,
        column_map: dict[str, str],
        item_key_fields: list[str],
        grain: str,
        owner_fallback_rule: Optional[str],
        report_source: str,
    ) -> None:
        self._column_map = column_map
        self._item_key_fields = item_key_fields
        self._grain = grain
        self._owner_fallback_rule = owner_fallback_rule
        self._report_source = report_source

    def normalize(
        self,
        raw_rows: list[dict[str, str]],
        run_date: date,
        run_id: str,
    ) -> list[TrackerItem]:
        """Normalize a list of raw row dicts into TrackerItem stubs.

        Each row is mapped through column_map, a composite item_key is
        built from item_key_fields, and owner resolution is applied.
        Returns one TrackerItem per input row (after deduplication by grain).

        Args:
            raw_rows: Output of TabularParser.parse() for this run.
            run_date: The date of this run (used as first_seen / last_seen
                      for newly encountered items).
            run_id: Unique identifier for this run.

        Returns:
            List of TrackerItem instances with all canonical fields populated.
            human_notes and human_status_override are always None from the
            normalizer — they are populated only from the tracker tab read.

        Raises:
            NotImplementedError: Implementation deferred to Phase 2.
        """
        raise NotImplementedError("Normalizer.normalize() — deferred to Phase 2.")

    def _map_row(self, raw_row: dict[str, str]) -> dict[str, object]:
        """Apply column_map to a single raw row dict.

        Returns a dict keyed by canonical field names. Source columns not
        present in column_map are silently dropped. Values are left as raw
        strings; type coercion happens in _coerce_fields().

        Raises:
            NotImplementedError: Implementation deferred to Phase 2.
        """
        raise NotImplementedError("Normalizer._map_row() — deferred to Phase 2.")

    def _build_item_key(self, canonical_row: dict[str, object]) -> str:
        """Build a composite item_key from item_key_fields.

        Joins the values of item_key_fields in order with '|' separator.
        Includes the report_source prefix to ensure cross-report uniqueness.

        Raises:
            NotImplementedError: Implementation deferred to Phase 2.
        """
        raise NotImplementedError("Normalizer._build_item_key() — deferred to Phase 2.")

    def _resolve_owner(self, canonical_row: dict[str, object]) -> str:
        """Resolve the owner for a row.

        If the owner field value is present and not a sentinel, return it.
        Otherwise apply owner_fallback_rule (Layer C logic). The fallback
        rule string is opaque to this module; Layer C provides the resolver.

        Raises:
            NotImplementedError: Implementation deferred to Phase 2.
        """
        raise NotImplementedError("Normalizer._resolve_owner() — deferred to Phase 2.")

    def _coerce_date(self, val: Optional[str]) -> Optional[date]:
        """Parse a date string and suppress the Excel 1900-01-01 sentinel.

        Returns None for None input, empty strings, or the sentinel date.

        Raises:
            NotImplementedError: Implementation deferred to Phase 2.
        """
        raise NotImplementedError("Normalizer._coerce_date() — deferred to Phase 2.")
