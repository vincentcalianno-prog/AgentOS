"""Agent 4: Structural Diff.

Per Architecture Spec v2.4 Section 5.4:
"Perform a deterministic clause-level diff between the outbound version sent
and the counterparty's redlined version. Persist the structured result to the
negotiation's storage folder and emit EVENT_DIFF_COMPLETE."

Triggered by EVENT_ROUND_READY_FOR_ANALYSIS from State Manager.
Deterministic — no LLM.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

from acp.layer_b.core.adapters.audit_adapter import AuditEvent, AuditLogAdapter
from acp.layer_b.core.adapters.storage_adapter import StorageAdapter
from acp.layer_b.core.types import (
    EVENT_DIFF_COMPLETE,
    EVENT_ROUND_READY_FOR_ANALYSIS,
    StateEvent,
    TenantContext,
)

# Type alias: callable that parses raw document bytes into a list of Clause objects.
# Injected so tests can stub without requiring python-docx.
ParseDocumentFn = Callable[[bytes], list["Clause"]]

# Type alias for downstream event subscribers.
EventHandler = Callable[[StateEvent], None]

DIFF_FILENAME = "structural_diff.json"


@dataclass(frozen=True)
class Clause:
    """A single numbered clause extracted from a contract document."""
    reference: str   # e.g., "1.1", "2", "Schedule A"
    text: str


@dataclass(frozen=True)
class DiffEntry:
    """The diff result for one clause reference."""
    clause_reference: str
    change_type: str          # "unchanged" | "modified" | "added" | "deleted"
    original_text: str        # text from outbound version; empty string if added
    counterparty_text: str    # text from counterparty version; empty string if deleted
    surrounding_context: str  # adjacent clause references for reviewer orientation
    character_delta: int      # len(counterparty_text) - len(original_text)


def _null_parser(content: bytes) -> list[Clause]:
    """Default parser: returns empty clause list. Swap in python-docx in production."""
    return []


class StructuralDiff:
    """Reads two document versions from storage, diffs them clause-by-clause,
    persists the result as JSON, and emits EVENT_DIFF_COMPLETE.

    Stateless across calls. Each process_event() call is self-contained.
    """

    AGENT_NAME = "structural_diff"

    def __init__(
        self,
        storage: StorageAdapter,
        audit: AuditLogAdapter,
        config: dict,
        parse_document: ParseDocumentFn = _null_parser,
    ):
        """
        Args:
            storage: Provider-neutral storage adapter. Both input documents and
                the output diff JSON are read/written here.
            audit: Append-only audit log.
            config: Agent configuration dict. No required keys currently;
                reserved for future clause-numbering config.
            parse_document: Callable that parses raw bytes into a list of Clause
                objects. Defaults to an empty-list stub. Swap in a python-docx-
                backed implementation in production.
        """
        self._storage = storage
        self._audit = audit
        self._parse_document = parse_document
        self._subscribers: list[EventHandler] = []

    # ============================================================
    # Subscription API
    # ============================================================

    def subscribe(self, handler: EventHandler) -> None:
        """Register a downstream handler (e.g., State Manager.process_event)."""
        self._subscribers.append(handler)

    # ============================================================
    # Event Processing API
    # ============================================================

    def process_event(self, context: TenantContext, event: StateEvent) -> None:
        """Process a round_ready_for_analysis event.

        Reads both document versions from storage, computes a clause-level diff,
        persists structural_diff.json to the negotiation's storage folder, and
        emits EVENT_DIFF_COMPLETE.

        Non-analysis events are ignored. If the outbound document path is absent
        (round 1 baseline), the diff treats all counterparty clauses as additions.
        """
        if event.event_type != EVENT_ROUND_READY_FOR_ANALYSIS:
            return

        counterparty_path: Optional[str] = event.payload.get("counterparty_document_path")
        outbound_path: Optional[str] = event.payload.get("outbound_document_path")
        storage_folder: Optional[str] = event.payload.get("storage_folder_path")
        round_number: int = event.payload.get("round_number", 0)

        if not counterparty_path or not storage_folder:
            self._audit_write(
                context, event.negotiation_id,
                "diff_skipped_missing_payload",
                {"payload_keys": list(event.payload.keys())},
                severity="warning",
            )
            return

        # Step 1: Read counterparty document
        try:
            counterparty_bytes = self._storage.retrieve(counterparty_path)
        except Exception as exc:
            self._audit_write(
                context, event.negotiation_id,
                "diff_fetch_failed",
                {"path": counterparty_path, "error": str(exc)},
                severity="error",
            )
            return

        # Step 2: Read outbound document (may be absent for round 1)
        outbound_bytes: bytes = b""
        if outbound_path:
            try:
                outbound_bytes = self._storage.retrieve(outbound_path)
            except Exception as exc:
                self._audit_write(
                    context, event.negotiation_id,
                    "diff_fetch_failed",
                    {"path": outbound_path, "error": str(exc)},
                    severity="warning",
                )
                # Non-fatal: proceed with empty outbound; all counterparty clauses become additions

        # Step 3: Parse both documents into clause lists
        counterparty_clauses = self._safe_parse(counterparty_bytes)
        outbound_clauses = self._safe_parse(outbound_bytes) if outbound_bytes else []

        # Step 4: Compute diff
        entries = _diff_clauses(outbound_clauses, counterparty_clauses)

        # Step 5: Persist diff JSON
        diff_path = f"{storage_folder}/{DIFF_FILENAME}"
        diff_payload = {
            "negotiation_id": event.negotiation_id,
            "round_number": round_number,
            "counterparty_document_path": counterparty_path,
            "outbound_document_path": outbound_path,
            "entries": [asdict(e) for e in entries],
        }
        try:
            self._storage.store(diff_path, json.dumps(diff_payload).encode())
        except Exception as exc:
            self._audit_write(
                context, event.negotiation_id,
                "diff_write_failed",
                {"path": diff_path, "error": str(exc)},
                severity="error",
            )
            return

        # Step 6: Emit EVENT_DIFF_COMPLETE
        self._emit(
            context,
            StateEvent(
                event_type=EVENT_DIFF_COMPLETE,
                tenant_id=event.tenant_id,
                negotiation_id=event.negotiation_id,
                workflow_id="contract_redline",
                payload={
                    "diff_path": diff_path,
                    "round_number": round_number,
                    "total_clauses": len(entries),
                    "changed_clauses": sum(
                        1 for e in entries if e.change_type != "unchanged"
                    ),
                },
                emitted_at=datetime.now(timezone.utc),
                emitted_by=self.AGENT_NAME,
            ),
        )

        self._audit_write(
            context, event.negotiation_id,
            "diff_completed",
            {
                "diff_path": diff_path,
                "round_number": round_number,
                "total_clauses": len(entries),
                "changed_clauses": sum(1 for e in entries if e.change_type != "unchanged"),
            },
        )

    # ============================================================
    # Internal
    # ============================================================

    def _safe_parse(self, content: bytes) -> list[Clause]:
        """Parse document bytes into clauses; return empty list on failure."""
        try:
            return self._parse_document(content)
        except Exception:
            return []

    def _emit(self, context: TenantContext, event: StateEvent) -> None:
        """Dispatch to all subscribers. Subscriber failures are logged, not raised."""
        for handler in self._subscribers:
            try:
                handler(event)
            except Exception as exc:
                self._audit_write(
                    context,
                    negotiation_id=event.negotiation_id,
                    event_type="subscriber_error",
                    payload={
                        "subscriber": getattr(handler, "__qualname__", str(handler)),
                        "error": str(exc),
                        "original_event_type": event.event_type,
                    },
                    severity="error",
                )

    def _audit_write(
        self,
        context: TenantContext,
        negotiation_id: Optional[str],
        event_type: str,
        payload: dict,
        severity: str = "info",
    ) -> None:
        self._audit.record(AuditEvent(
            event_id=str(uuid.uuid4()),
            tenant_id=context.tenant_id,
            negotiation_id=negotiation_id,
            workflow_id="contract_redline",
            agent_name=self.AGENT_NAME,
            event_type=event_type,
            timestamp=datetime.now(timezone.utc),
            payload=payload,
            severity=severity,
        ))


# ============================================================
# Diff algorithm (module-level, pure function)
# ============================================================

def _diff_clauses(
    outbound: list[Clause],
    counterparty: list[Clause],
) -> list[DiffEntry]:
    """Compute a clause-level diff between two ordered clause lists.

    Matching strategy: align by clause reference. Clauses present in both
    are compared textually. Clauses only in outbound are deletions; only in
    counterparty are additions.

    Returns entries in counterparty document order, with deletions inserted
    at the position of the missing reference.
    """
    outbound_map: dict[str, str] = {c.reference: c.text for c in outbound}
    counterparty_map: dict[str, str] = {c.reference: c.text for c in counterparty}
    counterparty_refs = [c.reference for c in counterparty]
    outbound_refs = [c.reference for c in outbound]

    # Build ordered reference list: counterparty order, then deletions appended
    seen: set[str] = set()
    ordered_refs: list[str] = []
    for ref in counterparty_refs:
        ordered_refs.append(ref)
        seen.add(ref)
    for ref in outbound_refs:
        if ref not in seen:
            ordered_refs.append(ref)

    entries: list[DiffEntry] = []
    for i, ref in enumerate(ordered_refs):
        orig = outbound_map.get(ref, "")
        cp = counterparty_map.get(ref, "")

        if ref in outbound_map and ref in counterparty_map:
            change_type = "unchanged" if orig == cp else "modified"
        elif ref in counterparty_map:
            change_type = "added"
        else:
            change_type = "deleted"

        # Surrounding context: adjacent references in ordered list
        prev_ref = ordered_refs[i - 1] if i > 0 else ""
        next_ref = ordered_refs[i + 1] if i < len(ordered_refs) - 1 else ""
        context_str = " | ".join(r for r in [prev_ref, next_ref] if r)

        entries.append(DiffEntry(
            clause_reference=ref,
            change_type=change_type,
            original_text=orig,
            counterparty_text=cp,
            surrounding_context=context_str,
            character_delta=len(cp) - len(orig),
        ))

    return entries
