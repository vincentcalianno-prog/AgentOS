"""Unit tests: PlaybookLoader.

Two test classes:

TestPlaybookLoaderSyntheticFixtures
    Uses temporary directories with synthetic YAML content.
    Synthetic entry IDs use "generic.*" prefixes; contract_type_id is
    "generic-agreement".  No deployment-specific identifiers.

TestPlaybookLoaderRealDeployment
    Loads the real committed Layer C playbook directory and verifies
    structural invariants.  Assertions reference only structural
    properties (counts, field presence, evidence tier values) — not
    specific text values that could contain deployment-specific content.
"""

from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from acp.layer_b.loaders.playbook_loader import PlaybookLoadError, PlaybookLoader
from acp.schemas.playbook_schemas import PlaybookEntry

# ---------------------------------------------------------------------------
# Path to the real Layer C deployment for smoke tests
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[4]
_LAYER_C = _REPO_ROOT / "acp" / "layer_c_antora"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MINIMAL_YAML = textwrap.dedent("""\
    id: generic.delivery.delivery_terms
    contract_type_id: generic-agreement
    category_id: delivery
    sub_clause_id: delivery_terms
""")

_FULL_YAML = textwrap.dedent("""\
    id: generic.delivery.delivery_terms
    contract_type_id: generic-agreement
    category_id: delivery
    sub_clause_id: delivery_terms
    defend_baseline:
      template_ref:
        document_id: generic_template
        section_id: "§2.1"
        version: "v1.0"
      guidance: Operator standard is delivery to project site.
    negotiability: parametric
    evidence_tier: provisional
    review_status: draft
    accept_modifications:
      - id: delivery.accept.schedule_adj
        description: Schedule adjustment with advance notice.
        example_language: Thirty days advance notice required.
        rationale: Commercial reality on capital equipment.
    reject_thresholds:
      - id: delivery.reject.pre_site
        description: Delivery risk transferred before site arrival.
        example_language: Risk transfers at origin.
        rationale: Operator bears uninsured transit risk.
      - id: delivery.reject.duty_passthrough
        description: Import duties passed through to operator.
        example_language: Plus applicable import duties.
        rationale: Operator cannot absorb unbudgeted tariff exposure.
    antora_response:
      rejection_response:
        rationale: Operator requires delivery to project site.
        counter_proposal: Delivery shall be to the named project site.
      compromise_response:
        conditions: Only where logistics team confirms cost benefit.
        revised_language: Delivery to [project site] with cargo insurance.
      acceptance_response:
        rationale: Counterparty language preserves site delivery point.
    constraints:
      minimum_notice_days: 30
    pending_items:
      - Confirm destination format convention.
    related_entries:
      - generic.delivery.risk_of_loss
    examples:
      - Project delivery confirmation on record.
""")

_PAYMENT_YAML = textwrap.dedent("""\
    id: generic.payment.payment_terms
    contract_type_id: generic-agreement
    category_id: payment
    sub_clause_id: payment_terms
    negotiability: parametric
    evidence_tier: provisional
    review_status: draft
    reject_thresholds:
      - id: payment.reject.net_30_or_less
        description: Net-30 or shorter demanded without milestone structure.
        example_language: Payment due Net-30 from invoice.
        rationale: Operator target is Net-90.
    constraints:
      invoice_dispute_window_days: 10
""")


def _write(root: Path, rel: str, content: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Synthetic fixture tests
# ---------------------------------------------------------------------------

class TestPlaybookLoaderMissingDirectory(unittest.TestCase):

    def test_missing_playbook_dir_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            loader = PlaybookLoader(Path(tmp))
            self.assertEqual(loader.load_all(), {})

    def test_missing_playbook_dir_get_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            loader = PlaybookLoader(Path(tmp))
            self.assertIsNone(loader.get("anything"))

    def test_missing_playbook_dir_entry_ids_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            loader = PlaybookLoader(Path(tmp))
            self.assertEqual(loader.entry_ids(), [])


class TestPlaybookLoaderMinimalEntry(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)
        _write(self.root, "playbook/delivery/entry.yaml", _MINIMAL_YAML)
        self.loader = PlaybookLoader(self.root)

    def test_load_all_returns_one_entry(self):
        entries = self.loader.load_all()
        self.assertEqual(len(entries), 1)

    def test_entry_id_correct(self):
        entry = self.loader.get("generic.delivery.delivery_terms")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.id, "generic.delivery.delivery_terms")

    def test_entry_is_playbook_entry_instance(self):
        entry = self.loader.get("generic.delivery.delivery_terms")
        self.assertIsInstance(entry, PlaybookEntry)

    def test_contract_type_id_loaded(self):
        entry = self.loader.get("generic.delivery.delivery_terms")
        self.assertEqual(entry.contract_type_id, "generic-agreement")

    def test_category_id_loaded(self):
        entry = self.loader.get("generic.delivery.delivery_terms")
        self.assertEqual(entry.category_id, "delivery")

    def test_sub_clause_id_loaded(self):
        entry = self.loader.get("generic.delivery.delivery_terms")
        self.assertEqual(entry.sub_clause_id, "delivery_terms")

    def test_missing_id_returns_none(self):
        self.assertIsNone(self.loader.get("does.not.exist"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)


class TestPlaybookLoaderFullEntry(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)
        _write(self.root, "playbook/delivery/delivery_terms.yaml", _FULL_YAML)
        self.loader = PlaybookLoader(self.root)
        self.entry = self.loader.get("generic.delivery.delivery_terms")

    def test_entry_loaded(self):
        self.assertIsNotNone(self.entry)

    def test_negotiability_loaded(self):
        self.assertEqual(self.entry.negotiability, "parametric")

    def test_evidence_tier_loaded(self):
        self.assertEqual(self.entry.evidence_tier, "provisional")

    def test_review_status_loaded(self):
        self.assertEqual(self.entry.review_status, "draft")

    def test_defend_baseline_guidance_nonempty(self):
        self.assertNotEqual(self.entry.defend_baseline.guidance, "")

    def test_defend_baseline_template_ref_document_id(self):
        self.assertEqual(
            self.entry.defend_baseline.template_ref.document_id,
            "generic_template",
        )

    def test_defend_baseline_template_ref_section_id(self):
        self.assertEqual(
            self.entry.defend_baseline.template_ref.section_id, "§2.1"
        )

    def test_accept_modifications_count(self):
        self.assertEqual(len(self.entry.accept_modifications), 1)

    def test_accept_modification_id(self):
        self.assertEqual(
            self.entry.accept_modifications[0].id, "delivery.accept.schedule_adj"
        )

    def test_accept_modification_fields_nonempty(self):
        mod = self.entry.accept_modifications[0]
        self.assertNotEqual(mod.description, "")
        self.assertNotEqual(mod.example_language, "")
        self.assertNotEqual(mod.rationale, "")

    def test_reject_thresholds_count(self):
        self.assertEqual(len(self.entry.reject_thresholds), 2)

    def test_reject_threshold_ids(self):
        ids = {t.id for t in self.entry.reject_thresholds}
        self.assertIn("delivery.reject.pre_site", ids)
        self.assertIn("delivery.reject.duty_passthrough", ids)

    def test_antora_response_present(self):
        self.assertIsNotNone(self.entry.antora_response)

    def test_antora_response_rejection_rationale_nonempty(self):
        self.assertNotEqual(
            self.entry.antora_response.rejection_response.rationale, ""
        )

    def test_antora_response_compromise_conditions_nonempty(self):
        self.assertNotEqual(
            self.entry.antora_response.compromise_response.conditions, ""
        )

    def test_antora_response_acceptance_rationale_nonempty(self):
        self.assertNotEqual(
            self.entry.antora_response.acceptance_response.rationale, ""
        )

    def test_constraints_numeric_loaded(self):
        self.assertIn("minimum_notice_days", self.entry.constraints)
        self.assertEqual(self.entry.constraints["minimum_notice_days"], 30)

    def test_pending_items_loaded(self):
        self.assertEqual(len(self.entry.pending_items), 1)

    def test_related_entries_loaded(self):
        self.assertIn("generic.delivery.risk_of_loss", self.entry.related_entries)

    def test_examples_loaded(self):
        self.assertEqual(len(self.entry.examples), 1)

    def test_outcome_log_defaults_empty(self):
        self.assertEqual(self.entry.outcome_log, [])

    def test_recommendation_reviews_defaults_empty(self):
        self.assertEqual(self.entry.recommendation_reviews, [])

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)


class TestPlaybookLoaderMultipleEntries(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)
        _write(self.root, "playbook/delivery/delivery_terms.yaml", _FULL_YAML)
        _write(self.root, "playbook/payment/payment_terms.yaml", _PAYMENT_YAML)
        self.loader = PlaybookLoader(self.root)

    def test_two_entries_loaded(self):
        self.assertEqual(len(self.loader.load_all()), 2)

    def test_both_entry_ids_present(self):
        ids = set(self.loader.entry_ids())
        self.assertIn("generic.delivery.delivery_terms", ids)
        self.assertIn("generic.payment.payment_terms", ids)

    def test_get_by_sub_clause_delivery(self):
        entry = self.loader.get_by_sub_clause("delivery", "delivery_terms")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.id, "generic.delivery.delivery_terms")

    def test_get_by_sub_clause_payment(self):
        entry = self.loader.get_by_sub_clause("payment", "payment_terms")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.id, "generic.payment.payment_terms")

    def test_get_by_sub_clause_unknown_returns_none(self):
        self.assertIsNone(self.loader.get_by_sub_clause("warranty", "duration"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)


class TestPlaybookLoaderErrorCases(unittest.TestCase):

    def test_missing_id_raises_playbook_load_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, "playbook/bad.yaml", "category_id: delivery\n")
            loader = PlaybookLoader(root)
            with self.assertRaises(PlaybookLoadError):
                loader.load_all()

    def test_duplicate_entry_id_raises_playbook_load_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, "playbook/a/entry.yaml", _MINIMAL_YAML)
            _write(root, "playbook/b/entry.yaml", _MINIMAL_YAML)
            loader = PlaybookLoader(root)
            with self.assertRaises(PlaybookLoadError):
                loader.load_all()

    def test_invalid_yaml_raises_playbook_load_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, "playbook/bad.yaml", "id: [unclosed\n")
            loader = PlaybookLoader(root)
            with self.assertRaises(PlaybookLoadError):
                loader.load_all()

    def test_non_mapping_yaml_raises_playbook_load_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, "playbook/list.yaml", "- item1\n- item2\n")
            loader = PlaybookLoader(root)
            with self.assertRaises(PlaybookLoadError):
                loader.load_all()

    def test_empty_constraints_loads_as_empty_dict(self):
        yaml_content = _MINIMAL_YAML + "constraints: {}\n"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, "playbook/e.yaml", yaml_content)
            loader = PlaybookLoader(root)
            entry = loader.get("generic.delivery.delivery_terms")
            self.assertIsNotNone(entry)
            self.assertEqual(entry.constraints, {})


class TestPlaybookLoaderIdempotent(unittest.TestCase):
    """load_all() called multiple times returns the same results."""

    def test_repeated_load_all_consistent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, "playbook/e.yaml", _MINIMAL_YAML)
            loader = PlaybookLoader(root)
            first = loader.load_all()
            second = loader.load_all()
            self.assertEqual(set(first.keys()), set(second.keys()))


# ---------------------------------------------------------------------------
# Real deployment smoke tests
# ---------------------------------------------------------------------------

class TestPlaybookLoaderRealDeployment(unittest.TestCase):
    """Structural invariants against the committed Layer C playbook.

    Assertions check structure only — not specific text values — to stay
    discipline-clean.
    """

    def setUp(self):
        self.loader = PlaybookLoader(_LAYER_C)
        self.entries = self.loader.load_all()

    def test_four_entries_committed(self):
        self.assertEqual(len(self.entries), 4)

    def test_all_entries_have_nonempty_id(self):
        for entry_id, entry in self.entries.items():
            self.assertNotEqual(entry.id, "", f"entry {entry_id} has empty id")
            self.assertEqual(entry_id, entry.id)

    def test_all_entries_have_evidence_tier(self):
        valid_tiers = {"verified", "provisional"}
        for entry in self.entries.values():
            self.assertIn(
                entry.evidence_tier,
                valid_tiers,
                f"entry {entry.id} has unexpected evidence_tier: {entry.evidence_tier!r}",
            )

    def test_all_entries_have_at_least_one_reject_threshold(self):
        for entry in self.entries.values():
            self.assertGreater(
                len(entry.reject_thresholds),
                0,
                f"entry {entry.id} has no reject_thresholds",
            )

    def test_all_entries_have_antora_response_with_rationale(self):
        for entry in self.entries.values():
            self.assertIsNotNone(entry.antora_response)
            self.assertNotEqual(
                entry.antora_response.rejection_response.rationale,
                "",
                f"entry {entry.id} has empty rejection rationale",
            )

    def test_all_entries_have_defend_baseline_guidance(self):
        for entry in self.entries.values():
            self.assertNotEqual(
                entry.defend_baseline.guidance,
                "",
                f"entry {entry.id} has empty baseline guidance",
            )

    def test_known_entry_ids_present(self):
        known_ids = {
            "mepa.delivery.ddp_terms",
            "mepa.delivery.risk_of_loss",
            "mepa.delivery.inspection_acceptance",
            "mepa.payment.net_terms",
        }
        loaded_ids = set(self.loader.entry_ids())
        self.assertEqual(loaded_ids, known_ids)

    def test_get_by_sub_clause_delivery_ddp(self):
        entry = self.loader.get_by_sub_clause("delivery", "ddp_terms")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.id, "mepa.delivery.ddp_terms")

    def test_get_by_sub_clause_payment_net(self):
        entry = self.loader.get_by_sub_clause("payment", "net_terms")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.id, "mepa.payment.net_terms")

    def test_delivery_entries_have_category_delivery(self):
        delivery_ids = {
            "mepa.delivery.ddp_terms",
            "mepa.delivery.risk_of_loss",
            "mepa.delivery.inspection_acceptance",
        }
        for eid in delivery_ids:
            entry = self.loader.get(eid)
            self.assertIsNotNone(entry)
            self.assertEqual(entry.category_id, "delivery")

    def test_payment_entry_has_category_payment(self):
        entry = self.loader.get("mepa.payment.net_terms")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.category_id, "payment")

    def test_inspection_acceptance_has_numeric_constraints(self):
        entry = self.loader.get("mepa.delivery.inspection_acceptance")
        self.assertIsNotNone(entry)
        self.assertTrue(
            any(isinstance(v, (int, float)) for v in entry.constraints.values()),
            "inspection_acceptance entry should have at least one numeric constraint",
        )

    def test_payment_entry_has_constraints(self):
        entry = self.loader.get("mepa.payment.net_terms")
        self.assertIsNotNone(entry)
        self.assertGreater(len(entry.constraints), 0)


if __name__ == "__main__":
    unittest.main()
