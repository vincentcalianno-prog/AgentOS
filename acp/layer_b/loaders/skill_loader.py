"""Skill loader for the ACP negotiation engine.

Discovers and loads SKILL.md files from <layer_c_root>/skills/.
Exposes lightweight metadata (name, title) and on-demand full-content
loading. Never executes skill content — parse only.

Expected layout::

    <layer_c_root>/
        skills/
            <skill-name>/
                SKILL.md

The skill name is the immediate parent directory of SKILL.md.
A missing skills/ directory yields an empty loader rather than raising.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class SkillMeta:
    """Lightweight metadata for a discovered SKILL.md file."""
    name: str
    # Derived from the skill's containing directory name
    title: str
    # First '# Heading' found in the file, or the name if none present
    file_path: Path
    # Absolute path to the SKILL.md file


def _extract_title(content: str, fallback: str) -> str:
    """Return the text of the first Markdown # heading, or fallback."""
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return fallback


class SkillLoader:
    """Discovers SKILL.md files under <layer_c_root>/skills/.

    Skills are indexed by their directory name (the name field of SkillMeta).
    Content is read eagerly on first list/get call.
    """

    def __init__(self, layer_c_root: str | Path) -> None:
        self._skills_dir = Path(layer_c_root) / "skills"
        self._meta: dict[str, SkillMeta] = {}
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        if not self._skills_dir.is_dir():
            self._loaded = True
            return
        for skill_file in sorted(self._skills_dir.rglob("SKILL.md")):
            name = skill_file.parent.name
            content = skill_file.read_text(encoding="utf-8")
            title = _extract_title(content, name)
            self._meta[name] = SkillMeta(
                name=name,
                title=title,
                file_path=skill_file.resolve(),
            )
        self._loaded = True

    def list_skills(self) -> list[SkillMeta]:
        """Return lightweight metadata for all discovered skills."""
        self._ensure_loaded()
        return list(self._meta.values())

    def get_meta(self, name: str) -> Optional[SkillMeta]:
        """Return metadata for a named skill, or None if not found."""
        self._ensure_loaded()
        return self._meta.get(name)

    def load(self, name: str) -> str:
        """Return the full content of a named skill file.

        Raises KeyError if the skill name is not found.
        """
        self._ensure_loaded()
        if name not in self._meta:
            raise KeyError(f"Skill not found: {name!r}")
        return self._meta[name].file_path.read_text(encoding="utf-8")

    def skill_names(self) -> list[str]:
        """Return all discovered skill names in discovery order."""
        self._ensure_loaded()
        return list(self._meta.keys())
