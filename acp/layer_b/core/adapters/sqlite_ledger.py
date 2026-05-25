"""SQLite-backed ledger adapter for local development and testing.

This adapter lives in layer_b because it operates only on synthetic data and
is used by the test suite. It contains no deployment-specific values.

Tables:
    negotiations(tenant_id, negotiation_id, ...all NegotiationRow fields)

PRIMARY KEY is (tenant_id, negotiation_id). Cross-tenant uniqueness of
negotiation_id is also enforced at the application layer through get_owner().
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from typing import Optional

from acp.layer_b.core.adapters.ledger_adapter import LedgerAdapter
from acp.layer_b.core.types import NegotiationRow, NegotiationState


_SCHEMA = """
CREATE TABLE IF NOT EXISTS negotiations (
    tenant_id TEXT NOT NULL,
    negotiation_id TEXT NOT NULL,
    row_number INTEGER NOT NULL,
    owner TEXT NOT NULL,
    category TEXT,
    priority TEXT,
    counterparty_description TEXT,
    whos_court TEXT,
    status TEXT NOT NULL,
    comments TEXT,
    action_next_steps TEXT,
    contract_type TEXT,
    round_number INTEGER NOT NULL DEFAULT 0,
    last_outbound_version_sent TEXT,
    last_counterparty_version TEXT,
    last_activity_date TEXT,
    inbox_thread_id TEXT,
    storage_folder_path TEXT,
    review_package_status TEXT,
    counterparty_profile_ref TEXT,
    last_review_package_sent_date TEXT,
    automation_status TEXT NOT NULL DEFAULT 'Manual Only',
    audit_log_ref TEXT,
    PRIMARY KEY (tenant_id, negotiation_id)
);

CREATE INDEX IF NOT EXISTS idx_negotiations_by_id ON negotiations(negotiation_id);
CREATE INDEX IF NOT EXISTS idx_negotiations_by_tenant ON negotiations(tenant_id);
"""


def _row_to_db_tuple(row: NegotiationRow, tenant_id: str) -> tuple:
    """Convert a NegotiationRow to a database tuple."""
    return (
        tenant_id,
        row.negotiation_id,
        row.row_number,
        row.owner,
        row.category,
        row.priority,
        row.counterparty_description,
        row.whos_court,
        row.status.value,
        row.comments,
        row.action_next_steps,
        row.contract_type,
        row.round_number,
        row.last_outbound_version_sent,
        row.last_counterparty_version,
        row.last_activity_date.isoformat() if row.last_activity_date else None,
        row.inbox_thread_id,
        row.storage_folder_path,
        row.review_package_status,
        row.counterparty_profile_ref,
        row.last_review_package_sent_date.isoformat() if row.last_review_package_sent_date else None,
        row.automation_status,
        row.audit_log_ref,
    )


def _db_tuple_to_row(t: tuple) -> NegotiationRow:
    """Convert a database tuple to a NegotiationRow."""
    (
        _tenant_id, negotiation_id, row_number, owner,
        category, priority, counterparty_description, whos_court, status_str,
        comments, action_next_steps, contract_type, round_number,
        last_outbound_version_sent, last_counterparty_version,
        last_activity_date_str, inbox_thread_id, storage_folder_path,
        review_package_status, counterparty_profile_ref, last_review_package_sent_date_str,
        automation_status, audit_log_ref,
    ) = t

    return NegotiationRow(
        negotiation_id=negotiation_id,
        row_number=row_number,
        owner=owner,
        category=category,
        priority=priority,
        counterparty_description=counterparty_description,
        whos_court=whos_court,
        status=NegotiationState(status_str),
        comments=comments,
        action_next_steps=action_next_steps,
        contract_type=contract_type,
        round_number=round_number,
        last_outbound_version_sent=last_outbound_version_sent,
        last_counterparty_version=last_counterparty_version,
        last_activity_date=datetime.fromisoformat(last_activity_date_str) if last_activity_date_str else None,
        inbox_thread_id=inbox_thread_id,
        storage_folder_path=storage_folder_path,
        review_package_status=review_package_status,
        counterparty_profile_ref=counterparty_profile_ref,
        last_review_package_sent_date=datetime.fromisoformat(last_review_package_sent_date_str) if last_review_package_sent_date_str else None,
        automation_status=automation_status,
        audit_log_ref=audit_log_ref,
    )


_FIELD_ORDER = (
    "tenant_id, negotiation_id, row_number, owner, category, priority, "
    "counterparty_description, whos_court, status, comments, action_next_steps, "
    "contract_type, round_number, last_outbound_version_sent, last_counterparty_version, "
    "last_activity_date, inbox_thread_id, storage_folder_path, review_package_status, "
    "counterparty_profile_ref, last_review_package_sent_date, automation_status, audit_log_ref"
)
_NUM_FIELDS = len(_FIELD_ORDER.split(", "))


class SQLiteLedger(LedgerAdapter):
    """SQLite-backed ledger. Uses :memory: by default; can be file-backed for persistence."""

    def __init__(self, db_path: str = ":memory:"):
        self._db_path = db_path
        # SQLite connections aren't thread-safe by default; use a lock
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def get_row(self, tenant_id: str, negotiation_id: str) -> Optional[NegotiationRow]:
        with self._lock:
            cur = self._conn.execute(
                f"SELECT {_FIELD_ORDER} FROM negotiations WHERE tenant_id = ? AND negotiation_id = ?",
                (tenant_id, negotiation_id),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return _db_tuple_to_row(row)

    def list_rows(self, tenant_id: str) -> list[NegotiationRow]:
        with self._lock:
            cur = self._conn.execute(
                f"SELECT {_FIELD_ORDER} FROM negotiations WHERE tenant_id = ? ORDER BY row_number",
                (tenant_id,),
            )
            rows = cur.fetchall()
        return [_db_tuple_to_row(r) for r in rows]

    def upsert_row(self, tenant_id: str, row: NegotiationRow) -> None:
        db_tuple = _row_to_db_tuple(row, tenant_id)
        placeholders = ", ".join(["?"] * _NUM_FIELDS)
        with self._lock:
            self._conn.execute(
                f"INSERT OR REPLACE INTO negotiations ({_FIELD_ORDER}) VALUES ({placeholders})",
                db_tuple,
            )
            self._conn.commit()

    def get_owner(self, negotiation_id: str) -> Optional[str]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT tenant_id FROM negotiations WHERE negotiation_id = ?",
                (negotiation_id,),
            )
            result = cur.fetchone()
        return result[0] if result else None

    def list_all_owners(self) -> dict[str, str]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT negotiation_id, tenant_id FROM negotiations"
            )
            return {nid: tid for nid, tid in cur.fetchall()}

    def close(self):
        with self._lock:
            self._conn.close()
