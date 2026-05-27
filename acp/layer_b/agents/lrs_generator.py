"""Agent 7: LRS (Legal Review Summary) Generator.

Per Architecture Spec v2.4 Section 5.7:
"For each negotiation round where counter-proposals have been drafted, generate
a Legal Review Summary document from the structural diff, redline analysis, and
counter-proposals. Persist the document to the negotiation's storage folder and
emit EVENT_LRS_READY."

Triggered by EVENT_COUNTER_PROPOSALS_READY from State Manager.
Deterministic — no LLM. render_lrs is injected so tests use deterministic stubs
and Layer C configures contract-type-specific renderers dispatched by contract_type.

contract_type and counterparty_description are read from the event payload, where
they are enriched by State Manager's _handle_counter_proposals_ready from the
NegotiationRow. Agent 7 does not parse or depend on storage path structure.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, List, Optional

from acp.layer_b.core.adapters.audit_adapter import AuditEvent, AuditLogAdapter
from acp.layer_b.core.adapters.storage_adapter import StorageAdapter
from acp.layer_b.core.types import (
    EVENT_COUNTER_PROPOSALS_READY,
    EVENT_LRS_READY,
    StateEvent,
    TenantContext,
)
from acp.layer_b.agents.counter_proposal import PROPOSALS_FILENAME
from acp.layer_b.agents.redline_analysis import ANALYSIS_FILENAME
from acp.layer_b.agents.structural_diff import DIFF_FILENAME

# Filename templates for the generated LRS document and its sidecar metadata.
# round_number and document_format are substituted at runtime.
LRS_DOCUMENT_FILENAME = "lrs_v{round_number}.{document_format}"
LRS_METADATA_FILENAME = "lrs_v{round_number}_metadata.json"

# Type alias: injectable renderer.
# (LRSInput) → LRSOutput
# In production: contract-type-specific renderer in layer_c_antora,
# dispatched by contract_type. In tests: deterministic stub.
RenderLRSFn = Callable[["LRSInput"], "LRSOutput"]

EventHandler = Callable[[StateEvent], None]


@dataclass(frozen=True)
class LRSInput:
    """All inputs the renderer needs to produce an LRS document.

    The agent orchestrates; the renderer decides format, sections, and styling.
    Missing input JSONs are represented as empty dicts and flagged for legal review.
    """
    negotiation_id: str
    workflow_id: str
    contract_type: str          # derived from storage path convention
    round_number: int
    counterparty_name: str      # derived from storage path convention
    diff: dict                  # structural_diff.json content; {} if missing
    analysis: dict              # redline_analysis.json content; {} if missing
    counter_proposals: dict     # counter_proposals.json content; {} if missing
    prior_round_summary: Optional[str] = None        # narrative summary of prior round, if any
    operator_position: Optional[str] = None          # operator's overall stance for legal reviewer
    signature_blockers: List[str] = field(default_factory=list)  # clause refs that must resolve before signing
    risk_summary: Optional[str] = None               # high-level risk narrative for legal reviewer
    counterparty_profile_ref: Optional[str] = None  # slug/ID for counterparty profile reference


@dataclass(frozen=True)
class LRSOutput:
    """The rendered LRS document and associated metadata."""
    document_bytes: bytes
    document_format: str    # e.g., "md", "pdf", "docx" — determines file extension
    metadata: dict          # renderer-supplied metadata merged into the sidecar JSON


def _null_renderer(lrs_input: LRSInput) -> LRSOutput:
    """Default stub: returns an empty document. Swap in a renderer in Layer C."""
    return LRSOutput(
        document_bytes=b"",
        document_format="txt",
        metadata={},
    )


class LRSGeneratorAgent:
    """Reads structural_diff.json, redline_analysis.json, and counter_proposals.json
    from the negotiation's storage folder, renders an LRS document via the injected
    RenderLRSFn, persists the document and a metadata JSON sidecar, and emits
    EVENT_LRS_READY.

    Stateless across calls. Each process_event() call is self-contained.
    Missing input JSONs are treated as empty dicts (non-fatal, flagged for legal
    review in the emitted event payload and audit log).
    Renderer failures are also non-fatal: an empty document is written and the
    event is still emitted with requires_legal_review=True.
    """

    AGENT_NAME = "lrs_generator"

    def __init__(
        self,
        storage: StorageAdapter,
        audit: AuditLogAdapter,
        config: dict,
        render_lrs: RenderLRSFn = _null_renderer,
    ):
        """
        Args:
            storage: Provider-neutral storage adapter.
            audit: Append-only audit log.
            config: Agent configuration dict. No keys currently recognised;
                reserved for future renderer routing configuration.
            render_lrs: Injectable renderer callable. Defaults to a stub that
                returns an empty document. Swap in a contract-type-specific
                renderer in layer_c_antora.
        """
        self._storage = storage
        self._audit = audit
        self._render_lrs = render_lrs
        self._subscribers: list[EventHandler] = []

    def subscribe(self, handler: EventHandler) -> None:
        self._subscribers.append(handler)

    def process_event(self, context: TenantContext, event: StateEvent) -> None:
        """Process a counter_proposals_ready event.

        Loads the three input JSONs from the storage folder, builds an LRSInput,
        calls the renderer, persists the document and metadata JSON, and emits
        EVENT_LRS_READY. Non-counter-proposals-ready events are silently ignored.
        """
        if event.event_type != EVENT_COUNTER_PROPOSALS_READY:
            return

        proposals_path: Optional[str] = event.payload.get("proposals_path")
        round_number: int = event.payload.get("round_number", 0)

        if not proposals_path:
            self._audit_write(
                context, event.negotiation_id,
                "lrs_skipped_missing_proposals_path",
                {"payload_keys": list(event.payload.keys())},
                severity="warning",
            )
            return

        # Derive storage folder from the proposals path (one level up).
        # contract_type and counterparty_description are enriched into the payload
        # by State Manager's _handle_counter_proposals_ready from the NegotiationRow.
        storage_folder = "/".join(proposals_path.split("/")[:-1])
        contract_type = event.payload.get("contract_type", "unknown")
        counterparty_name = event.payload.get("counterparty_description", "unknown")

        # Step 1: Load each input JSON; missing → empty dict + warning
        requires_legal_review = False

        diff = self._load_json(
            context, event.negotiation_id,
            f"{storage_folder}/{DIFF_FILENAME}",
            "diff_missing",
        )
        if diff is None:
            diff = {}
            requires_legal_review = True

        analysis = self._load_json(
            context, event.negotiation_id,
            f"{storage_folder}/{ANALYSIS_FILENAME}",
            "analysis_missing",
        )
        if analysis is None:
            analysis = {}
            requires_legal_review = True

        counter_proposals_doc = self._load_json(
            context, event.negotiation_id,
            f"{storage_folder}/{PROPOSALS_FILENAME}",
            "counter_proposals_missing",
        )
        if counter_proposals_doc is None:
            counter_proposals_doc = {}
            requires_legal_review = True

        # Step 2: Build LRSInput and call renderer
        lrs_input = LRSInput(
            negotiation_id=event.negotiation_id,
            workflow_id=event.workflow_id,
            contract_type=contract_type,
            round_number=round_number,
            counterparty_name=counterparty_name,
            diff=diff,
            analysis=analysis,
            counter_proposals=counter_proposals_doc,
            prior_round_summary=event.payload.get("prior_round_summary"),
            operator_position=event.payload.get("operator_position"),
            signature_blockers=event.payload.get("signature_blockers", []),
            risk_summary=event.payload.get("risk_summary"),
            counterparty_profile_ref=event.payload.get("counterparty_profile_ref"),
        )

        try:
            lrs_output = self._render_lrs(lrs_input)
        except Exception as exc:
            self._audit_write(
                context, event.negotiation_id,
                "lrs_render_failed",
                {"error": str(exc)},
                severity="error",
            )
            lrs_output = LRSOutput(
                document_bytes=b"",
                document_format="txt",
                metadata={"render_error": str(exc)},
            )
            requires_legal_review = True

        # Step 3: Build paths and persist document + metadata sidecar
        doc_filename = LRS_DOCUMENT_FILENAME.format(
            round_number=round_number,
            document_format=lrs_output.document_format,
        )
        metadata_filename = LRS_METADATA_FILENAME.format(round_number=round_number)
        lrs_path = f"{storage_folder}/{doc_filename}"
        metadata_path = f"{storage_folder}/{metadata_filename}"

        metadata_doc = {
            "negotiation_id": event.negotiation_id,
            "round_number": round_number,
            "document_format": lrs_output.document_format,
            "lrs_path": lrs_path,
            "requires_legal_review": requires_legal_review,
            **lrs_output.metadata,
        }

        try:
            self._storage.store(lrs_path, lrs_output.document_bytes)
            self._storage.store(metadata_path, json.dumps(metadata_doc).encode())
        except Exception as exc:
            self._audit_write(
                context, event.negotiation_id,
                "lrs_write_failed",
                {"lrs_path": lrs_path, "error": str(exc)},
                severity="error",
            )
            return

        # Step 4: Emit EVENT_LRS_READY
        self._emit(
            context,
            StateEvent(
                event_type=EVENT_LRS_READY,
                tenant_id=event.tenant_id,
                negotiation_id=event.negotiation_id,
                workflow_id=event.workflow_id,
                payload={
                    "lrs_path": lrs_path,
                    "metadata_path": metadata_path,
                    "round_number": round_number,
                    "document_format": lrs_output.document_format,
                    "requires_legal_review": requires_legal_review,
                },
                emitted_at=datetime.now(timezone.utc),
                emitted_by=self.AGENT_NAME,
            ),
        )

        self._audit_write(
            context, event.negotiation_id,
            "lrs_generated",
            {
                "lrs_path": lrs_path,
                "metadata_path": metadata_path,
                "round_number": round_number,
                "document_format": lrs_output.document_format,
                "requires_legal_review": requires_legal_review,
            },
        )

    def _load_json(
        self,
        context: TenantContext,
        negotiation_id: str,
        path: str,
        missing_event_type: str,
    ) -> Optional[dict]:
        """Load a JSON file from storage. Returns None and audits a warning if
        the file is missing or cannot be parsed."""
        try:
            raw = self._storage.retrieve(path)
            return json.loads(raw.decode())
        except Exception as exc:
            self._audit_write(
                context, negotiation_id,
                missing_event_type,
                {"path": path, "error": str(exc)},
                severity="warning",
            )
            return None

    def _emit(self, context: TenantContext, event: StateEvent) -> None:
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
