"""Tabular parser for report triage input files.

Accepts raw bytes + a format hint from Layer C config.
Supports: csv, spreadsheetml_xml2003, xlsx.
Returns a list of raw row dicts (column name → raw string value).

Format detection logic lives here; column semantics live in the Layer C
normalizer config (column_map). No column names or report-specific logic
are hardcoded in this module.

Layer C config key consumed:
    format — one of: "csv" | "spreadsheetml_xml2003" | "xlsx"
"""

from __future__ import annotations


# SpreadsheetML XML-2003: these files have .xls extension but are XML, not BIFF.
# openpyxl and xlrd both reject them. Parse with xml.etree.ElementTree or lxml.
# Do not attempt pd.read_excel() — it will fail silently or raise on this format.


class TabularParser:
    """Dispatch parser for tabular report formats.

    Usage::

        parser = TabularParser()
        rows = parser.parse(raw_bytes, fmt="csv")
    """

    def parse(self, raw_bytes: bytes, fmt: str) -> list[dict[str, str]]:
        """Dispatch to the appropriate format parser.

        Args:
            raw_bytes: Raw file content as bytes.
            fmt: Format hint from Layer C config. One of:
                 "csv" | "spreadsheetml_xml2003" | "xlsx"

        Returns:
            List of row dicts mapping column header → raw cell value (str).
            Empty rows are skipped. Header row is not included in output.

        Raises:
            ValueError: If fmt is not a recognised format.
            NotImplementedError: Individual format parsers not yet implemented.
        """
        dispatch = {
            "csv": self._parse_csv,
            "spreadsheetml_xml2003": self._parse_spreadsheetml_xml2003,
            "xlsx": self._parse_xlsx,
        }
        if fmt not in dispatch:
            raise ValueError(
                f"Unknown format {fmt!r}. Expected one of: {sorted(dispatch)}"
            )
        return dispatch[fmt](raw_bytes)

    def _parse_csv(self, raw_bytes: bytes) -> list[dict[str, str]]:
        """Parse CSV bytes into a list of row dicts.

        Uses the standard library csv module. Encoding is detected or
        falls back to utf-8. The first non-empty row is treated as the
        header.

        Returns:
            List of dicts: {header_col: cell_value, ...} for each data row.

        Raises:
            NotImplementedError: Implementation deferred to Phase 2.
        """
        raise NotImplementedError("TabularParser._parse_csv() — deferred to Phase 2.")

    def _parse_spreadsheetml_xml2003(self, raw_bytes: bytes) -> list[dict[str, str]]:
        """Parse SpreadsheetML XML-2003 bytes into a list of row dicts.

        SpreadsheetML XML-2003: these files have .xls extension but are XML,
        not BIFF. openpyxl and xlrd both reject them. Use xml.etree.ElementTree
        or lxml to parse the XML directly. The Worksheet/Table/Row/Cell
        structure maps naturally to header + data rows.

        Returns:
            List of dicts: {header_col: cell_value, ...} for each data row.

        Raises:
            NotImplementedError: Implementation deferred to Phase 2.
        """
        raise NotImplementedError(
            "TabularParser._parse_spreadsheetml_xml2003() — deferred to Phase 2. "
            "Use xml.etree.ElementTree or lxml, NOT openpyxl/xlrd/pd.read_excel."
        )

    def _parse_xlsx(self, raw_bytes: bytes) -> list[dict[str, str]]:
        """Parse XLSX bytes into a list of row dicts.

        Uses openpyxl (or equivalent) to open the workbook from bytes.
        Reads the first sheet. The first non-empty row is treated as the header.

        Returns:
            List of dicts: {header_col: cell_value, ...} for each data row.

        Raises:
            NotImplementedError: Implementation deferred to Phase 2.
        """
        raise NotImplementedError("TabularParser._parse_xlsx() — deferred to Phase 2.")
