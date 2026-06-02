"""Unit tests: PromptRegistry.

Uses temporary directories with synthetic prompt template files.
No deployment-specific identifiers appear as Python literals.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from acp.layer_b.loaders.prompt_registry import PromptNotFoundError, PromptRegistry

# ---------------------------------------------------------------------------
# Path to real Layer C deployment for smoke test
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[4]
_LAYER_C = _REPO_ROOT / "acp" / "layer_c_antora"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_prompt(prompts_dir: Path, filename: str, content: str) -> None:
    prompts_dir.mkdir(parents=True, exist_ok=True)
    (prompts_dir / filename).write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Tests: missing directory
# ---------------------------------------------------------------------------

class TestPromptRegistryMissingDirectory(unittest.TestCase):

    def test_list_keys_empty_when_no_prompts_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = PromptRegistry(Path(tmp))
            self.assertEqual(reg.list_keys(), [])

    def test_has_returns_false_when_no_prompts_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = PromptRegistry(Path(tmp))
            self.assertFalse(reg.has("anything"))

    def test_get_or_none_returns_none_when_no_prompts_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = PromptRegistry(Path(tmp))
            self.assertIsNone(reg.get_or_none("anything"))

    def test_get_raises_prompt_not_found_when_no_prompts_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = PromptRegistry(Path(tmp))
            with self.assertRaises(PromptNotFoundError):
                reg.get("anything")


# ---------------------------------------------------------------------------
# Tests: .txt templates
# ---------------------------------------------------------------------------

class TestPromptRegistryTxtTemplates(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)
        pd = self.root / "prompts"
        _write_prompt(pd, "counter_proposal_draft.txt", "Draft a counter-proposal.")
        _write_prompt(pd, "rejection_rationale.txt", "Explain why rejected.")
        self.reg = PromptRegistry(self.root)

    def test_two_keys_loaded(self):
        self.assertEqual(len(self.reg.list_keys()), 2)

    def test_keys_are_filename_stems(self):
        keys = set(self.reg.list_keys())
        self.assertEqual(keys, {"counter_proposal_draft", "rejection_rationale"})

    def test_get_returns_correct_content(self):
        content = self.reg.get("counter_proposal_draft")
        self.assertEqual(content.strip(), "Draft a counter-proposal.")

    def test_get_or_none_returns_content(self):
        content = self.reg.get_or_none("rejection_rationale")
        self.assertIsNotNone(content)
        self.assertIn("rejected", content)

    def test_has_returns_true_for_existing_key(self):
        self.assertTrue(self.reg.has("counter_proposal_draft"))

    def test_has_returns_false_for_unknown_key(self):
        self.assertFalse(self.reg.has("nonexistent_key"))

    def test_get_raises_prompt_not_found_for_unknown(self):
        with self.assertRaises(PromptNotFoundError):
            self.reg.get("nonexistent_key")

    def test_get_or_none_returns_none_for_unknown(self):
        self.assertIsNone(self.reg.get_or_none("nonexistent_key"))

    def test_list_keys_sorted(self):
        keys = self.reg.list_keys()
        self.assertEqual(keys, sorted(keys))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Tests: .md templates
# ---------------------------------------------------------------------------

class TestPromptRegistryMdTemplates(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)
        pd = self.root / "prompts"
        _write_prompt(pd, "analysis_system.md", "# System Prompt\nAnalyse clauses.")
        self.reg = PromptRegistry(self.root)

    def test_md_file_loaded(self):
        self.assertTrue(self.reg.has("analysis_system"))

    def test_md_content_returned(self):
        content = self.reg.get("analysis_system")
        self.assertIn("System Prompt", content)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Tests: unsupported extensions ignored
# ---------------------------------------------------------------------------

class TestPromptRegistryIgnoresUnsupportedExtensions(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)
        pd = self.root / "prompts"
        pd.mkdir(parents=True)
        _write_prompt(pd, "good_template.txt", "Good content.")
        (pd / "ignored.py").write_text("python file", encoding="utf-8")
        (pd / "ignored.yaml").write_text("yaml: file", encoding="utf-8")
        (pd / "ignored.json").write_text("{}", encoding="utf-8")
        self.reg = PromptRegistry(self.root)

    def test_only_txt_file_loaded(self):
        self.assertEqual(self.reg.list_keys(), ["good_template"])

    def test_python_file_not_registered(self):
        self.assertFalse(self.reg.has("ignored"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Tests: duplicate stem raises
# ---------------------------------------------------------------------------

class TestPromptRegistryDuplicateStem(unittest.TestCase):

    def test_duplicate_stem_raises_value_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pd = root / "prompts"
            _write_prompt(pd, "the_key.txt", "Version one.")
            _write_prompt(pd, "the_key.md", "Version two.")
            reg = PromptRegistry(root)
            with self.assertRaises(ValueError):
                reg.list_keys()  # triggers load


# ---------------------------------------------------------------------------
# Tests: real layer_c_antora — no prompts/ yet, should return empty
# ---------------------------------------------------------------------------

class TestPromptRegistryRealDeploymentNoPromptsDir(unittest.TestCase):
    """prompts/ directory does not exist in layer_c_antora yet.
    Registry should return empty without raising.
    """

    def test_list_keys_empty_or_populated_without_error(self):
        reg = PromptRegistry(_LAYER_C)
        keys = reg.list_keys()
        self.assertIsInstance(keys, list)

    def test_has_does_not_raise(self):
        reg = PromptRegistry(_LAYER_C)
        result = reg.has("any_key")
        self.assertIsInstance(result, bool)


if __name__ == "__main__":
    unittest.main()
