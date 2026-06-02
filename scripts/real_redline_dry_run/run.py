"""ACP Phase 1 real-redline dry-run harness.

Wires all 9 Layer B agents together using in-memory adapters and processes
a synthetic redlined MEPA through the full pipeline. All artifacts are
written to a timestamped output directory under outputs/.

Usage:
    python3 run.py [--patterns PATTERN ...] [--out-dir outputs/<timestamp>]
                   [--llm {stub,real}] [--compare-with-stub]

    # Run with all modification patterns (default, stub LLMs)
    python3 run.py

    # Run with real Anthropic SDK calls on delivery/payment patterns
    python3 run.py --llm real --patterns delivery_ddp delivery_risk_of_loss \
        delivery_inspection payment_delay --compare-with-stub

    # Run specific patterns
    python3 run.py --patterns payment_delay indemnity_deletion

    # Specify custom output directory
    python3 run.py --out-dir /tmp/acp-dry-run

--llm real requires ANTHROPIC_API_KEY in the environment. Model is controlled
by ACP_LLM_MODEL (default: claude-sonnet-4-6). On auth error or unknown model
the harness prints a STOP message and exits 1.

--compare-with-stub (only with --llm real): runs the stub pipeline first to
outputs/<out-dir>/_stub_baseline/, then runs the real-LLM pipeline, then writes
a side-by-side comparison.md to the output directory.

Exit codes:
    0 — all expected artifacts were produced
    1 — one or more artifacts missing or pipeline error

Outputs produced (all in <out-dir>/):
    counterparty_redline.md      — synthetic counterparty-redlined MEPA
    structural_diff.json         — clause-level diff output
    redline_analysis.json        — per-clause LLM analysis
    counter_proposals.json       — per-clause counter-proposal drafts
    lrs_v1.md                    — Legal Review Summary document
    lrs_v1_metadata.json         — LRS metadata sidecar
    audit_log.json               — all audit events from all agents
    run_manifest.json            — run metadata (patterns, timestamps, llm_mode)
    gate_feedback_log.json       — Gate 1/2 ReviewFeedbackCapture summary
    comparison.md                — stub vs real side-by-side (--compare-with-stub only)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
import yaml
from datetime import datetime, timezone
from pathlib import Path

# Ensure project root is on path
_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from acp.layer_b.agents.counter_proposal import CounterProposalAgent
from acp.layer_b.agents.lrs_generator import LRSGeneratorAgent, LRSInput, LRSOutput
from acp.layer_b.agents.portfolio_aggregator import PortfolioAggregatorAgent
from acp.layer_b.agents.redline_analysis import (
    ClauseRecommendation,
    LrsConfidenceTier,
    RedlineAnalyzer,
    resolve_confidence_tier,
)
from acp.layer_b.agents.review_feedback_capture import ReviewFeedbackCapture
from acp.layer_b.agents.state_manager import StateManager
from acp.layer_b.agents.structural_diff import Clause, StructuralDiff
from acp.layer_b.agents.workflow_orchestrator import WorkflowOrchestratorAgent
from acp.layer_b.agents.contract_redline_source import ContractRedlineWorkItemSource
from acp.layer_b.core.adapters.in_memory_audit import InMemoryAuditLog
from acp.layer_b.core.adapters.sqlite_ledger import SQLiteLedger
from acp.layer_b.core.tenancy import TenancyEnforcer
from acp.layer_b.core.types import (
    EVENT_ROUND_READY_FOR_ANALYSIS,
    NegotiationRow,
    NegotiationState,
    StateEvent,
    TenantContext,
)
from acp.layer_b.loaders.pilot_entry_loader import PilotEntryLoader
from acp.layer_b.loaders.playbook_loader import PlaybookLoader
from acp.layer_b.resolver import OverlayResolver
from acp.schemas.playbook_schemas import (
    AcceptanceResponse,
    AntoraResponse,
    CompromiseResponse,
    PlaybookEntry,
    RejectionResponse,
    ReviewerReaction,
)
from acp.layer_b.tests.fixtures.synthetic_config import SYNTHETIC_CONFIG

_pilot_loader = PilotEntryLoader()
_LAYER_C_ROOT = _REPO_ROOT / "acp" / "layer_c_antora"
_playbook_loader = PlaybookLoader(_LAYER_C_ROOT)
_resolver = OverlayResolver()


def _build_clause_ref_map() -> dict[str, PlaybookEntry]:
    """Build a clause_ref → PlaybookEntry map from PlaybookLoader.

    Strips the leading '§' from section_id to produce a bare clause reference
    (e.g. '§2.3' → '2.3').  Only entries with a non-empty section_id are indexed.
    """
    result: dict[str, PlaybookEntry] = {}
    for entry in _playbook_loader.load_all().values():
        raw_section = entry.defend_baseline.template_ref.section_id
        clause_ref = raw_section.lstrip("§").strip()
        if clause_ref:
            result[clause_ref] = entry
    return result


_CLAUSE_REF_MAP: dict[str, PlaybookEntry] = _build_clause_ref_map()


def _load_pilot_antora_response(md_path: Path) -> AntoraResponse | None:
    """Extract and parse the antora_response block from a pilot entry markdown file.

    Reads the first ```yaml code block in the file (which is the PlaybookEntry YAML),
    parses it, and constructs an AntoraResponse from the antora_response sub-block.
    Returns None if the file is missing or contains no antora_response.
    """
    if not md_path.exists():
        return None
    content = md_path.read_text()
    m = re.search(r'```yaml\n(.*?)```', content, re.DOTALL)
    if not m:
        return None
    entry_data = yaml.safe_load(m.group(1))
    ar = (entry_data or {}).get("antora_response")
    if not ar:
        return None
    rr = ar.get("rejection_response") or {}
    cr = ar.get("compromise_response") or {}
    acc = ar.get("acceptance_response") or {}
    return AntoraResponse(
        rejection_response=RejectionResponse(
            rationale=rr.get("rationale", ""),
            counter_proposal=rr.get("counter_proposal", ""),
        ),
        compromise_response=CompromiseResponse(
            conditions=cr.get("conditions", ""),
            revised_language=cr.get("revised_language", ""),
        ),
        acceptance_response=AcceptanceResponse(
            rationale=acc.get("rationale", ""),
        ),
    )


_PILOT_DIR = _REPO_ROOT / "docs" / "architecture" / "pilot_entries"
_PILOT_ANTORA_RESPONSES: dict[str, AntoraResponse | None] = {
    "5.1": _load_pilot_antora_response(_PILOT_DIR / "mepa_warranty_warranty_period.md"),
    "8.3": _load_pilot_antora_response(_PILOT_DIR / "mepa_lol_direct_damages.md"),
}


# Import harness-local modules
_HARNESS_DIR = Path(__file__).parent
sys.path.insert(0, str(_HARNESS_DIR))
from mock_redline_generator import generate_redline, _ALL_PATTERNS

# ---------------------------------------------------------------------------
# Harness-internal storage adapter
# ---------------------------------------------------------------------------

class _HarnessStorageAdapter:
    """File-backed storage adapter for the dry-run harness.

    All paths are stored under the configured root directory.
    """

    def __init__(self, root: Path) -> None:
        self._root = root

    def store(self, path: str, data: bytes) -> None:
        full = self._root / path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_bytes(data)

    def retrieve(self, path: str) -> bytes:
        full = self._root / path
        return full.read_bytes()

    def exists(self, path: str) -> bool:
        return (self._root / path).exists()


# ---------------------------------------------------------------------------
# Stub LLM functions — Layer B style (no SDK in harness)
# ---------------------------------------------------------------------------

def _stub_parse_document(content: bytes) -> list[Clause]:
    """Parse a Markdown document into clauses by scanning for ### N.N headings."""
    clauses: list[Clause] = []
    current_ref: str | None = None
    current_lines: list[str] = []

    for line in content.decode(errors="replace").splitlines():
        stripped = line.strip()
        # Match ### N.N or ### N headings
        if stripped.startswith("### "):
            if current_ref is not None and current_lines:
                clauses.append(Clause(reference=current_ref, text=" ".join(current_lines).strip()))
            header_text = stripped[4:].strip()
            # Extract reference (first token if it looks like N.N)
            parts = header_text.split(None, 1)
            if parts and _is_clause_ref(parts[0]):
                current_ref = parts[0].rstrip(".")
            else:
                current_ref = None
            current_lines = []
        elif current_ref is not None and stripped and not stripped.startswith("#"):
            # Skip markdown markup lines for redline markers
            if not stripped.startswith(">") and not stripped.startswith("~~"):
                current_lines.append(stripped)

    if current_ref is not None and current_lines:
        clauses.append(Clause(reference=current_ref, text=" ".join(current_lines).strip()))

    return clauses


def _is_clause_ref(token: str) -> bool:
    """Return True if token looks like a clause reference (1, 1.1, 2.9, etc.)."""
    cleaned = token.rstrip(".")
    parts = cleaned.split(".")
    return all(p.isdigit() for p in parts) and len(parts) <= 3


def _stub_analyze_clause(
    clause_reference: str,
    change_type: str,
    original_text: str,
    counterparty_text: str,
    playbook_context: str,
    round_number: int = 0,
) -> ClauseRecommendation:
    """Deterministic stub analyzer for dry-run purposes.

    Decision rules (no LLM):
    1. PlaybookLoader lookup — checks real Layer C entries indexed by section_id
       (e.g. '2.3' → mepa.delivery.ddp_terms).  OverlayResolver applied as
       baseline passthrough (no overlays authored yet).
    2. PilotEntryLoader fallback — legacy in-memory pilot entries for clauses
       not yet committed as YAML playbook files.
    3. Agent-reasoned — no playbook entry; escalate with playbook_grounded=False.

    Change-type rules:
    - deleted → reject, is_signature_blocker=True for §6.x or signature_blocker entries
    - added   → escalate, requires_legal_review=True
    - modified + signature_blocker → reject with is_signature_blocker=True
    - modified (other) → negotiate
    """
    # --- 1. PlaybookLoader (real Layer C YAML entries) ---
    playbook_entry = _CLAUSE_REF_MAP.get(clause_reference)
    if playbook_entry is not None:
        resolved = _resolver.resolve(playbook_entry, [])
        resolved_entry = resolved.resolved_entry
        playbook_grounded = True
        evidence_source = f"{resolved_entry.id} | {resolved_entry.evidence_tier}"
        is_signature_blocker = resolved_entry.negotiability == "signature_blocker"
        playbook_ref = resolved_entry.id
        antora_resp: AntoraResponse | None = resolved_entry.antora_response
    else:
        # --- 2. PilotEntryLoader fallback ---
        pilot_ref = _pilot_loader.lookup(clause_reference)
        playbook_grounded = pilot_ref is not None
        evidence_source = (
            f"{pilot_ref.entry_id} | {pilot_ref.evidence_tier} | {pilot_ref.description}"
            if pilot_ref is not None else None
        )
        is_signature_blocker = (
            clause_reference.startswith("6.")
            or (pilot_ref is not None and pilot_ref.negotiability == "signature_blocker")
        )
        playbook_ref = pilot_ref.entry_id if pilot_ref is not None else None
        antora_resp = (
            _PILOT_ANTORA_RESPONSES.get(clause_reference) if pilot_ref is not None else None
        )

    if change_type == "deleted":
        return ClauseRecommendation(
            clause_reference=clause_reference,
            recommendation="reject",
            reasoning=f"Clause {clause_reference} deleted by counterparty. Stub: restore required.",
            playbook_reference=playbook_ref,
            confidence="high",
            requires_legal_review=is_signature_blocker,
            is_signature_blocker=is_signature_blocker,
            playbook_grounded=playbook_grounded,
            evidence_source=evidence_source,
            antora_response=antora_resp,
        )
    if change_type == "added":
        return ClauseRecommendation(
            clause_reference=clause_reference,
            recommendation="escalate",
            reasoning=f"Clause {clause_reference} added by counterparty. Stub: legal review required.",
            playbook_reference=playbook_ref,
            confidence="medium",
            requires_legal_review=True,
            is_signature_blocker=False,
            playbook_grounded=playbook_grounded,
            evidence_source=evidence_source,
            antora_response=antora_resp,
        )
    # modified — signature blockers reject; all others negotiate
    if is_signature_blocker:
        return ClauseRecommendation(
            clause_reference=clause_reference,
            recommendation="reject",
            reasoning=(
                f"Clause {clause_reference} is a signature blocker per playbook. "
                "Stub: reject required."
            ),
            playbook_reference=playbook_ref,
            confidence="high",
            requires_legal_review=True,
            is_signature_blocker=True,
            playbook_grounded=playbook_grounded,
            evidence_source=evidence_source,
            antora_response=antora_resp,
        )
    return ClauseRecommendation(
        clause_reference=clause_reference,
        recommendation="negotiate",
        reasoning=f"Clause {clause_reference} modified. Stub: propose compromise.",
        playbook_reference=playbook_ref,
        confidence="medium",
        requires_legal_review=False,
        is_signature_blocker=False,
        playbook_grounded=playbook_grounded,
        evidence_source=evidence_source,
        antora_response=antora_resp,
    )


def _stub_draft_counter_proposal(
    clause_reference: str,
    recommendation: str,
    reasoning_from_analysis: str,
    original_text: str,
    counterparty_text: str,
    playbook_context: str,
    restore_strategy: str = "redraft",
) -> "CounterProposalDraft":  # noqa: F821
    from acp.layer_b.agents.counter_proposal import CounterProposalDraft
    if restore_strategy == "verbatim" and original_text:
        counter = original_text
        tone = "firm"
        reasoning = f"Restoring original clause {clause_reference} verbatim per restore_strategy=verbatim."
    else:
        counter = "[AGENT-REASONED — no playbook entry. Legal review required before use.]"
        tone = "collaborative"
        reasoning = f"Stub: {reasoning_from_analysis}"
    return CounterProposalDraft(
        clause_reference=clause_reference,
        based_on_recommendation=recommendation,
        original_text=original_text,
        counterparty_text=counterparty_text,
        counter_text=counter,
        reasoning=reasoning,
        tone=tone,
        playbook_reference=None,
        requires_legal_review=False,
    )


def _stub_render_lrs(lrs_input: LRSInput) -> LRSOutput:
    """Stub LRS renderer — produces a Markdown summary document."""
    lines = [
        "# Legal Review Summary",
        "",
        f"**Negotiation ID:** {lrs_input.negotiation_id}",
        f"**Contract Type:** {lrs_input.contract_type}",
        f"**Counterparty:** {lrs_input.counterparty_name}",
        f"**Round Number:** {lrs_input.round_number}",
    ]
    if lrs_input.counterparty_profile_ref:
        lines.append(f"**Counterparty Profile:** {lrs_input.counterparty_profile_ref}")
    if lrs_input.signature_blockers:
        lines.append(f"**Signature Blockers:** {', '.join(lrs_input.signature_blockers)}")
    if lrs_input.risk_summary:
        lines += ["", f"**Risk Summary:** {lrs_input.risk_summary}"]
    if lrs_input.operator_position:
        lines += ["", f"**Operator Position:** {lrs_input.operator_position}"]
    lines += ["", "---", "", "## Diff Summary"]

    entries = lrs_input.diff.get("entries", [])
    for e in entries:
        ct = e.get("change_type", "?")
        mt = e.get("modification_type", ct)
        if ct != "unchanged":
            lines.append(f"- **{e['clause_reference']}** [{ct} / {mt}]")

    lines += ["", "## Analysis Summary"]
    recs = lrs_input.analysis.get("recommendations", [])
    for r in recs:
        # Reconstruct a minimal ClauseRecommendation for confidence tier resolution.
        # The dict is the asdict() serialisation produced by RedlineAnalyzer, so all
        # fields are present.
        _rec = ClauseRecommendation(
            clause_reference=r["clause_reference"],
            recommendation=r["recommendation"],
            reasoning=r.get("reasoning", ""),
            playbook_reference=r.get("playbook_reference"),
            confidence=r.get("confidence", "low"),
            requires_legal_review=r.get("requires_legal_review", False),
            is_signature_blocker=r.get("is_signature_blocker", False),
            playbook_grounded=r.get("playbook_grounded", False),
            evidence_source=r.get("evidence_source"),
        )
        tier = resolve_confidence_tier(_rec)
        if tier == LrsConfidenceTier.PLAYBOOK_VERIFIED:
            lines.append(f"✓ Playbook — Verified")
            lines.append(f"(source: {_rec.evidence_source})")
        elif tier == LrsConfidenceTier.PLAYBOOK_PROVISIONAL:
            lines.append(f"⚠ Playbook — Provisional")
            lines.append(f"(source: {_rec.evidence_source})")
        else:  # AGENT_REASONED
            lines.append("✗ No playbook entry — Agent-reasoned")
            lines.append("Draft below requires legal review before use.")
        blocker = " ⚠ SIGNATURE BLOCKER" if r.get("is_signature_blocker") else ""
        lines.append(f"- **{r['clause_reference']}**: {r['recommendation']}{blocker}")

    lines += ["", "## Counter-Proposal Drafts"]
    drafts = lrs_input.counter_proposals.get("drafts", [])
    for d in drafts:
        lines.append(f"- **{d['clause_reference']}** ({d['based_on_recommendation']}): {d['counter_text'][:80]}...")

    lines += ["", "---", "_Generated by ACP dry-run harness (stub renderer)_"]
    return LRSOutput(
        document_bytes="\n".join(lines).encode(),
        document_format="md",
        metadata={"renderer": "stub", "clause_count": len(entries)},
    )


# ---------------------------------------------------------------------------
# Pipeline wiring
# ---------------------------------------------------------------------------

def run_pipeline(
    patterns: list[str],
    out_dir: Path,
    tenant_id: str = "alice",
    negotiation_id: str | None = None,
    *,
    analyze_fn=None,
    draft_fn=None,
    render_fn=None,
    llm_mode: str = "stub",
) -> dict:
    """Run the full 9-agent pipeline on a synthetic redlined MEPA.

    Args:
        patterns: Modification patterns to apply to the base MEPA.
        out_dir: Directory to write all output artifacts.
        tenant_id: Tenant identifier for the negotiation row.
        negotiation_id: Optional; generated if not supplied.
        analyze_fn: Injectable analyze_clause callable. Defaults to _stub_analyze_clause.
        draft_fn: Injectable draft_counter_proposal callable. Defaults to _stub_draft_counter_proposal.
        render_fn: Injectable render_lrs callable. Defaults to _stub_render_lrs.
        llm_mode: Label written to the manifest ("stub" or "real").

    Returns a manifest dict with run metadata.
    """
    if analyze_fn is None:
        analyze_fn = _stub_analyze_clause
    if draft_fn is None:
        draft_fn = _stub_draft_counter_proposal
    if render_fn is None:
        render_fn = _stub_render_lrs
    negotiation_id = negotiation_id or f"neg-dryrun-{uuid.uuid4().hex[:8]}"
    run_id = uuid.uuid4().hex[:12]
    started_at = datetime.now(timezone.utc)

    out_dir.mkdir(parents=True, exist_ok=True)
    storage_root = out_dir

    print(f"[ACP dry-run] run_id={run_id}  negotiation_id={negotiation_id}")
    print(f"[ACP dry-run] patterns: {patterns}")
    print(f"[ACP dry-run] output: {out_dir}")

    # -----------------------------------------------------------------------
    # Step 1: Generate synthetic redline
    # -----------------------------------------------------------------------
    print("[1/7] Generating synthetic counterparty redline...")
    redline_md = generate_redline(patterns=patterns)
    redline_path = out_dir / "counterparty_redline.md"
    redline_path.write_text(redline_md)
    print(f"      Written: {redline_path.name}")

    # -----------------------------------------------------------------------
    # Step 2: Build infrastructure
    # -----------------------------------------------------------------------
    print("[2/7] Wiring agents...")
    audit = InMemoryAuditLog()
    ledger = SQLiteLedger(db_path=":memory:")
    tenancy = TenancyEnforcer(audit)
    storage = _HarnessStorageAdapter(storage_root)
    ctx = TenantContext(tenant_id=tenant_id)

    # Storage paths
    storage_folder = f"negotiations/{negotiation_id}/round_1"
    cp_doc_path = f"{storage_folder}/counterparty_redline.md"
    outbound_path = f"{storage_folder}/outbound_mepa.md"

    # Store documents into harness storage
    storage.store(cp_doc_path, redline_md.encode())
    storage.store(outbound_path, (_HARNESS_DIR / "inputs" / "sample_mepa_base.md").read_bytes())

    # -----------------------------------------------------------------------
    # Step 3: Seed negotiation row in State Manager
    # -----------------------------------------------------------------------
    sm = StateManager(ledger=ledger, tenancy=tenancy, audit=audit)
    row = NegotiationRow(
        negotiation_id=negotiation_id,
        row_number=1,
        owner=tenant_id,
        workflow_id="contract_redline",
        counterparty_description="Beta Manufacturing - synthetic dry-run counterparty",
        contract_type="master-energy-purchase-agreement",
        status=NegotiationState.NEGOTIATING,
        last_activity_date=started_at,
        round_number=1,
        priority="High",
        automation_status="Active",
    )
    sm.create_negotiation(ctx, row)

    # -----------------------------------------------------------------------
    # Step 4: Wire agents — StructuralDiff → SM → RedlineAnalyzer → SM → CounterProposal → SM → LRS
    # -----------------------------------------------------------------------
    diff_agent = StructuralDiff(
        storage=storage,
        audit=audit,
        config={},
        parse_document=_stub_parse_document,
    )
    analysis_agent = RedlineAnalyzer(
        storage=storage,
        audit=audit,
        config={},
        analyze_clause=analyze_fn,
    )
    counter_agent = CounterProposalAgent(
        storage=storage,
        audit=audit,
        config={},
        draft_counter_proposal=draft_fn,
    )
    source = ContractRedlineWorkItemSource(ledger)
    portfolio = PortfolioAggregatorAgent(sources=[source], audit=audit)
    orch = WorkflowOrchestratorAgent(
        config=SYNTHETIC_CONFIG, ledger=ledger, audit=audit, portfolio=portfolio
    )
    lrs_agent = LRSGeneratorAgent(
        storage=storage,
        audit=audit,
        config={},
        render_lrs=render_fn,
    )

    # Collected emitted events
    pipeline_events: list[StateEvent] = []

    def _record(event: StateEvent) -> None:
        pipeline_events.append(event)

    # Re-emit pattern: each agent's output → SM → SM re-emits to subscribers.
    # SM subscribers receive every re-emitted event; each agent handles only its own type.
    #   diff_agent     → (EVENT_DIFF_COMPLETE) → SM
    #   SM             → (DIFF_COMPLETE re-emitted) → analysis_agent
    #   analysis_agent → (EVENT_ANALYSIS_COMPLETE) → SM
    #   SM             → (ANALYSIS_COMPLETE re-emitted) → counter_agent
    #   counter_agent  → (EVENT_COUNTER_PROPOSALS_READY) → SM
    #   SM             → (COUNTER_PROPOSALS_READY enriched) → lrs_agent
    diff_agent.subscribe(lambda e: sm.process_event(ctx, e))
    analysis_agent.subscribe(lambda e: sm.process_event(ctx, e))
    counter_agent.subscribe(lambda e: sm.process_event(ctx, e))
    sm.subscribe(lambda e: analysis_agent.process_event(ctx, e))
    sm.subscribe(lambda e: counter_agent.process_event(ctx, e))
    sm.subscribe(lambda e: lrs_agent.process_event(ctx, e))
    sm.subscribe(_record)
    lrs_agent.subscribe(_record)

    # -----------------------------------------------------------------------
    # Step 5: Fire EVENT_ROUND_READY_FOR_ANALYSIS
    # -----------------------------------------------------------------------
    print("[3/7] Running structural diff...")
    trigger = StateEvent(
        event_type=EVENT_ROUND_READY_FOR_ANALYSIS,
        tenant_id=tenant_id,
        negotiation_id=negotiation_id,
        workflow_id="contract_redline",
        payload={
            "counterparty_document_path": cp_doc_path,
            "outbound_document_path": outbound_path,
            "storage_folder_path": storage_folder,
            "round_number": 1,
        },
        emitted_at=started_at,
        emitted_by="harness",
    )
    diff_agent.process_event(ctx, trigger)

    # -----------------------------------------------------------------------
    # Step 6: Copy artifacts from harness storage to out_dir at top level
    # -----------------------------------------------------------------------
    print("[4/7] Collecting artifacts...")
    artifacts = {
        "structural_diff.json": f"{storage_folder}/structural_diff.json",
        "redline_analysis.json": f"{storage_folder}/redline_analysis.json",
        "counter_proposals.json": f"{storage_folder}/counter_proposals.json",
    }
    for dest_name, src_path in artifacts.items():
        if storage.exists(src_path):
            (out_dir / dest_name).write_bytes(storage.retrieve(src_path))
            print(f"      Written: {dest_name}")
        else:
            print(f"      MISSING: {dest_name} — pipeline may not have reached this stage")

    # LRS files — scan for lrs_v*.* in storage root
    lrs_folder = storage_root / storage_folder.replace("/", "/")
    if lrs_folder.exists():
        for f in lrs_folder.iterdir():
            if f.name.startswith("lrs_v"):
                (out_dir / f.name).write_bytes(f.read_bytes())
                print(f"      Written: {f.name}")

    # -----------------------------------------------------------------------
    # Step 7: Write audit log and manifest
    # -----------------------------------------------------------------------
    print("[5/7] Writing audit log...")
    all_audit_events = audit.query()
    audit_log = [
        {
            "event_id": e.event_id,
            "agent_name": e.agent_name,
            "event_type": e.event_type,
            "tenant_id": e.tenant_id,
            "negotiation_id": e.negotiation_id,
            "severity": e.severity,
            "timestamp": e.timestamp.isoformat(),
            "payload": e.payload,
        }
        for e in all_audit_events
    ]
    (out_dir / "audit_log.json").write_text(json.dumps(audit_log, indent=2))
    print(f"      Written: audit_log.json ({len(audit_log)} events)")

    finished_at = datetime.now(timezone.utc)
    manifest = {
        "run_id": run_id,
        "negotiation_id": negotiation_id,
        "tenant_id": tenant_id,
        "patterns": patterns,
        "llm_mode": llm_mode,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_ms": int((finished_at - started_at).total_seconds() * 1000),
        "pipeline_events_emitted": len(pipeline_events),
        "audit_events_total": len(audit_log),
    }
    (out_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"      Written: run_manifest.json")

    # -----------------------------------------------------------------------
    # Step 5.5: Simulate Gate 1 and Gate 2 feedback capture
    # -----------------------------------------------------------------------
    print("[5.5/7] Simulating Gate 1 / Gate 2 feedback capture...")
    rfc = ReviewFeedbackCapture(audit_log=audit)

    analysis_data = json.loads((out_dir / "redline_analysis.json").read_bytes())
    recs = analysis_data.get("recommendations", [])

    gate_log: dict = {
        "total_reviews": 0,
        "by_reaction": {"accepted": 0, "edited": 0, "rejected": 0},
        "by_role": {"owner": 0, "legal": 0},
        "edited_clause_references": [],
    }

    for rec_dict in recs:
        clause_ref = rec_dict["clause_reference"]
        recommendation = rec_dict.get("recommendation", "")
        playbook_grounded = rec_dict.get("playbook_grounded", False)
        playbook_reference = rec_dict.get("playbook_reference")

        entry = PlaybookEntry(
            id=playbook_reference or clause_ref,
            recommendation_reviews=[],
        )

        # Gate 1 — owner review (all clauses)
        if playbook_grounded:
            entry = rfc.capture_owner_feedback(
                entry=entry,
                clause_reference=clause_ref,
                reviewer_name="dry-run-owner",
                original_recommendation=recommendation,
                reaction=ReviewerReaction.ACCEPTED,
                rationale="Dry-run: owner accepted agent recommendation",
            )
            gate_log["by_reaction"]["accepted"] += 1
        else:
            entry = rfc.capture_owner_feedback(
                entry=entry,
                clause_reference=clause_ref,
                reviewer_name="dry-run-owner",
                original_recommendation=recommendation,
                reaction=ReviewerReaction.EDITED,
                revised_disposition="negotiate",
                rationale=(
                    "Dry-run: owner flagged agent-reasoned item for legal review"
                ),
            )
            gate_log["by_reaction"]["edited"] += 1
            gate_log["edited_clause_references"].append(clause_ref)
        gate_log["by_role"]["owner"] += 1
        gate_log["total_reviews"] += 1

        # Gate 2 — legal review (pilot-matched clauses only)
        if playbook_grounded:
            entry = rfc.capture_legal_feedback(  # noqa: F841  — returned entry not persisted in harness
                entry=entry,
                clause_reference=clause_ref,
                reviewer_name="dry-run-legal",
                agent_drafted_language="Stub counter-proposal language",
                reaction=ReviewerReaction.ACCEPTED,
                rationale=(
                    "Dry-run: legal accepted playbook-grounded counter-language"
                ),
            )
            gate_log["by_reaction"]["accepted"] += 1
            gate_log["by_role"]["legal"] += 1
            gate_log["total_reviews"] += 1

    (out_dir / "gate_feedback_log.json").write_text(json.dumps(gate_log, indent=2))
    print(
        f"      Written: gate_feedback_log.json  "
        f"(owner={gate_log['by_role']['owner']}, "
        f"legal={gate_log['by_role']['legal']}, "
        f"total={gate_log['total_reviews']})"
    )

    # -----------------------------------------------------------------------
    # Summary: playbook grounding breakdown
    # -----------------------------------------------------------------------
    print(f"\n[ACP dry-run] Analysis summary — {len(recs)} clause(s) changed:")
    playbook_count = sum(1 for r in recs if r.get("playbook_grounded", False))
    reasoned_count = len(recs) - playbook_count
    for r in recs:
        grounded = "✓ playbook" if r.get("playbook_grounded", False) else "✗ agent-reasoned"
        blocker = " [SIGNATURE BLOCKER]" if r.get("is_signature_blocker") else ""
        print(f"    {r['clause_reference']:6s}  {r['recommendation']:10s}  {grounded}{blocker}")
    print(
        f"  Playbook-matched: {playbook_count} / {len(recs)}"
        f"   Agent-reasoned: {reasoned_count} / {len(recs)}"
    )

    return manifest


# ---------------------------------------------------------------------------
# Smoke test: verify expected artifacts exist
# ---------------------------------------------------------------------------

_EXPECTED_ARTIFACTS = [
    "counterparty_redline.md",
    "structural_diff.json",
    "redline_analysis.json",
    "counter_proposals.json",
    "audit_log.json",
    "run_manifest.json",
    "gate_feedback_log.json",
]


def smoke_test(out_dir: Path, llm_mode: str = "stub") -> bool:
    """Check that all expected artifacts exist. Returns True if all present.

    For llm_mode="real", also verifies the LRS document was not truncated by
    reading stop_reason from lrs_v1_metadata.json.
    """
    print("\n[6/7] Smoke test — checking expected artifacts...")
    all_ok = True
    for name in _EXPECTED_ARTIFACTS:
        path = out_dir / name
        if path.exists() and path.stat().st_size > 0:
            print(f"  ✓  {name}")
        else:
            print(f"  ✗  {name}  — MISSING or EMPTY")
            all_ok = False

    # LRS document (lrs_v1.md or lrs_v1.txt depending on renderer)
    lrs_files = list(out_dir.glob("lrs_v*"))
    if lrs_files:
        for f in lrs_files:
            print(f"  ✓  {f.name}")
    else:
        print("  ✗  lrs_v1.md  — MISSING (LRS document not produced)")
        all_ok = False

    # Real-LLM completeness check: fail loudly if LRS was cut off at token limit
    if llm_mode == "real":
        meta_path = out_dir / "lrs_v1_metadata.json"
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text())
                if meta.get("truncated") or meta.get("stop_reason") == "max_tokens":
                    print(
                        "  ✗  lrs_v1_metadata.json — LRS TRUNCATED (stop_reason=max_tokens) "
                        "— raise _MAX_TOKENS_LRS in llm_anthropic.py"
                    )
                    all_ok = False
                else:
                    stop = meta.get("stop_reason", "?")
                    print(f"  ✓  lrs_v1_metadata.json — LRS complete (stop_reason={stop})")
            except (json.JSONDecodeError, OSError) as exc:
                print(f"  ✗  lrs_v1_metadata.json — could not read: {exc}")
                all_ok = False
        else:
            print("  ✗  lrs_v1_metadata.json — MISSING (cannot verify LRS completeness)")
            all_ok = False

    return all_ok


# ---------------------------------------------------------------------------
# Comparison: stub vs real side-by-side
# ---------------------------------------------------------------------------

def _write_comparison(stub_dir: Path, real_dir: Path, out_path: Path) -> None:
    """Read analysis + counter_proposals + LRS from both dirs; write comparison.md."""
    import os

    def _read_json(d: Path, name: str) -> dict:
        p = d / name
        return json.loads(p.read_text()) if p.exists() else {}

    stub_analysis = _read_json(stub_dir, "redline_analysis.json")
    real_analysis = _read_json(real_dir, "redline_analysis.json")
    stub_props = _read_json(stub_dir, "counter_proposals.json")
    real_props = _read_json(real_dir, "counter_proposals.json")

    stub_lrs_files = sorted(stub_dir.glob("lrs_v*.md"))
    real_lrs_files = sorted(real_dir.glob("lrs_v*.md"))
    stub_lrs = stub_lrs_files[0].read_text() if stub_lrs_files else "(not found)"
    real_lrs = real_lrs_files[0].read_text() if real_lrs_files else "(not found)"

    stub_recs = {r["clause_reference"]: r for r in stub_analysis.get("recommendations", [])}
    real_recs = {r["clause_reference"]: r for r in real_analysis.get("recommendations", [])}
    stub_drafts = {d["clause_reference"]: d for d in stub_props.get("drafts", [])}
    real_drafts = {d["clause_reference"]: d for d in real_props.get("drafts", [])}

    all_refs = sorted(set(list(stub_recs) + list(real_recs)))

    model = os.environ.get("ACP_LLM_MODEL", "claude-sonnet-4-6")
    lines = [
        "# Stub vs Real-LLM Comparison",
        "",
        f"Real LLM model: `{model}`",
        "",
        "---",
        "",
        "## Per-Clause Analysis",
        "",
        "> Counter-proposal text for playbook-matched clauses comes from the",
        "> `antora_response` block — identical for stub and real.",
        "> The meaningful difference is in LLM **reasoning** and the **LRS document**.",
        "",
    ]

    for ref in all_refs:
        sr = stub_recs.get(ref, {})
        rr = real_recs.get(ref, {})
        blocker = " ⚠ SIGNATURE BLOCKER" if (sr or rr).get("is_signature_blocker") else ""
        grounded = "✓ playbook" if (sr or rr).get("playbook_grounded") else "✗ agent-reasoned"

        lines += [
            f"### Clause {ref}{blocker}  [{grounded}]",
            "",
            "| | Stub | Real LLM |",
            "|---|---|---|",
            (
                f"| **Recommendation** | {sr.get('recommendation', '—')} "
                f"| {rr.get('recommendation', '—')} |"
            ),
            (
                f"| **Confidence** | {sr.get('confidence', '—')} "
                f"| {rr.get('confidence', '—')} |"
            ),
        ]
        lines.append("")
        lines.append("**Stub reasoning:**")
        lines.append(f"> {sr.get('reasoning', '—')}")
        lines.append("")
        lines.append("**Real LLM reasoning:**")
        lines.append(f"> {rr.get('reasoning', '—')}")

        sd = stub_drafts.get(ref, {})
        rd = real_drafts.get(ref, {})
        if sd or rd:
            lines += [
                "",
                "**Counter-proposal (stub):**",
                f"```\n{sd.get('counter_text', '—')}\n```",
                "",
                "**Counter-proposal (real LLM):**",
                f"```\n{rd.get('counter_text', '—')}\n```",
            ]
        lines += ["", "---", ""]

    lines += [
        "## LRS Document — Stub",
        "",
        "```markdown",
        stub_lrs,
        "```",
        "",
        "---",
        "",
        "## LRS Document — Real LLM",
        "",
        real_lrs,
    ]

    out_path.write_text("\n".join(lines))
    print(f"      Written: {out_path.name}")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="ACP dry-run harness: process a synthetic redlined MEPA through all 9 agents."
    )
    parser.add_argument(
        "--patterns",
        nargs="+",
        choices=_ALL_PATTERNS,
        default=_ALL_PATTERNS,
        help="Modification patterns to apply to the base MEPA (default: all).",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Output directory. Defaults to outputs/<ISO-timestamp>.",
    )
    parser.add_argument(
        "--llm",
        choices=["stub", "real"],
        default="stub",
        help="LLM backend: 'stub' (deterministic, default) or 'real' (Anthropic SDK).",
    )
    parser.add_argument(
        "--compare-with-stub",
        action="store_true",
        help=(
            "With --llm real: also run the stub pipeline and write comparison.md. "
            "Ignored when --llm stub."
        ),
    )
    args = parser.parse_args()

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = args.out_dir or (_HARNESS_DIR / "outputs" / ts)

    # --- Build LLM adapters --------------------------------------------------
    analyze_fn = None
    draft_fn = None
    render_fn = None

    if args.llm == "real":
        try:
            from acp.layer_b.adapters.llm_anthropic import (
                make_real_analyze_clause,
                make_real_draft_counter_proposal,
                make_real_render_lrs,
            )
            import os
            model = os.environ.get("ACP_LLM_MODEL", "claude-sonnet-4-6")
            print(f"[ACP dry-run] LLM mode: REAL (model={model})")
            analyze_fn = make_real_analyze_clause(
                _CLAUSE_REF_MAP, _resolver, _pilot_loader, _PILOT_ANTORA_RESPONSES
            )
            draft_fn = make_real_draft_counter_proposal()
            render_fn = make_real_render_lrs()
        except RuntimeError as exc:
            print(f"\nSTOP: real-LLM adapter failed to initialise: {exc}")
            print("Check ANTHROPIC_API_KEY and ACP_LLM_MODEL.")
            return 1
    else:
        print("[ACP dry-run] LLM mode: stub (deterministic)")

    # --- Stub baseline for comparison ----------------------------------------
    stub_dir: Path | None = None
    if args.llm == "real" and args.compare_with_stub:
        stub_dir = out_dir / "_stub_baseline"
        print(f"\n[ACP dry-run] Running stub baseline first → {stub_dir}")
        run_pipeline(patterns=args.patterns, out_dir=stub_dir, llm_mode="stub")

    # --- Main run ------------------------------------------------------------
    manifest = run_pipeline(
        patterns=args.patterns,
        out_dir=out_dir,
        analyze_fn=analyze_fn,
        draft_fn=draft_fn,
        render_fn=render_fn,
        llm_mode=args.llm,
    )

    ok = smoke_test(out_dir, llm_mode=args.llm)

    print(f"\n[7/7] Done. Duration: {manifest['duration_ms']}ms")
    print(f"      Output directory: {out_dir}")

    # --- Comparison ----------------------------------------------------------
    if stub_dir is not None:
        print("\n[ACP dry-run] Generating stub vs real comparison...")
        _write_comparison(stub_dir, out_dir, out_dir / "comparison.md")

    if ok:
        print("\nSMOKE TEST PASSED — all expected artifacts present.")
        return 0
    else:
        print("\nSMOKE TEST FAILED — one or more expected artifacts missing.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
