"""Agent 2: Document Extraction.

Per Architecture Spec v2.4 Section 5.2:
"Pull contract document attachments from the inbox, persist them to the
tenant-scoped storage folder at canonical paths, compute integrity
fingerprints, and extract document metadata. Strict tenant isolation:
documents are persisted only to the owning tenant's storage scope."

Triggered by EVENT_DOCUMENT_EXTRACTION_REQUIRED from Agent 3.
Deterministic — no LLM.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

from acp.layer_b.core.adapters.audit_adapter import AuditEvent, AuditLogAdapter
from acp.layer_b.core.adapters.inbox_adapter import InboxAdapter
from acp.layer_b.core.adapters.storage_adapter import StorageAdapter
from acp.layer_b.core.types import (
    EVENT_DOCUMENT_EXTRACTED,
    EVENT_DOCUMENT_EXTRACTION_REQUIRED,
    StateEvent,
    TenantContext,
)

# Type alias: callable that extracts structured metadata from raw document bytes.
# Returns (clause_count, page_count, word_count). Injected so tests can stub
# without requiring python-docx.
ExtractMetadataFn = Callable[[bytes], tuple[int, int, int]]

# Type alias for downstream event subscribers (State Manager registers here).
EventHandler = Callable[[StateEvent], None]


@dataclass(frozen=True)
class DocumentFingerprint:
    """Integrity and structural metadata for a stored document."""
    sha256_hash: str
    file_size_bytes: int
    clause_count: int   # 0 if metadata extraction not supported or failed
    page_count: int     # 0 if metadata extraction not supported or failed
    word_count: int     # 0 if metadata extraction not supported or failed


def _null_metadata(content: bytes) -> tuple[int, int, int]:
    """Default metadata extractor: returns zeros. Swap out in production."""
    return (0, 0, 0)


class DocumentExtractor:
    """Fetches attachment bytes from an inbox and persists them to storage.

    Stateless across calls. Each process_event() call is self-contained.
    """

    AGENT_NAME = "document_extractor"

    def __init__(
        self,
        inbox: InboxAdapter,
        storage: StorageAdapter,
        audit: AuditLogAdapter,
        config: dict,
        extract_metadata: ExtractMetadataFn = _null_metadata,
    ):
        """
        Args:
            inbox: Provider-neutral inbox adapter (re-uses Agent 1's OAuth grants
                in production). Used to fetch raw attachment bytes.
            storage: Provider-neutral storage adapter. Files are persisted here
                at the canonical path this agent constructs.
            audit: Append-only audit log.
            config: Agent configuration dict. Recognised keys:
                - storage_root (str): tenant-scoped root for this deployment.
                  Must be set. In production, maps to the tenant's Drive folder.
            extract_metadata: Optional callable for structured metadata extraction
                (clause count, page count, word count). Defaults to zeros.
                Swap in a python-docx-backed implementation in production.
        """
        self._inbox = inbox
        self._storage = storage
        self._audit = audit
        self._storage_root: str = config["storage_root"]
        self._extract_metadata = extract_metadata
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
        """Process a document_extraction_required event.

        Fetches all attachments listed in the event payload, persists each to
        storage at a canonical path, computes a fingerprint, and emits
        EVENT_DOCUMENT_EXTRACTED for each successfully stored file.

        Non-extraction events are ignored. Attachment fetch failures are
        audited and skipped; other attachments in the same event still proceed.
        """
        if event.event_type != EVENT_DOCUMENT_EXTRACTION_REQUIRED:
            return

        attachment_ids: list[str] = event.payload.get("attachment_ids", [])
        message_id: str = event.payload.get("inbox_message_id", "")
        round_number: int = event.payload.get("round_number", 0)
        contract_type: str = event.payload.get("contract_type") or "unknown"
        counterparty_ref: str = event.payload.get("counterparty_ref") or "unknown"

        if not attachment_ids:
            self._audit_write(
                context, event.negotiation_id,
                "extraction_skipped_no_attachments",
                {"inbox_message_id": message_id},
                severity="warning",
            )
            return

        stored_count = 0
        for attachment_id in attachment_ids:
            success = self._process_attachment(
                context=context,
                negotiation_id=event.negotiation_id,
                tenant_id=event.tenant_id,
                message_id=message_id,
                attachment_id=attachment_id,
                round_number=round_number,
                contract_type=contract_type,
                counterparty_ref=counterparty_ref,
            )
            if success:
                stored_count += 1

        self._audit_write(
            context, event.negotiation_id,
            "extraction_completed",
            {
                "inbox_message_id": message_id,
                "attachments_requested": len(attachment_ids),
                "attachments_stored": stored_count,
            },
        )

    # ============================================================
    # Internal
    # ============================================================

    def _process_attachment(
        self,
        context: TenantContext,
        negotiation_id: str,
        tenant_id: str,
        message_id: str,
        attachment_id: str,
        round_number: int,
        contract_type: str,
        counterparty_ref: str,
    ) -> bool:
        """Fetch, store, fingerprint, and emit for one attachment. Returns True on success."""
        # Step 1: Fetch raw bytes from inbox
        try:
            content = self._inbox.get_attachment(message_id, attachment_id)
        except Exception as exc:
            self._audit_write(
                context, negotiation_id,
                "attachment_fetch_failed",
                {"message_id": message_id, "attachment_id": attachment_id, "error": str(exc)},
                severity="error",
            )
            return False

        # Step 2: Build canonical storage path
        path = self._build_path(
            contract_type=contract_type,
            counterparty_ref=counterparty_ref,
            round_number=round_number,
            attachment_id=attachment_id,
        )

        # Step 3: Collision guard — paths must be unique
        if self._storage.exists(path):
            self._audit_write(
                context, negotiation_id,
                "storage_path_collision",
                {"path": path, "attachment_id": attachment_id},
                severity="error",
            )
            return False

        # Step 4: Persist to storage
        try:
            stored = self._storage.store(path, content)
        except Exception as exc:
            self._audit_write(
                context, negotiation_id,
                "storage_write_failed",
                {"path": path, "attachment_id": attachment_id, "error": str(exc)},
                severity="error",
            )
            return False

        # Step 5: Compute fingerprint
        fingerprint = self._fingerprint(content)

        # Step 6: Emit extracted event
        storage_folder = "/".join(path.split("/")[:-1])
        self._emit(
            context,
            StateEvent(
                event_type=EVENT_DOCUMENT_EXTRACTED,
                tenant_id=tenant_id,
                negotiation_id=negotiation_id,
                workflow_id="contract_redline",
                payload={
                    "storage_path": stored.path,
                    "storage_folder_path": storage_folder,
                    "attachment_id": attachment_id,
                    "inbox_message_id": message_id,
                    "round_number": round_number,
                    "fingerprint": {
                        "sha256_hash": fingerprint.sha256_hash,
                        "file_size_bytes": fingerprint.file_size_bytes,
                        "clause_count": fingerprint.clause_count,
                        "page_count": fingerprint.page_count,
                        "word_count": fingerprint.word_count,
                    },
                },
                emitted_at=datetime.now(timezone.utc),
                emitted_by=self.AGENT_NAME,
            ),
        )

        self._audit_write(
            context, negotiation_id,
            "attachment_stored",
            {
                "storage_path": stored.path,
                "attachment_id": attachment_id,
                "file_size_bytes": fingerprint.file_size_bytes,
                "sha256_hash": fingerprint.sha256_hash,
            },
        )
        return True

    def _build_path(
        self,
        contract_type: str,
        counterparty_ref: str,
        round_number: int,
        attachment_id: str,
    ) -> str:
        """Construct a canonical, unique storage path for one attachment.

        Schema:
            {storage_root}/{contract_type}/{counterparty_ref}/round_{N}/{timestamp}_{attachment_id}.bin

        The timestamp + attachment_id suffix guarantees uniqueness within a round
        even when multiple attachments arrive in the same message.
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        safe_attachment = re.sub(r"[^\w-]", "_", attachment_id)
        filename = f"{timestamp}_{safe_attachment}.bin"
        return "/".join([
            self._storage_root,
            _slugify(contract_type),
            _slugify(counterparty_ref),
            f"round_{round_number}",
            filename,
        ])

    def _fingerprint(self, content: bytes) -> DocumentFingerprint:
        """Compute SHA-256 + size; delegate structured counts to injected extractor."""
        sha256 = hashlib.sha256(content).hexdigest()
        try:
            clause_count, page_count, word_count = self._extract_metadata(content)
        except Exception:
            clause_count, page_count, word_count = 0, 0, 0
        return DocumentFingerprint(
            sha256_hash=sha256,
            file_size_bytes=len(content),
            clause_count=clause_count,
            page_count=page_count,
            word_count=word_count,
        )

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


def _slugify(text: str) -> str:
    """Convert text to a path-safe lowercase slug. Generic — no deployment-specific logic."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text[:64] or "unknown"
