"""Playbook schema definitions for the ACP contract negotiation engine.

These dataclasses define the structure of PlaybookEntry and related entities.
PlaybookEntry instances are authored in Layer C (acp/layer_c_antora/) and
loaded at runtime. The schema is defined here so all layers share the same
data contract without importing Layer C content.

AntoraResponse and its sub-dataclasses are also imported by Agent 5
(Redline Analysis) to type the three-state response block on
ClauseRecommendation. The canonical definitions live here; redline_analysis.py
imports from this module rather than duplicating them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class AbstractionStatus(Enum):
    PENDING            = "pending"
    # Not yet processed by the learning loop
    EXTRACTED          = "extracted"
    # Abstracted pattern written to shared registry (IP stripped)
    SKIPPED            = "skipped"
    # Not useful for pattern extraction
    FLAGGED_FOR_REVIEW = "flagged_for_review"
    # Needs human review before extraction


class ReviewerReaction(Enum):
    ACCEPTED = "accepted"
    EDITED   = "edited"
    REJECTED = "rejected"


# ---------------------------------------------------------------------------
# AntoraResponse — three-state structured response block
#
# Production analyzers MUST populate all three states for each clause:
#   rejection_response  — rationale + counter restoring baseline position
#   compromise_response — conditions for partial acceptance + revised language
#   acceptance_response — why the counterparty position already protects operator
#
# The canonical definitions live here. Do NOT redefine these in layer_b agents.
# ---------------------------------------------------------------------------

@dataclass
class RejectionResponse:
    rationale: str = ""
    # Risk rationale explaining why the operator cannot accept the change
    counter_proposal: str = ""
    # Counter-proposal language — firm, no hedging on signature blockers


@dataclass
class CompromiseResponse:
    conditions: str = ""
    # Specific conditions under which the operator would accept a deviation
    revised_language: str = ""
    # The exact contract language the operator would accept under those conditions


@dataclass
class AcceptanceResponse:
    rationale: str = ""
    # Why the baseline clause already protects the operator adequately
    # Not optional — silent accepts rejected by schema validation


@dataclass
class AntoraResponse:
    """Three-state structured response block for a clause redline."""
    rejection_response: RejectionResponse = field(default_factory=RejectionResponse)
    compromise_response: CompromiseResponse = field(default_factory=CompromiseResponse)
    acceptance_response: AcceptanceResponse = field(default_factory=AcceptanceResponse)


# ---------------------------------------------------------------------------
# PlaybookEntry supporting structures
# ---------------------------------------------------------------------------

@dataclass
class TemplateRef:
    """Reference to the authoritative template document and section."""
    document_id: str = ""
    section_id: str = ""
    version: str = ""


@dataclass
class DefendBaseline:
    """The baseline position to defend for this clause type."""
    template_ref: TemplateRef = field(default_factory=TemplateRef)
    guidance: str = ""


@dataclass
class AcceptModification:
    """A counterparty modification pattern that is acceptable."""
    id: str = ""
    description: str = ""
    example_language: str = ""
    rationale: str = ""


@dataclass
class RejectThreshold:
    """A counterparty change that must be rejected."""
    id: str = ""
    description: str = ""
    example_language: str = ""
    rationale: str = ""


# ---------------------------------------------------------------------------
# OutcomeRecord
# ---------------------------------------------------------------------------

@dataclass
class OutcomeRecord:
    """Single negotiation outcome — raw IP, never leaves Layer C."""
    date: str = ""
    # ISO date string e.g. "2026-05-30"
    counterparty: str = ""
    # Counterparty name — raw IP, stays in Layer C
    agent_recommendation: str = ""
    # The disposition Agent 5 recommended: accept | counter | reject
    actual_outcome: str = ""
    # What actually happened: accepted | compromised | rejected | escalated
    rounds_to_close: int = 0
    sandelin_override: bool = False
    # True if the owner overrode the agent recommendation
    abstraction_status: AbstractionStatus = AbstractionStatus.PENDING
    # Tracks whether this record has been processed by the learning loop
    notes: str = ""


# ---------------------------------------------------------------------------
# RecommendationReview
# ---------------------------------------------------------------------------

@dataclass
class RecommendationReview:
    """Captures reviewer redline feedback as Tier-2 evidence (Flow 2)."""
    date: str = ""
    proposed_counter: str = ""
    # The counter-proposal language the agent drafted
    reviewer_role: str = ""
    # e.g. "owner" | "legal" — deployment-specific role labels live in Layer C
    reaction: Optional[ReviewerReaction] = None
    revised_language: str = ""
    # What the reviewer changed it to (empty if accepted as-is)
    rationale: str = ""
    abstraction_status: AbstractionStatus = AbstractionStatus.PENDING
    # Reuses AbstractionStatus — same processing pipeline as OutcomeRecord
    notes: str = ""


# ---------------------------------------------------------------------------
# PlaybookEntry
# ---------------------------------------------------------------------------

@dataclass
class PlaybookEntry:
    """Single playbook entry defining the operator's position on a clause type.

    Authored in Layer C and loaded by the playbook_loader at runtime.
    The schema structure here enforces the contract between content authoring
    and the Agent 5 (Redline Analysis) lookup path.
    """
    id: str = ""
    contract_type_id: str = ""
    category_id: str = ""
    sub_clause_id: str = ""
    defend_baseline: DefendBaseline = field(default_factory=DefendBaseline)
    accept_modifications: List[AcceptModification] = field(default_factory=list)
    reject_thresholds: List[RejectThreshold] = field(default_factory=list)
    negotiability: str = ""
    # Enforced enum (validated at load time in PlaybookLoader._parse_entry):
    # "signature_blocker" — firm walk-away; any modification is a deal-breaker
    # "parametric"        — structure fixed, specific values flex within constraints
    # "negotiable"        — open to substantive changes within playbook guardrails
    # "boilerplate"       — standard language; accept counterparty style edits
    constraints: dict = field(default_factory=dict)
    pending_items: List[str] = field(default_factory=list)
    examples: List[str] = field(default_factory=list)
    related_entries: List[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    review_status: str = ""
    last_reviewed_by: Optional[str] = None
    last_reviewed_date: Optional[str] = None
    evidence_tier: str = ""
    # "verified" | "provisional"
    antora_response: Optional[AntoraResponse] = field(default_factory=AntoraResponse)
    # Three-part response block: rejection, compromise, acceptance.
    # COEXISTS with accept_modifications / reject_thresholds — those classify
    # counterparty redlines; antora_response holds what the operator says back.
    # Do NOT delete accept_modifications or reject_thresholds.
    outcome_log: List[OutcomeRecord] = field(default_factory=list)
    # Per-entry log of actual negotiation outcomes.
    # Raw IP — never leaves Layer C deployment.
    # abstraction_status on each record prevents double-processing
    # into the shared learning registry.
    recommendation_reviews: List[RecommendationReview] = field(default_factory=list)
    # Tier-2 evidence: reviewer redline feedback on agent recommendations.
    # Feeds learning Flow 2 (within-deployment calibration).
    # abstraction_status prevents double-processing.


# ---------------------------------------------------------------------------
# Overlay — tightening delta applied by the resolver
# ---------------------------------------------------------------------------

@dataclass
class Overlay:
    """A tightening delta applied to a PlaybookEntry for a specific context.

    Overlays are authored in Layer C and applied by the OverlayResolver.
    Tightening only: add reject thresholds, remove acceptable modifications,
    or raise numeric constraints — never the reverse.

    overlay_type values: "counterparty" | "project" | "commodity"
    An empty entry_id means the overlay applies to any entry passed to the
    resolver (caller is responsible for filtering before calling resolve()).
    """
    overlay_id: str = ""
    overlay_type: str = ""
    entry_id: str = ""
    # The PlaybookEntry.id this overlay targets; empty = caller-filtered
    add_reject_thresholds: List[RejectThreshold] = field(default_factory=list)
    # Additional thresholds — unioned with the base entry's reject_thresholds
    remove_accept_modification_ids: List[str] = field(default_factory=list)
    # AcceptModification.id values to remove (position tightening)
    constraint_overrides: dict = field(default_factory=dict)
    # Constraint overrides — max-wins per numeric key (higher = tighter minimum)


# ---------------------------------------------------------------------------
# ResolutionResult — output of the overlay resolver
# ---------------------------------------------------------------------------

@dataclass
class ResolutionResult:
    """The resolved PlaybookEntry after overlay application, with full provenance."""
    entry_id: str = ""
    resolved_entry: Optional[PlaybookEntry] = None
    provenance: List[str] = field(default_factory=list)
    # Ordered provenance tokens tracing each change:
    # "baseline:<entry_id>"
    # "overlay:<type>:<overlay_id> → add_reject_threshold:<id>"
    # "rule:max_wins:<key>=<new> (was <prior>) via overlay:<type>:<id>"
    # "overlay:<type>:<overlay_id> → remove_accept_modification:<id>"
    # "overlay:<type>:<overlay_id> → override_constraint:<key>"
