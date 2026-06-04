"""Unit tests: PilotEntryLoader.

Per Implementation Guide Section 7.1: synthetic fixtures only.

Tests confirm that:
  - lookup() returns the correct PilotEntryRef for known clause references
  - lookup() returns None for unknown clause references
  - has_entry() returns True/False correctly
  - evidence_source_string() returns a correctly formatted string or None
  - CLAUSE_TO_PILOT covers exactly the two expected pilot entries
  - PilotEntryRef fields match the authored pilot PlaybookEntries
"""

from __future__ import annotations

import unittest

from acp.layer_b.loaders.pilot_entry_loader import (
    CLAUSE_TO_PILOT,
    PilotEntryLoader,
    PilotEntryRef,
)


class TestPilotEntryLoaderLookup(unittest.TestCase):

    def setUp(self):
        self.loader = PilotEntryLoader()

    # --- Known clause references ---

    def test_5_1_returns_warranty_period_entry(self):
        ref = self.loader.lookup("5.1")
        self.assertIsNotNone(ref)
        self.assertEqual(ref.entry_id, "mepa.warranty.warranty_period")

    def test_8_3_returns_lol_direct_damages_entry(self):
        ref = self.loader.lookup("8.3")
        self.assertIsNotNone(ref)
        self.assertEqual(
            ref.entry_id,
            "mepa.limitation_of_liability.direct_damages_clarification",
        )

    # --- Unknown clause references ---

    def test_unknown_numeric_clause_returns_none(self):
        self.assertIsNone(self.loader.lookup("99.9"))

    def test_empty_string_returns_none(self):
        self.assertIsNone(self.loader.lookup(""))

    def test_existing_pattern_clauses_not_in_loader(self):
        # Confirm no overlap with the five original mock_redline_generator patterns
        for ref in ("2.9", "3.2", "4.4", "6.1", "7.2"):
            self.assertIsNone(
                self.loader.lookup(ref),
                f"Clause {ref} should not be in pilot loader",
            )

    # --- Evidence tier ---

    def test_warranty_period_evidence_tier_provisional(self):
        ref = self.loader.lookup("5.1")
        self.assertEqual(ref.evidence_tier, "provisional")

    def test_lol_direct_damages_evidence_tier_provisional(self):
        ref = self.loader.lookup("8.3")
        self.assertEqual(ref.evidence_tier, "provisional")

    # --- Negotiability ---

    def test_warranty_period_negotiability_parametric(self):
        ref = self.loader.lookup("5.1")
        self.assertEqual(ref.negotiability, "parametric")

    def test_lol_direct_damages_negotiability_signature_blocker(self):
        ref = self.loader.lookup("8.3")
        self.assertEqual(ref.negotiability, "signature_blocker")

    # --- Frozen dataclass ---

    def test_pilot_entry_ref_is_frozen(self):
        ref = self.loader.lookup("5.1")
        with self.assertRaises(Exception):
            ref.entry_id = "mutated"  # type: ignore[misc]


class TestPilotEntryLoaderHasEntry(unittest.TestCase):

    def setUp(self):
        self.loader = PilotEntryLoader()

    def test_has_entry_true_for_5_1(self):
        self.assertTrue(self.loader.has_entry("5.1"))

    def test_has_entry_true_for_8_3(self):
        self.assertTrue(self.loader.has_entry("8.3"))

    def test_has_entry_false_for_original_patterns(self):
        for ref in ("2.9", "3.2", "4.4", "6.1", "7.2"):
            self.assertFalse(
                self.loader.has_entry(ref),
                f"has_entry should be False for {ref}",
            )

    def test_has_entry_false_for_empty_string(self):
        self.assertFalse(self.loader.has_entry(""))


class TestPilotEntryLoaderEvidenceSourceString(unittest.TestCase):

    def setUp(self):
        self.loader = PilotEntryLoader()

    def test_warranty_period_format_three_parts(self):
        src = self.loader.evidence_source_string("5.1")
        self.assertIsNotNone(src)
        parts = src.split(" | ")
        self.assertEqual(len(parts), 3, f"Expected 3 pipe-separated parts, got: {src!r}")

    def test_warranty_period_entry_id_in_source(self):
        src = self.loader.evidence_source_string("5.1")
        self.assertTrue(src.startswith("mepa.warranty.warranty_period"))

    def test_warranty_period_provisional_in_source(self):
        src = self.loader.evidence_source_string("5.1")
        self.assertIn("provisional", src)

    def test_lol_entry_id_in_source(self):
        src = self.loader.evidence_source_string("8.3")
        self.assertIn(
            "mepa.limitation_of_liability.direct_damages_clarification", src
        )

    def test_lol_provisional_in_source(self):
        src = self.loader.evidence_source_string("8.3")
        self.assertIn("provisional", src)

    def test_unknown_clause_returns_none(self):
        self.assertIsNone(self.loader.evidence_source_string("7.2"))
        self.assertIsNone(self.loader.evidence_source_string(""))


class TestClauseToPilotMapping(unittest.TestCase):

    def test_exactly_two_entries(self):
        """CLAUSE_TO_PILOT covers exactly the two authored pilot entries."""
        self.assertEqual(len(CLAUSE_TO_PILOT), 2)

    def test_clause_5_1_maps_to_warranty_period(self):
        self.assertEqual(CLAUSE_TO_PILOT["5.1"], "warranty_period")

    def test_clause_8_3_maps_to_lol_direct_damages(self):
        self.assertEqual(CLAUSE_TO_PILOT["8.3"], "lol_direct_damages")

    def test_no_overlap_with_original_mock_patterns(self):
        original_patterns = {"2.9", "3.2", "4.4", "6.1", "7.2"}
        overlap = set(CLAUSE_TO_PILOT.keys()) & original_patterns
        self.assertEqual(
            overlap,
            set(),
            f"CLAUSE_TO_PILOT must not overlap with original mock patterns: {overlap}",
        )


if __name__ == "__main__":
    unittest.main()
