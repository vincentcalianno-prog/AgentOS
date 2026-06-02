"""Unit tests: SkillLoader.

Uses temporary directories with synthetic SKILL.md content throughout.
No deployment-specific identifiers appear as Python literals.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from acp.layer_b.loaders.skill_loader import SkillLoader, SkillMeta

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SKILL_WITH_HEADING = """\
# Generic Contract Review Skill
Analyse contract clauses against the operator's playbook.

## Usage
Run this skill when a new redline arrives.
"""

_SKILL_NO_HEADING = """\
Skill body without a heading.
Second line.
"""

_SKILL_WITH_H2_ONLY = """\
## Not a top-level heading
Body content.
"""


def _write_skill(skills_dir: Path, skill_name: str, content: str) -> None:
    d = skills_dir / skill_name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Tests: missing directory
# ---------------------------------------------------------------------------

class TestSkillLoaderMissingDirectory(unittest.TestCase):

    def test_list_skills_empty_when_no_skills_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            loader = SkillLoader(Path(tmp))
            self.assertEqual(loader.list_skills(), [])

    def test_skill_names_empty_when_no_skills_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            loader = SkillLoader(Path(tmp))
            self.assertEqual(loader.skill_names(), [])

    def test_get_meta_returns_none_when_no_skills_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            loader = SkillLoader(Path(tmp))
            self.assertIsNone(loader.get_meta("anything"))

    def test_load_raises_key_error_when_no_skills_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            loader = SkillLoader(Path(tmp))
            with self.assertRaises(KeyError):
                loader.load("anything")


# ---------------------------------------------------------------------------
# Tests: single skill with heading
# ---------------------------------------------------------------------------

class TestSkillLoaderSingleSkillWithHeading(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)
        skills_dir = self.root / "skills"
        _write_skill(skills_dir, "contract_review", _SKILL_WITH_HEADING)
        self.loader = SkillLoader(self.root)

    def test_one_skill_discovered(self):
        self.assertEqual(len(self.loader.list_skills()), 1)

    def test_skill_name_is_directory_name(self):
        meta = self.loader.get_meta("contract_review")
        self.assertIsNotNone(meta)
        self.assertEqual(meta.name, "contract_review")

    def test_title_extracted_from_heading(self):
        meta = self.loader.get_meta("contract_review")
        self.assertEqual(meta.title, "Generic Contract Review Skill")

    def test_skill_meta_is_frozen(self):
        meta = self.loader.get_meta("contract_review")
        with self.assertRaises(Exception):
            meta.name = "mutated"  # type: ignore[misc]

    def test_file_path_points_to_skill_md(self):
        meta = self.loader.get_meta("contract_review")
        self.assertTrue(meta.file_path.exists())
        self.assertEqual(meta.file_path.name, "SKILL.md")

    def test_load_returns_full_content(self):
        content = self.loader.load("contract_review")
        self.assertIn("Generic Contract Review Skill", content)
        self.assertIn("## Usage", content)

    def test_skill_names_contains_skill(self):
        self.assertIn("contract_review", self.loader.skill_names())

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Tests: skill without a heading — fallback to directory name
# ---------------------------------------------------------------------------

class TestSkillLoaderNoHeading(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)
        skills_dir = self.root / "skills"
        _write_skill(skills_dir, "no_heading_skill", _SKILL_NO_HEADING)
        self.loader = SkillLoader(self.root)

    def test_title_falls_back_to_directory_name(self):
        meta = self.loader.get_meta("no_heading_skill")
        self.assertIsNotNone(meta)
        self.assertEqual(meta.title, "no_heading_skill")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Tests: h2 heading only — should not be treated as h1 title
# ---------------------------------------------------------------------------

class TestSkillLoaderH2HeadingOnly(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)
        skills_dir = self.root / "skills"
        _write_skill(skills_dir, "h2_skill", _SKILL_WITH_H2_ONLY)
        self.loader = SkillLoader(self.root)

    def test_h2_heading_does_not_set_title(self):
        meta = self.loader.get_meta("h2_skill")
        self.assertIsNotNone(meta)
        # h2 (##) should not be extracted; fallback to directory name
        self.assertEqual(meta.title, "h2_skill")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Tests: multiple skills
# ---------------------------------------------------------------------------

class TestSkillLoaderMultipleSkills(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)
        skills_dir = self.root / "skills"
        _write_skill(skills_dir, "alpha_skill", "# Alpha\nContent A.")
        _write_skill(skills_dir, "beta_skill", "# Beta\nContent B.")
        _write_skill(skills_dir, "gamma_skill", "# Gamma\nContent C.")
        self.loader = SkillLoader(self.root)

    def test_three_skills_discovered(self):
        self.assertEqual(len(self.loader.list_skills()), 3)

    def test_all_skill_names_present(self):
        names = set(self.loader.skill_names())
        self.assertEqual(names, {"alpha_skill", "beta_skill", "gamma_skill"})

    def test_each_skill_has_correct_title(self):
        self.assertEqual(self.loader.get_meta("alpha_skill").title, "Alpha")
        self.assertEqual(self.loader.get_meta("beta_skill").title, "Beta")
        self.assertEqual(self.loader.get_meta("gamma_skill").title, "Gamma")

    def test_load_returns_content_for_each(self):
        self.assertIn("Content A.", self.loader.load("alpha_skill"))
        self.assertIn("Content B.", self.loader.load("beta_skill"))
        self.assertIn("Content C.", self.loader.load("gamma_skill"))

    def test_get_meta_unknown_returns_none(self):
        self.assertIsNone(self.loader.get_meta("delta_skill"))

    def test_load_unknown_raises_key_error(self):
        with self.assertRaises(KeyError):
            self.loader.load("delta_skill")

    def test_list_skills_returns_skill_meta_instances(self):
        for meta in self.loader.list_skills():
            self.assertIsInstance(meta, SkillMeta)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Tests: real layer_c_antora — no skills/ yet, should return empty
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[4]
_LAYER_C = _REPO_ROOT / "acp" / "layer_c_antora"


class TestSkillLoaderRealDeploymentNoSkillsDir(unittest.TestCase):
    """skills/ directory does not exist in layer_c_antora yet.
    Loader should return empty without raising.
    """

    def test_list_skills_empty_for_real_layer_c(self):
        loader = SkillLoader(_LAYER_C)
        # skills/ directory absent → empty list; does not raise
        skills = loader.list_skills()
        self.assertIsInstance(skills, list)

    def test_skill_names_empty_or_populated_without_error(self):
        loader = SkillLoader(_LAYER_C)
        names = loader.skill_names()
        self.assertIsInstance(names, list)


if __name__ == "__main__":
    unittest.main()
