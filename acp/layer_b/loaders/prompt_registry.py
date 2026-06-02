"""Prompt template registry for the ACP negotiation engine.

Loads prompt template files from <layer_c_root>/prompts/.
Templates are keyed by filename stem (without extension).
Supported file types: .txt, .md.

A missing prompts/ directory yields an empty registry rather than raising.
Duplicate stems (e.g. both counter_proposal.txt and counter_proposal.md)
raise ValueError at load time.

Usage::

    registry = PromptRegistry(layer_c_root)
    template = registry.get("counter_proposal_draft")
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


class PromptNotFoundError(KeyError):
    """Raised by PromptRegistry.get() when the key is not registered."""


class PromptRegistry:
    """Registry of prompt templates from a deployment's prompts/ directory.

    Keys are filename stems.  Templates are loaded eagerly on first access.
    The registry is read-only after loading.
    """

    _SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({".txt", ".md"})

    def __init__(self, layer_c_root: str | Path) -> None:
        self._prompts_dir = Path(layer_c_root) / "prompts"
        self._templates: dict[str, str] = {}
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        if not self._prompts_dir.is_dir():
            self._loaded = True
            return
        for path in sorted(self._prompts_dir.iterdir()):
            if path.is_file() and path.suffix in self._SUPPORTED_EXTENSIONS:
                key = path.stem
                if key in self._templates:
                    raise ValueError(
                        f"Duplicate prompt key '{key}': {path} conflicts with"
                        " a previously loaded file (check for .txt/.md duplicates)"
                    )
                self._templates[key] = path.read_text(encoding="utf-8")
        self._loaded = True

    def get(self, key: str) -> str:
        """Return the template for key.

        Raises PromptNotFoundError if the key is not registered.
        """
        self._ensure_loaded()
        if key not in self._templates:
            raise PromptNotFoundError(
                f"Prompt key not found: {key!r}. "
                f"Available keys: {sorted(self._templates)}"
            )
        return self._templates[key]

    def get_or_none(self, key: str) -> Optional[str]:
        """Return the template for key, or None if not found."""
        self._ensure_loaded()
        return self._templates.get(key)

    def list_keys(self) -> list[str]:
        """Return all registered template keys in sorted order."""
        self._ensure_loaded()
        return sorted(self._templates.keys())

    def has(self, key: str) -> bool:
        """Return True if the key is registered."""
        self._ensure_loaded()
        return key in self._templates
