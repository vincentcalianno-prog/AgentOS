"""Playbook entry loader for the ACP negotiation engine.

Loads PlaybookEntry objects from YAML files under <layer_c_root>/playbook/.
The deployment root (layer_c_root) is a constructor argument — this loader
contains no deployment-specific paths or identifiers.

Supersedes PilotEntryLoader for entries committed as YAML in a deployment's
Layer C. PilotEntryLoader remains available for the dry-run harness.

Discovery: scans <layer_c_root>/playbook/**/*.yaml recursively and indexes
all found entries by PlaybookEntry.id.

Thread-safe after construction (scan is eager and the index is immutable
after the first load).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

from acp.schemas.playbook_schemas import (
    AcceptModification,
    AcceptanceResponse,
    AntoraResponse,
    CompromiseResponse,
    DefendBaseline,
    PlaybookEntry,
    RejectThreshold,
    RejectionResponse,
    TemplateRef,
)


class PlaybookLoadError(Exception):
    """Raised when a playbook YAML file cannot be parsed into a PlaybookEntry."""


# ---------------------------------------------------------------------------
# Negotiability vocabulary — enforced at load time
# ---------------------------------------------------------------------------

# Closed set of valid negotiability values.
# Canonical vocabulary: docs/architecture/ontology.md §6 (Negotiability Tiers).
# Empty string is permitted for entries not yet assigned a tier (draft state).
# Any non-empty value outside this set raises PlaybookLoadError at load time.
_VALID_NEGOTIABILITY: frozenset[str] = frozenset({
    "signature_blocker",  # firm walk-away; any modification is a deal-breaker
    "parametric",         # structure fixed, values flex within defined constraints
    "negotiable",         # open to substantive changes within playbook guardrails
    "boilerplate",        # standard language; accept counterparty style edits
})


# ---------------------------------------------------------------------------
# YAML → dataclass helpers
# ---------------------------------------------------------------------------

def _str(val: object) -> str:
    """Coerce a YAML scalar to a stripped string, treating None as empty."""
    if val is None:
        return ""
    return str(val).strip()


def _parse_template_ref(data: dict) -> TemplateRef:
    return TemplateRef(
        document_id=_str(data.get("document_id")),
        section_id=_str(data.get("section_id")),
        version=_str(data.get("version")),
    )


def _parse_defend_baseline(data: dict) -> DefendBaseline:
    return DefendBaseline(
        template_ref=_parse_template_ref(data.get("template_ref") or {}),
        guidance=_str(data.get("guidance")),
    )


def _parse_accept_modification(data: dict) -> AcceptModification:
    return AcceptModification(
        id=_str(data.get("id")),
        description=_str(data.get("description")),
        example_language=_str(data.get("example_language")),
        rationale=_str(data.get("rationale")),
    )


def _parse_reject_threshold(data: dict) -> RejectThreshold:
    return RejectThreshold(
        id=_str(data.get("id")),
        description=_str(data.get("description")),
        example_language=_str(data.get("example_language")),
        rationale=_str(data.get("rationale")),
    )


def _parse_antora_response(data: dict) -> AntoraResponse:
    rr = data.get("rejection_response") or {}
    cr = data.get("compromise_response") or {}
    ar = data.get("acceptance_response") or {}
    return AntoraResponse(
        rejection_response=RejectionResponse(
            rationale=_str(rr.get("rationale")),
            counter_proposal=_str(rr.get("counter_proposal")),
        ),
        compromise_response=CompromiseResponse(
            conditions=_str(cr.get("conditions")),
            revised_language=_str(cr.get("revised_language")),
        ),
        acceptance_response=AcceptanceResponse(
            rationale=_str(ar.get("rationale")),
        ),
    )


def _parse_entry(data: dict, source_path: Path) -> PlaybookEntry:
    """Parse a raw YAML mapping into a PlaybookEntry.

    Raises PlaybookLoadError when:
    - The required 'id' field is absent or empty.
    - The 'negotiability' field is set to an unrecognised value (empty is allowed).
    """
    entry_id = _str(data.get("id"))
    if not entry_id:
        raise PlaybookLoadError(
            f"PlaybookEntry missing required 'id' field: {source_path}"
        )

    negotiability = _str(data.get("negotiability"))
    if negotiability and negotiability not in _VALID_NEGOTIABILITY:
        raise PlaybookLoadError(
            f"PlaybookEntry '{entry_id}' has unrecognised negotiability "
            f"'{negotiability}' in {source_path}. "
            f"Valid values: {sorted(_VALID_NEGOTIABILITY)}"
        )

    raw_constraints = data.get("constraints")
    constraints: dict = raw_constraints if isinstance(raw_constraints, dict) else {}

    antora_raw = data.get("antora_response")
    antora_response = (
        _parse_antora_response(antora_raw)
        if isinstance(antora_raw, dict)
        else AntoraResponse()
    )

    return PlaybookEntry(
        id=entry_id,
        contract_type_id=_str(data.get("contract_type_id")),
        category_id=_str(data.get("category_id")),
        sub_clause_id=_str(data.get("sub_clause_id")),
        defend_baseline=_parse_defend_baseline(data.get("defend_baseline") or {}),
        accept_modifications=[
            _parse_accept_modification(m)
            for m in (data.get("accept_modifications") or [])
        ],
        reject_thresholds=[
            _parse_reject_threshold(t)
            for t in (data.get("reject_thresholds") or [])
        ],
        negotiability=negotiability,
        constraints=constraints,
        pending_items=list(data.get("pending_items") or []),
        examples=list(data.get("examples") or []),
        related_entries=list(data.get("related_entries") or []),
        metadata=data.get("metadata") or {},
        review_status=_str(data.get("review_status")),
        last_reviewed_by=data.get("last_reviewed_by"),
        last_reviewed_date=data.get("last_reviewed_date"),
        evidence_tier=_str(data.get("evidence_tier")),
        antora_response=antora_response,
    )


# ---------------------------------------------------------------------------
# Public loader
# ---------------------------------------------------------------------------

class PlaybookLoader:
    """Load PlaybookEntry objects from a deployment's playbook directory.

    Scans <layer_c_root>/playbook/**/*.yaml and indexes entries by
    PlaybookEntry.id.  An absent playbook directory yields an empty loader
    rather than raising — callers decide whether that is an error.

    Usage::

        loader = PlaybookLoader(layer_c_root)
        entry = loader.get("some.category.sub_clause")
        all_entries = loader.load_all()
    """

    def __init__(self, layer_c_root: str | Path) -> None:
        self._playbook_dir = Path(layer_c_root) / "playbook"
        self._index: dict[str, PlaybookEntry] = {}
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        if not self._playbook_dir.is_dir():
            self._loaded = True
            return
        for yaml_path in sorted(self._playbook_dir.rglob("*.yaml")):
            try:
                raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
            except yaml.YAMLError as exc:
                raise PlaybookLoadError(
                    f"Failed to parse YAML at {yaml_path}: {exc}"
                ) from exc
            if not isinstance(raw, dict):
                raise PlaybookLoadError(
                    f"Expected a YAML mapping at {yaml_path},"
                    f" got {type(raw).__name__}"
                )
            entry = _parse_entry(raw, yaml_path)
            if entry.id in self._index:
                raise PlaybookLoadError(
                    f"Duplicate entry id '{entry.id}': already seen before"
                    f" {yaml_path}"
                )
            self._index[entry.id] = entry
        self._loaded = True

    # --- Public API ---

    def load_all(self) -> dict[str, PlaybookEntry]:
        """Return all loaded PlaybookEntry objects keyed by id."""
        self._ensure_loaded()
        return dict(self._index)

    def get(self, entry_id: str) -> Optional[PlaybookEntry]:
        """Return a PlaybookEntry by id, or None if not found."""
        self._ensure_loaded()
        return self._index.get(entry_id)

    def get_by_sub_clause(
        self, category_id: str, sub_clause_id: str
    ) -> Optional[PlaybookEntry]:
        """Return the first entry matching both category_id and sub_clause_id."""
        self._ensure_loaded()
        for entry in self._index.values():
            if (
                entry.category_id == category_id
                and entry.sub_clause_id == sub_clause_id
            ):
                return entry
        return None

    def entry_ids(self) -> list[str]:
        """Return all known entry ids in load order (alphabetical by file path)."""
        self._ensure_loaded()
        return list(self._index.keys())
