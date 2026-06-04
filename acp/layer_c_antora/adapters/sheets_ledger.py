"""Google Sheets ledger adapter.

PHASE 1 STATUS: STUB. The interface is defined and validated against the
LedgerAdapter contract, but the concrete Google Sheets API calls are not yet
wired. This is intentional: connecting to live Sheets requires the same
OAuth setup we will perform when building Agent 1 (Email Watcher), so we
defer the live integration to that pass.

What this stub does today:
    - Implements the LedgerAdapter interface
    - Raises NotImplementedError on every method
    - Documents the column mapping from NegotiationRow to ACP_Tracker columns

What this stub will do after the Phase 1 OAuth pass:
    - Use the gspread library (or Google API Python Client) to read/write
    - Map each NegotiationRow field to the corresponding ACP_Tracker column
    - Honor the Schema Reference and Reference Data sheets for validation
    - Tenant scoping: one spreadsheet ID per tenant, configured in deploy/

This adapter is layer_c_antora because the Sheets-specific implementation is
the concrete production binding. Agent code in layer_b uses only the abstract
LedgerAdapter interface.
"""

from __future__ import annotations

from typing import Optional

from acp.layer_b.core.adapters.ledger_adapter import LedgerAdapter
from acp.layer_b.core.types import NegotiationRow


# Column mapping: NegotiationRow field name -> ACP_Tracker column letter.
#
# The COLUMN_MAP binds generic Layer B field names to letter positions in the
# spreadsheet. The display header text in row 3 of the Negotiations sheet is a
# Layer C choice and can be customized per deployment. For example, Antora's
# Vincent deployment displays the "owner" column as "Owner (SCM)" because his
# role is Supply Chain Manager; a different company might display it as
# "Owner (Contract Manager)" or "Deal Lead". The COLUMN_MAP is unaffected.
#
# Source of truth for the letter positions: ACP_Tracker_v2.xlsx, Negotiations sheet.
COLUMN_MAP = {
    "row_number": "A",
    "category": "B",
    "priority": "C",
    "counterparty_description": "D",
    "whos_court": "E",
    "status": "F",
    "comments": "G",
    "action_next_steps": "H",
    "contract_type": "I",
    "owner": "J",
    "round_number": "K",
    "last_outbound_version_sent": "L",
    "last_counterparty_version": "M",
    "last_activity_date": "N",
    # "days_since_last_activity" is column O — formula-derived, not adapter-managed
    "inbox_thread_id": "P",
    "storage_folder_path": "Q",
    "review_package_status": "R",
    "counterparty_profile_ref": "S",
    "last_review_package_sent_date": "T",
    "automation_status": "U",
    "audit_log_ref": "V",
}

DATA_START_ROW = 5  # rows 1-4 are title, subtitle, header, sub-header


class SheetsLedger(LedgerAdapter):
    """Google Sheets-backed ledger. ONE spreadsheet per tenant.

    Configuration:
        tenant_spreadsheet_ids: dict mapping tenant_id -> Google Sheet spreadsheet ID
        credentials_path: path to OAuth2 credentials JSON
    """

    def __init__(
        self,
        tenant_spreadsheet_ids: dict[str, str],
        credentials_path: Optional[str] = None,
    ):
        self._tenant_spreadsheets = tenant_spreadsheet_ids
        self._credentials_path = credentials_path
        # In the live implementation, instantiate gspread / Google API client here

    def get_row(self, tenant_id: str, negotiation_id: str) -> Optional[NegotiationRow]:
        raise NotImplementedError(
            "SheetsLedger.get_row not yet wired. "
            "Use SQLiteLedger for development. Live wiring deferred to Phase 1 OAuth pass."
        )

    def list_rows(self, tenant_id: str) -> list[NegotiationRow]:
        raise NotImplementedError(
            "SheetsLedger.list_rows not yet wired. "
            "Use SQLiteLedger for development. Live wiring deferred to Phase 1 OAuth pass."
        )

    def upsert_row(self, tenant_id: str, row: NegotiationRow) -> None:
        raise NotImplementedError(
            "SheetsLedger.upsert_row not yet wired. "
            "Use SQLiteLedger for development. Live wiring deferred to Phase 1 OAuth pass."
        )

    def get_owner(self, negotiation_id: str) -> Optional[str]:
        raise NotImplementedError(
            "SheetsLedger.get_owner not yet wired. "
            "Use SQLiteLedger for development. Live wiring deferred to Phase 1 OAuth pass."
        )

    def list_all_owners(self) -> dict[str, str]:
        raise NotImplementedError(
            "SheetsLedger.list_all_owners not yet wired. "
            "Use SQLiteLedger for development. Live wiring deferred to Phase 1 OAuth pass."
        )
