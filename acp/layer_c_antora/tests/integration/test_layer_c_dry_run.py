"""Integration test: Layer C dry-run with real PlaybookLoader.

Exercises the full analysis → counter-proposal → LRS chain against the
4 committed playbook entries from the real layer_c_antora deployment.
All adapters (storage, audit, ledger) are in-memory. LLM callables are
deterministic stubs injected at construction time.

Coverage:
  - Four clause references that map to committed playbook YAML entries →
    playbook_grounded=True, evidence_source populated, correct is_signature_blocker
  - One clause reference with no playbook entry → playbook_grounded=False
  - Unchanged clause excluded from analysis
  - Counter-proposal text is non-empty for all draftable clauses
  - LRS output contains confidence tier markers for both grounded and
    agent-reasoned clauses

No deployment-specific identifiers appear as Python literals.
"""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from acp.layer_b.agents.counter_proposal import (
    PROPOSALS_FILENAME,
    CounterProposalAgent,
    CounterProposalDraft,
)
from acp.layer_b.agents.lrs_generator import (
    LRS_DOCUMENT_FILENAME,
    LRSGeneratorAgent,
    LRSInput,
    LRSOutput,
)
from acp.layer_b.agents.redline_analysis import (
    ANALYSIS_FILENAME,
    ClauseRecommendation,
    RedlineAnalyzer,
)
from acp.layer_b.agents.state_manager import StateManager
from acp.layer_b.agents.structural_diff import DIFF_FILENAME
from acp.layer_b.core.adapters.in_memory_audit import InMemoryAuditLog
from acp.layer_b.core.adapters.sqlite_ledger import SQLiteLedger
from acp.layer_b.core.tenancy import TenancyEnforcer
from acp.layer_b.core.types import (
    EVENT_DIFF_COMPLETE,
    NegotiationRow,
    NegotiationState,
    StateEvent,
    TenantContext,
)
from acp.layer_c_antora.loaders.playbook_loader import PlaybookLoader
from acp.layer_b.resolver import OverlayResolver
from acp.layer_b.tests.fixtures.mock_storage import MockStorageAdapter
from acp.schemas.playbook_schemas import PlaybookEntry

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[4]
_LAYER_C = _REPO_ROOT / "acp" / "layer_c_antora"
_EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)
_STORAGE_FOLDER = "test/neg-layer-c-dryrun-001/round_1"


# ---------------------------------------------------------------------------
# PlaybookLoader-backed clause_ref_map helper
# ---------------------------------------------------------------------------

def _build_clause_ref_map(loader: PlaybookLoader) -> dict[str, PlaybookEntry]:
    """Map bare clause references (e.g. '2.3') to PlaybookEntry objects.

    Strips the leading '§' from defend_baseline.template_ref.section_id.
    Only entries with a non-empty section_id are indexed.
    """
    result: dict[str, PlaybookEntry] = {}
    for entry in loader.load_all().values():
        raw = entry.defend_baseline.template_ref.section_id
        clause_ref = raw.lstrip("§").strip()
        if clause_ref:
            result[clause_ref] = entry
    return result


# ---------------------------------------------------------------------------
# Stub callables (injected into agents)
# ---------------------------------------------------------------------------

def _make_playbook_analyzer(
    clause_ref_map: dict[str, PlaybookEntry],
    resolver: OverlayResolver,
):
    """Return an AnalyzeClauseFn backed by PlaybookLoader + OverlayResolver.

    Matched clauses → playbook_grounded=True.
    Unmatched clauses → playbook_grounded=False, agent-reasoned escalation.
    """
    def _analyze(
        clause_reference: str,
        change_type: str,
        original_text: str,
        counterparty_text: str,
        playbook_context: str,
        round_number: int = 0,
    ) -> ClauseRecommendation:
        entry = clause_ref_map.get(clause_reference)
        if entry is not None:
            resolved = resolver.resolve(entry, [])
            re = resolved.resolved_entry
            non_negotiable = re.negotiability == "signature_blocker"
            return ClauseRecommendation(
                clause_reference=clause_reference,
                recommendation="reject" if non_negotiable else "negotiate",
                reasoning=f"Playbook entry matched: {re.id}",
                playbook_reference=re.id,
                confidence="high",
                requires_legal_review=non_negotiable,
                is_signature_blocker=non_negotiable,
                playbook_grounded=True,
                evidence_source=f"{re.id} | {re.evidence_tier}",
                antora_response=re.antora_response,
            )
        return ClauseRecommendation(
            clause_reference=clause_reference,
            recommendation="escalate",
            reasoning="No playbook entry found for this clause. Agent-reasoned.",
            playbook_reference=None,
            confidence="low",
            requires_legal_review=True,
            is_signature_blocker=False,
            playbook_grounded=False,
            evidence_source=None,
        )
    return _analyze


def _stub_drafter(
    clause_reference: str,
    recommendation: str,
    reasoning_from_analysis: str,
    original_text: str,
    counterparty_text: str,
    playbook_context: str,
    restore_strategy: str = "redraft",
) -> CounterProposalDraft:
    counter = original_text if original_text else "[no original — agent-reasoned response required]"
    return CounterProposalDraft(
        clause_reference=clause_reference,
        based_on_recommendation=recommendation,
        original_text=original_text,
        counterparty_text=counterparty_text,
        counter_text=counter,
        reasoning="integration test stub",
        tone="firm",
        playbook_reference=None,
        requires_legal_review=(recommendation == "escalate"),
    )


def _stub_renderer(lrs_input: LRSInput) -> LRSOutput:
    recs = lrs_input.analysis.get("recommendations", [])
    lines = ["# Legal Review Summary (integration test stub)", ""]
    for r in recs:
        if r.get("playbook_grounded", False):
            lines.append("⚠ Playbook — Provisional")
        else:
            lines.append("✗ No playbook entry — Agent-reasoned")
        lines.append(f"  clause: {r['clause_reference']}  rec: {r['recommendation']}")
    return LRSOutput(
        document_bytes="\n".join(lines).encode(),
        document_format="md",
        metadata={"renderer": "integration-test-stub"},
    )


# ---------------------------------------------------------------------------
# Synthetic diff fixture
# ---------------------------------------------------------------------------

# Four clause references that match the committed playbook YAML entries
# (section_ids §2.3 / §2.4 / §2.5 / §3.2 → bare refs 2.3 / 2.4 / 2.5 / 3.2).
# One clause reference (9.1) has no playbook entry → agent-reasoned path.
# One clause reference (1.1) is unchanged → excluded from analysis.

_SYNTHETIC_DIFF: dict = {
    "negotiation_id": "neg-layer-c-dryrun-001",
    "round_number": 1,
    "entries": [
        {
            "clause_reference": "2.3",
            "change_type": "modified",
            "modification_type": "replacement",
            "original_text": "Delivery at the named destination per agreed Incoterm.",
            "counterparty_text": "Goods available for collection at origin (EXW).",
        },
        {
            "clause_reference": "2.4",
            "change_type": "modified",
            "modification_type": "replacement",
            "original_text": "Risk transfers at delivery to the named destination.",
            "counterparty_text": "Risk transfers upon loading at origin facility.",
        },
        {
            "clause_reference": "2.5",
            "change_type": "modified",
            "modification_type": "replacement",
            "original_text": "Written acceptance required within 10 business days of delivery.",
            "counterparty_text": "Deemed accepted after 5-business-day silence.",
        },
        {
            "clause_reference": "3.2",
            "change_type": "modified",
            "modification_type": "replacement",
            "original_text": "Payment within 30 days of invoice date.",
            "counterparty_text": "Payment within 60 days of invoice date.",
        },
        {
            "clause_reference": "9.1",
            "change_type": "added",
            "modification_type": "addition",
            "original_text": "",
            "counterparty_text": "This Agreement constitutes the entire agreement between the parties.",
        },
        {
            "clause_reference": "1.1",
            "change_type": "unchanged",
            "modification_type": "unchanged",
            "original_text": "Definitions apply throughout.",
            "counterparty_text": "Definitions apply throughout.",
        },
    ],
    "summary": {"total": 6, "modified": 4, "added": 1, "deleted": 0, "unchanged": 1},
}

_PLAYBOOK_REFS = {"2.3", "2.4", "2.5", "3.2"}
_SIGNATURE_BLOCKER_REF = "2.4"  # negotiability == "signature_blocker" in the real YAML


# ---------------------------------------------------------------------------
# Integration test class
# ---------------------------------------------------------------------------

class LayerCDryRunIntegrationTest(unittest.TestCase):
    """End-to-end: PlaybookLoader → OverlayResolver → analysis → counter → LRS.

    Uses real layer_c_antora YAML entries. All adapters are in-memory.
    """

    @classmethod
    def setUpClass(cls):
        cls.loader = PlaybookLoader(_LAYER_C)
        cls.resolver = OverlayResolver()
        cls.clause_ref_map = _build_clause_ref_map(cls.loader)

    def setUp(self):
        self.ledger = SQLiteLedger(db_path=":memory:")
        self.audit = InMemoryAuditLog()
        tenancy = TenancyEnforcer(self.audit)
        self.sm = StateManager(ledger=self.ledger, tenancy=tenancy, audit=self.audit)
        self.storage = MockStorageAdapter()
        self.negotiation_id = "neg-layer-c-dryrun-001"
        self.tenant_id = "alice"
        self.ctx = TenantContext(tenant_id=self.tenant_id)

        # Seed negotiation row
        row = NegotiationRow(
            negotiation_id=self.negotiation_id,
            row_number=1,
            owner=self.tenant_id,
            workflow_id="contract_redline",
            counterparty_description="Beta Manufacturing - integration test fixture",
            contract_type="generic-agreement",
            status=NegotiationState.NEGOTIATING,
            last_activity_date=_EPOCH,
            round_number=1,
        )
        self.sm.create_negotiation(self.ctx, row)

        # Store synthetic diff in mock storage
        diff_path = f"{_STORAGE_FOLDER}/{DIFF_FILENAME}"
        self.storage.store(diff_path, json.dumps(_SYNTHETIC_DIFF).encode())
        self.diff_path = diff_path

        # Construct agents with injected stubs
        analyzer_fn = _make_playbook_analyzer(self.clause_ref_map, self.resolver)
        self.analysis_agent = RedlineAnalyzer(
            storage=self.storage, audit=self.audit, config={},
            analyze_clause=analyzer_fn,
        )
        self.counter_agent = CounterProposalAgent(
            storage=self.storage, audit=self.audit, config={},
            draft_counter_proposal=_stub_drafter,
        )
        self.lrs_agent = LRSGeneratorAgent(
            storage=self.storage, audit=self.audit, config={},
            render_lrs=_stub_renderer,
        )

        # Wire event chain: analysis → SM → counter → SM → lrs
        self.final_events: list[StateEvent] = []
        self.analysis_agent.subscribe(lambda e: self.sm.process_event(self.ctx, e))
        self.counter_agent.subscribe(lambda e: self.sm.process_event(self.ctx, e))
        self.sm.subscribe(lambda e: self.counter_agent.process_event(self.ctx, e))
        self.sm.subscribe(lambda e: self.lrs_agent.process_event(self.ctx, e))
        self.sm.subscribe(self.final_events.append)
        self.lrs_agent.subscribe(self.final_events.append)

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _fire_diff_complete(self) -> None:
        event = StateEvent(
            event_type=EVENT_DIFF_COMPLETE,
            tenant_id=self.tenant_id,
            negotiation_id=self.negotiation_id,
            workflow_id="contract_redline",
            payload={
                "diff_path": self.diff_path,
                "round_number": 1,
                "storage_folder_path": _STORAGE_FOLDER,
            },
            emitted_at=_EPOCH,
            emitted_by="test-harness",
        )
        self.analysis_agent.process_event(self.ctx, event)

    def _read_analysis(self) -> dict:
        path = f"{_STORAGE_FOLDER}/{ANALYSIS_FILENAME}"
        return json.loads(self.storage.retrieve(path).decode())

    def _read_counter_proposals(self) -> dict:
        path = f"{_STORAGE_FOLDER}/{PROPOSALS_FILENAME}"
        return json.loads(self.storage.retrieve(path).decode())

    def _read_lrs(self) -> str:
        path = f"{_STORAGE_FOLDER}/{LRS_DOCUMENT_FILENAME.format(round_number=1, document_format='md')}"
        return self.storage.retrieve(path).decode()

    # -----------------------------------------------------------------------
    # Tests
    # -----------------------------------------------------------------------

    def test_playbook_loader_maps_four_clause_refs(self):
        """PlaybookLoader finds section_ids for all 4 committed entries."""
        for ref in _PLAYBOOK_REFS:
            self.assertIn(ref, self.clause_ref_map, f"clause ref {ref} not in clause_ref_map")

    def test_four_matched_clauses_are_playbook_grounded(self):
        """Clauses 2.3, 2.4, 2.5, 3.2 match real playbook entries → grounded."""
        self._fire_diff_complete()
        recs = {r["clause_reference"]: r for r in self._read_analysis()["recommendations"]}
        for ref in _PLAYBOOK_REFS:
            self.assertIn(ref, recs, f"clause {ref} missing from analysis")
            self.assertTrue(recs[ref]["playbook_grounded"], f"clause {ref} should be playbook_grounded")
            self.assertIsNotNone(
                recs[ref]["evidence_source"],
                f"clause {ref} should have a non-None evidence_source",
            )

    def test_unmatched_clause_is_agent_reasoned(self):
        """Clause 9.1 has no playbook entry → playbook_grounded=False."""
        self._fire_diff_complete()
        recs = {r["clause_reference"]: r for r in self._read_analysis()["recommendations"]}
        self.assertIn("9.1", recs)
        self.assertFalse(recs["9.1"]["playbook_grounded"])
        self.assertIsNone(recs["9.1"]["evidence_source"])

    def test_signature_blocker_clause_sets_is_signature_blocker(self):
        """The signature_blocker negotiability clause is flagged as is_signature_blocker=True."""
        self._fire_diff_complete()
        recs = {r["clause_reference"]: r for r in self._read_analysis()["recommendations"]}
        self.assertTrue(
            recs[_SIGNATURE_BLOCKER_REF]["is_signature_blocker"],
            f"clause {_SIGNATURE_BLOCKER_REF} should be is_signature_blocker=True",
        )

    def test_signature_blocker_clause_gets_reject_recommendation(self):
        """signature_blocker entries receive a 'reject' recommendation."""
        self._fire_diff_complete()
        recs = {r["clause_reference"]: r for r in self._read_analysis()["recommendations"]}
        self.assertEqual(recs[_SIGNATURE_BLOCKER_REF]["recommendation"], "reject")

    def test_unchanged_clause_excluded_from_analysis(self):
        """Unchanged clause 1.1 is not present in the analysis output."""
        self._fire_diff_complete()
        recs = {r["clause_reference"]: r for r in self._read_analysis()["recommendations"]}
        self.assertNotIn("1.1", recs)

    def test_counter_proposals_non_empty_for_matched_clauses(self):
        """Draftable matched clauses produce non-empty counter_text."""
        self._fire_diff_complete()
        drafts = {d["clause_reference"]: d for d in self._read_counter_proposals()["drafts"]}
        # negotiate / reject clauses are drafted; escalate (9.1) is not
        for ref in _PLAYBOOK_REFS:
            self.assertIn(ref, drafts, f"clause {ref} has no counter draft")
            self.assertGreater(
                len(drafts[ref]["counter_text"]), 0,
                f"clause {ref} counter_text is empty",
            )

    def test_lrs_contains_provisional_tier_marker(self):
        """LRS output includes the playbook-provisional confidence marker."""
        self._fire_diff_complete()
        lrs_text = self._read_lrs()
        self.assertIn("Playbook — Provisional", lrs_text)

    def test_lrs_contains_agent_reasoned_marker(self):
        """LRS output includes the agent-reasoned confidence marker for clause 9.1."""
        self._fire_diff_complete()
        lrs_text = self._read_lrs()
        self.assertIn("Agent-reasoned", lrs_text)

    def test_overlay_resolver_baseline_passthrough(self):
        """OverlayResolver with no overlays returns a deep copy of the base entry."""
        for ref, entry in self.clause_ref_map.items():
            result = self.resolver.resolve(entry, [])
            self.assertEqual(result.entry_id, entry.id)
            self.assertIsNotNone(result.resolved_entry)
            self.assertEqual(result.resolved_entry.id, entry.id)
            self.assertGreater(len(result.provenance), 0)
            self.assertIn(f"baseline:{entry.id}", result.provenance[0])


if __name__ == "__main__":
    unittest.main()
