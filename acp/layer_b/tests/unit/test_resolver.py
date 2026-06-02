"""Unit tests: OverlayResolver.

All fixtures are synthetic — no deployment-specific identifiers.
Entry IDs use "generic.*" prefix; overlay_type strings use the three
canonical values: "counterparty", "project", "commodity".

Tests cover:
  - Baseline resolution (no overlays)
  - Reject threshold union
  - Accept modification removal
  - Numeric constraint max-wins
  - Non-numeric constraint override
  - No mutation of base entry
  - Overlay skipped when entry_id doesn't match
  - Overlay applied when entry_id is empty
  - Multiple overlays applied in order
  - Provenance chain structure and content
"""

from __future__ import annotations

import copy
import unittest

from acp.layer_b.resolver import OverlayResolver
from acp.schemas.playbook_schemas import (
    AcceptModification,
    Overlay,
    PlaybookEntry,
    RejectThreshold,
    ResolutionResult,
)

# ---------------------------------------------------------------------------
# Synthetic fixture builders
# ---------------------------------------------------------------------------

def _base_entry(
    entry_id: str = "generic.delivery.delivery_terms",
    extra_accept_mods: list[AcceptModification] | None = None,
    extra_reject_thresholds: list[RejectThreshold] | None = None,
    constraints: dict | None = None,
) -> PlaybookEntry:
    accept_mods = [
        AcceptModification(
            id="accept.schedule_adj",
            description="Schedule adjustment with advance notice.",
        ),
        AcceptModification(
            id="accept.alternate_route",
            description="Alternate delivery route acceptable.",
        ),
    ]
    if extra_accept_mods:
        accept_mods.extend(extra_accept_mods)

    reject_thresholds = [
        RejectThreshold(
            id="reject.pre_site_risk",
            description="Risk transfers before site arrival.",
        ),
    ]
    if extra_reject_thresholds:
        reject_thresholds.extend(extra_reject_thresholds)

    return PlaybookEntry(
        id=entry_id,
        category_id="delivery",
        sub_clause_id="delivery_terms",
        accept_modifications=accept_mods,
        reject_thresholds=reject_thresholds,
        constraints=constraints or {"minimum_notice_days": 30, "mode": "standard"},
    )


def _counterparty_overlay(
    overlay_id: str = "cp_overlay_001",
    entry_id: str = "generic.delivery.delivery_terms",
    add_reject: list[RejectThreshold] | None = None,
    remove_accept: list[str] | None = None,
    constraint_overrides: dict | None = None,
) -> Overlay:
    return Overlay(
        overlay_id=overlay_id,
        overlay_type="counterparty",
        entry_id=entry_id,
        add_reject_thresholds=add_reject or [],
        remove_accept_modification_ids=remove_accept or [],
        constraint_overrides=constraint_overrides or {},
    )


# ---------------------------------------------------------------------------
# Tests: baseline (no overlays)
# ---------------------------------------------------------------------------

class TestResolverBaseline(unittest.TestCase):

    def setUp(self):
        self.resolver = OverlayResolver()
        self.base = _base_entry()

    def test_result_is_resolution_result(self):
        result = self.resolver.resolve(self.base, [])
        self.assertIsInstance(result, ResolutionResult)

    def test_entry_id_matches_base(self):
        result = self.resolver.resolve(self.base, [])
        self.assertEqual(result.entry_id, self.base.id)

    def test_resolved_entry_not_none(self):
        result = self.resolver.resolve(self.base, [])
        self.assertIsNotNone(result.resolved_entry)

    def test_resolved_entry_is_playbook_entry(self):
        result = self.resolver.resolve(self.base, [])
        self.assertIsInstance(result.resolved_entry, PlaybookEntry)

    def test_reject_thresholds_unchanged(self):
        result = self.resolver.resolve(self.base, [])
        self.assertEqual(
            len(result.resolved_entry.reject_thresholds),
            len(self.base.reject_thresholds),
        )

    def test_accept_modifications_unchanged(self):
        result = self.resolver.resolve(self.base, [])
        self.assertEqual(
            len(result.resolved_entry.accept_modifications),
            len(self.base.accept_modifications),
        )

    def test_constraints_unchanged(self):
        result = self.resolver.resolve(self.base, [])
        self.assertEqual(
            result.resolved_entry.constraints,
            self.base.constraints,
        )

    def test_provenance_starts_with_baseline(self):
        result = self.resolver.resolve(self.base, [])
        self.assertTrue(result.provenance[0].startswith("baseline:"))

    def test_provenance_contains_entry_id(self):
        result = self.resolver.resolve(self.base, [])
        self.assertIn(self.base.id, result.provenance[0])

    def test_provenance_single_entry_with_no_overlays(self):
        result = self.resolver.resolve(self.base, [])
        self.assertEqual(len(result.provenance), 1)


# ---------------------------------------------------------------------------
# Tests: reject threshold union
# ---------------------------------------------------------------------------

class TestResolverRejectThresholdUnion(unittest.TestCase):

    def setUp(self):
        self.resolver = OverlayResolver()
        self.base = _base_entry()
        self.new_rt = RejectThreshold(
            id="reject.duty_passthrough",
            description="Import duties passed to operator.",
        )
        self.overlay = _counterparty_overlay(
            add_reject=[self.new_rt],
        )

    def test_reject_threshold_count_increases(self):
        result = self.resolver.resolve(self.base, [self.overlay])
        self.assertEqual(
            len(result.resolved_entry.reject_thresholds),
            len(self.base.reject_thresholds) + 1,
        )

    def test_original_reject_threshold_preserved(self):
        result = self.resolver.resolve(self.base, [self.overlay])
        ids = {t.id for t in result.resolved_entry.reject_thresholds}
        self.assertIn("reject.pre_site_risk", ids)

    def test_new_reject_threshold_added(self):
        result = self.resolver.resolve(self.base, [self.overlay])
        ids = {t.id for t in result.resolved_entry.reject_thresholds}
        self.assertIn("reject.duty_passthrough", ids)

    def test_provenance_records_addition(self):
        result = self.resolver.resolve(self.base, [self.overlay])
        combined = " ".join(result.provenance)
        self.assertIn("add_reject_threshold:reject.duty_passthrough", combined)

    def test_overlay_type_in_provenance(self):
        result = self.resolver.resolve(self.base, [self.overlay])
        combined = " ".join(result.provenance)
        self.assertIn("overlay:counterparty:", combined)


# ---------------------------------------------------------------------------
# Tests: accept modification removal
# ---------------------------------------------------------------------------

class TestResolverRemoveAcceptModification(unittest.TestCase):

    def setUp(self):
        self.resolver = OverlayResolver()
        self.base = _base_entry()
        self.overlay = _counterparty_overlay(
            remove_accept=["accept.alternate_route"],
        )

    def test_accept_modification_removed(self):
        result = self.resolver.resolve(self.base, [self.overlay])
        ids = {m.id for m in result.resolved_entry.accept_modifications}
        self.assertNotIn("accept.alternate_route", ids)

    def test_other_accept_modification_preserved(self):
        result = self.resolver.resolve(self.base, [self.overlay])
        ids = {m.id for m in result.resolved_entry.accept_modifications}
        self.assertIn("accept.schedule_adj", ids)

    def test_accept_modification_count_decremented(self):
        result = self.resolver.resolve(self.base, [self.overlay])
        self.assertEqual(
            len(result.resolved_entry.accept_modifications),
            len(self.base.accept_modifications) - 1,
        )

    def test_provenance_records_removal(self):
        result = self.resolver.resolve(self.base, [self.overlay])
        combined = " ".join(result.provenance)
        self.assertIn("remove_accept_modification:accept.alternate_route", combined)

    def test_removing_nonexistent_id_does_not_raise(self):
        overlay = _counterparty_overlay(remove_accept=["accept.does_not_exist"])
        result = self.resolver.resolve(self.base, [overlay])
        # Count unchanged — nothing removed
        self.assertEqual(
            len(result.resolved_entry.accept_modifications),
            len(self.base.accept_modifications),
        )


# ---------------------------------------------------------------------------
# Tests: numeric constraint max-wins
# ---------------------------------------------------------------------------

class TestResolverConstraintMaxWins(unittest.TestCase):

    def setUp(self):
        self.resolver = OverlayResolver()

    def test_larger_value_wins(self):
        base = _base_entry(constraints={"minimum_notice_days": 30})
        overlay = _counterparty_overlay(
            constraint_overrides={"minimum_notice_days": 60}
        )
        result = self.resolver.resolve(base, [overlay])
        self.assertEqual(
            result.resolved_entry.constraints["minimum_notice_days"], 60
        )

    def test_smaller_overlay_value_does_not_win(self):
        base = _base_entry(constraints={"minimum_notice_days": 30})
        overlay = _counterparty_overlay(
            constraint_overrides={"minimum_notice_days": 10}
        )
        result = self.resolver.resolve(base, [overlay])
        self.assertEqual(
            result.resolved_entry.constraints["minimum_notice_days"], 30
        )

    def test_equal_value_base_preserved(self):
        base = _base_entry(constraints={"minimum_notice_days": 30})
        overlay = _counterparty_overlay(
            constraint_overrides={"minimum_notice_days": 30}
        )
        result = self.resolver.resolve(base, [overlay])
        self.assertEqual(
            result.resolved_entry.constraints["minimum_notice_days"], 30
        )

    def test_new_numeric_key_added(self):
        base = _base_entry(constraints={"minimum_notice_days": 30})
        overlay = _counterparty_overlay(
            constraint_overrides={"max_rounds": 3}
        )
        result = self.resolver.resolve(base, [overlay])
        self.assertIn("max_rounds", result.resolved_entry.constraints)
        self.assertEqual(result.resolved_entry.constraints["max_rounds"], 3)

    def test_provenance_records_max_wins_when_tighter(self):
        base = _base_entry(constraints={"minimum_notice_days": 30})
        overlay = _counterparty_overlay(
            constraint_overrides={"minimum_notice_days": 60}
        )
        result = self.resolver.resolve(base, [overlay])
        combined = " ".join(result.provenance)
        self.assertIn("rule:max_wins:minimum_notice_days=60", combined)

    def test_provenance_records_not_tighter_when_base_wins(self):
        base = _base_entry(constraints={"minimum_notice_days": 30})
        overlay = _counterparty_overlay(
            constraint_overrides={"minimum_notice_days": 10}
        )
        result = self.resolver.resolve(base, [overlay])
        combined = " ".join(result.provenance)
        self.assertIn("not tighter", combined)

    def test_float_constraint_max_wins(self):
        base = _base_entry(constraints={"ratio": 1.5})
        overlay = _counterparty_overlay(constraint_overrides={"ratio": 2.0})
        result = self.resolver.resolve(base, [overlay])
        self.assertAlmostEqual(
            result.resolved_entry.constraints["ratio"], 2.0
        )


# ---------------------------------------------------------------------------
# Tests: non-numeric constraint override
# ---------------------------------------------------------------------------

class TestResolverNonNumericConstraintOverride(unittest.TestCase):

    def setUp(self):
        self.resolver = OverlayResolver()

    def test_string_constraint_replaced(self):
        base = _base_entry(constraints={"mode": "standard"})
        overlay = _counterparty_overlay(
            constraint_overrides={"mode": "expedited"}
        )
        result = self.resolver.resolve(base, [overlay])
        self.assertEqual(result.resolved_entry.constraints["mode"], "expedited")

    def test_provenance_records_override(self):
        base = _base_entry(constraints={"mode": "standard"})
        overlay = _counterparty_overlay(
            constraint_overrides={"mode": "expedited"}
        )
        result = self.resolver.resolve(base, [overlay])
        combined = " ".join(result.provenance)
        self.assertIn("override_constraint:mode", combined)

    def test_numeric_base_with_string_overlay_replaces(self):
        base = _base_entry(constraints={"minimum_notice_days": 30})
        overlay = _counterparty_overlay(
            constraint_overrides={"minimum_notice_days": "sixty days"}
        )
        result = self.resolver.resolve(base, [overlay])
        # Non-numeric overlay replaces unconditionally
        self.assertEqual(
            result.resolved_entry.constraints["minimum_notice_days"], "sixty days"
        )


# ---------------------------------------------------------------------------
# Tests: base entry not mutated
# ---------------------------------------------------------------------------

class TestResolverNoMutation(unittest.TestCase):

    def setUp(self):
        self.resolver = OverlayResolver()

    def test_base_reject_thresholds_not_mutated(self):
        base = _base_entry()
        original_count = len(base.reject_thresholds)
        overlay = _counterparty_overlay(
            add_reject=[RejectThreshold(id="reject.new", description="New.")]
        )
        self.resolver.resolve(base, [overlay])
        self.assertEqual(len(base.reject_thresholds), original_count)

    def test_base_accept_modifications_not_mutated(self):
        base = _base_entry()
        original_count = len(base.accept_modifications)
        overlay = _counterparty_overlay(remove_accept=["accept.alternate_route"])
        self.resolver.resolve(base, [overlay])
        self.assertEqual(len(base.accept_modifications), original_count)

    def test_base_constraints_not_mutated(self):
        base = _base_entry(constraints={"minimum_notice_days": 30})
        overlay = _counterparty_overlay(
            constraint_overrides={"minimum_notice_days": 90}
        )
        self.resolver.resolve(base, [overlay])
        self.assertEqual(base.constraints["minimum_notice_days"], 30)


# ---------------------------------------------------------------------------
# Tests: overlay entry_id filtering
# ---------------------------------------------------------------------------

class TestResolverEntryIdFiltering(unittest.TestCase):

    def setUp(self):
        self.resolver = OverlayResolver()

    def test_overlay_with_wrong_entry_id_skipped(self):
        base = _base_entry(entry_id="generic.delivery.delivery_terms")
        overlay = _counterparty_overlay(
            entry_id="generic.payment.payment_terms",
            add_reject=[RejectThreshold(id="reject.new", description="New.")],
        )
        result = self.resolver.resolve(base, [overlay])
        # Overlay skipped — count unchanged
        self.assertEqual(
            len(result.resolved_entry.reject_thresholds),
            len(base.reject_thresholds),
        )

    def test_overlay_with_empty_entry_id_always_applied(self):
        base = _base_entry(entry_id="generic.delivery.delivery_terms")
        overlay = Overlay(
            overlay_id="global_overlay",
            overlay_type="project",
            entry_id="",  # empty = applies to any entry
            add_reject_thresholds=[
                RejectThreshold(id="reject.global", description="Global reject.")
            ],
        )
        result = self.resolver.resolve(base, [overlay])
        ids = {t.id for t in result.resolved_entry.reject_thresholds}
        self.assertIn("reject.global", ids)

    def test_overlay_with_matching_entry_id_applied(self):
        base = _base_entry(entry_id="generic.delivery.delivery_terms")
        overlay = _counterparty_overlay(
            entry_id="generic.delivery.delivery_terms",
            add_reject=[RejectThreshold(id="reject.matched", description="Matched.")],
        )
        result = self.resolver.resolve(base, [overlay])
        ids = {t.id for t in result.resolved_entry.reject_thresholds}
        self.assertIn("reject.matched", ids)


# ---------------------------------------------------------------------------
# Tests: multiple overlays applied in order
# ---------------------------------------------------------------------------

class TestResolverMultipleOverlays(unittest.TestCase):

    def setUp(self):
        self.resolver = OverlayResolver()

    def test_two_overlays_both_add_reject_thresholds(self):
        base = _base_entry()
        o1 = _counterparty_overlay(
            overlay_id="o1",
            add_reject=[RejectThreshold(id="reject.o1", description="From o1.")],
        )
        o2 = Overlay(
            overlay_id="o2",
            overlay_type="project",
            entry_id=base.id,
            add_reject_thresholds=[
                RejectThreshold(id="reject.o2", description="From o2.")
            ],
        )
        result = self.resolver.resolve(base, [o1, o2])
        ids = {t.id for t in result.resolved_entry.reject_thresholds}
        self.assertIn("reject.o1", ids)
        self.assertIn("reject.o2", ids)

    def test_second_overlay_tightens_constraint_further(self):
        base = _base_entry(constraints={"minimum_notice_days": 30})
        o1 = _counterparty_overlay(
            overlay_id="o1",
            constraint_overrides={"minimum_notice_days": 45},
        )
        o2 = Overlay(
            overlay_id="o2",
            overlay_type="project",
            entry_id=base.id,
            constraint_overrides={"minimum_notice_days": 60},
        )
        result = self.resolver.resolve(base, [o1, o2])
        self.assertEqual(
            result.resolved_entry.constraints["minimum_notice_days"], 60
        )

    def test_looser_second_overlay_does_not_reduce_constraint(self):
        base = _base_entry(constraints={"minimum_notice_days": 30})
        o1 = _counterparty_overlay(
            overlay_id="o1",
            constraint_overrides={"minimum_notice_days": 90},
        )
        o2 = Overlay(
            overlay_id="o2",
            overlay_type="commodity",
            entry_id=base.id,
            constraint_overrides={"minimum_notice_days": 15},
        )
        result = self.resolver.resolve(base, [o1, o2])
        # o1 sets 90; o2 tries 15 which is less tight → 90 stands
        self.assertEqual(
            result.resolved_entry.constraints["minimum_notice_days"], 90
        )

    def test_provenance_lists_all_overlays(self):
        base = _base_entry()
        o1 = _counterparty_overlay(overlay_id="o1")
        o2 = Overlay(
            overlay_id="o2",
            overlay_type="project",
            entry_id=base.id,
        )
        result = self.resolver.resolve(base, [o1, o2])
        combined = " ".join(result.provenance)
        self.assertIn("baseline:", combined)

    def test_skipped_and_applied_overlays_mix(self):
        base = _base_entry(entry_id="generic.delivery.delivery_terms")
        wrong = _counterparty_overlay(
            overlay_id="wrong",
            entry_id="generic.other.entry",
            add_reject=[RejectThreshold(id="reject.wrong", description="Wrong.")],
        )
        right = _counterparty_overlay(
            overlay_id="right",
            entry_id="generic.delivery.delivery_terms",
            add_reject=[RejectThreshold(id="reject.right", description="Right.")],
        )
        result = self.resolver.resolve(base, [wrong, right])
        ids = {t.id for t in result.resolved_entry.reject_thresholds}
        self.assertNotIn("reject.wrong", ids)
        self.assertIn("reject.right", ids)


# ---------------------------------------------------------------------------
# Tests: ResolutionResult is independent of base (deep copy)
# ---------------------------------------------------------------------------

class TestResolverResolutionResultIsDeepCopy(unittest.TestCase):

    def setUp(self):
        self.resolver = OverlayResolver()

    def test_resolved_entry_is_independent_object(self):
        base = _base_entry()
        result = self.resolver.resolve(base, [])
        self.assertIsNot(result.resolved_entry, base)

    def test_mutating_resolved_entry_does_not_affect_base(self):
        base = _base_entry()
        result = self.resolver.resolve(base, [])
        result.resolved_entry.reject_thresholds.append(
            RejectThreshold(id="reject.injected", description="Injected post-resolve.")
        )
        # Base should still have its original count
        self.assertEqual(len(base.reject_thresholds), 1)


if __name__ == "__main__":
    unittest.main()
