"""Pilot PlaybookEntry loader for the ACP dry-run harness and Phase 2a validation.

Maps clause references to the two pilot PlaybookEntries authored during
Phase 2 schema validation. The explicit CLAUSE_TO_PILOT lookup table is the
stable surface: it does not read YAML or disk, so it works in test and
harness contexts without a Layer C deployment.

Phase 2a will replace this with a full playbook_loader that reads YAML
files from acp/layer_c_antora/. PilotEntryLoader is the bridge used by
the dry-run harness and Phase 2 validation tests until then.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# Explicit mapping: clause reference → pilot name.
# "5.1" and "8.3" are non-conflicting references chosen specifically because
# they do not overlap with existing mock_redline_generator patterns (2.9, 3.2,
# 4.4, 6.1, 7.2). Content mismatch with the base contract template is intentional —
# these patterns exercise playbook lookup and confidence tier rendering.
CLAUSE_TO_PILOT: dict[str, str] = {
    "5.1": "warranty_period",
    "8.3": "lol_direct_damages",
}


@dataclass(frozen=True)
class PilotEntryRef:
    """Lightweight reference to a pilot PlaybookEntry.

    Carries only the fields needed to populate ClauseRecommendation.
    The full PlaybookEntry YAML lives in docs/architecture/pilot_entries/.
    """
    entry_id: str
    # The PlaybookEntry.id from the pilot YAML
    evidence_tier: str
    # "provisional" | "verified" — matches PlaybookEntry.evidence_tier
    negotiability: str
    # "signature_blocker" | "parametric" | "flexible"
    description: str
    # Brief description used in evidence_source string generation


_PILOT_ENTRIES: dict[str, PilotEntryRef] = {
    "warranty_period": PilotEntryRef(
        entry_id="mepa.warranty.warranty_period",
        evidence_tier="provisional",
        negotiability="parametric",
        description="Antora warranty period baseline (§6.1(vi))",
    ),
    "lol_direct_damages": PilotEntryRef(
        entry_id="mepa.limitation_of_liability.direct_damages_clarification",
        evidence_tier="provisional",
        negotiability="signature_blocker",
        description="JST §8.3 three-category direct damages clarification",
    ),
}


class PilotEntryLoader:
    """Looks up pilot PlaybookEntry references by clause reference.

    Returns a PilotEntryRef for known clause references, None for unknown.
    Thread-safe (read-only internal state).
    """

    def lookup(self, clause_reference: str) -> Optional[PilotEntryRef]:
        """Return the PilotEntryRef for a clause reference, or None if not found."""
        pilot_name = CLAUSE_TO_PILOT.get(clause_reference)
        if pilot_name is None:
            return None
        return _PILOT_ENTRIES.get(pilot_name)

    def has_entry(self, clause_reference: str) -> bool:
        """Return True if a pilot entry exists for this clause reference."""
        return clause_reference in CLAUSE_TO_PILOT

    def evidence_source_string(self, clause_reference: str) -> Optional[str]:
        """Build the evidence_source string for a ClauseRecommendation, or None.

        Format: "<entry_id> | <evidence_tier> | <description>"
        Returns None for unknown clause references.
        """
        ref = self.lookup(clause_reference)
        if ref is None:
            return None
        return f"{ref.entry_id} | {ref.evidence_tier} | {ref.description}"
