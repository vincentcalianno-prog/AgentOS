"""Abstract KnowledgeLoader base for the ACP portable engine.

Abstract base for all workflow-specific knowledge loaders.
Concrete implementations live in Layer C. Layer B engine components
depend on this interface, never on concrete loaders.

Each workflow defines its own knowledge schema (e.g. PlaybookEntry for
Workflow #1 contract redline, report config for Workflow #2 report triage).
The concrete loader for each workflow lives in the corresponding
layer_c_<deployment>/ package and subclasses this interface.

This module has zero knowledge of any schema type or deployment.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class KnowledgeLoader(ABC):
    """Abstract base for workflow-specific knowledge loaders.

    Concrete implementations live in Layer C. Layer B engine components
    depend on this interface, never on concrete loaders.
    """

    @abstractmethod
    def load(self, config_path: str) -> list:
        """Load knowledge objects from config_path and return them as a list.

        Args:
            config_path: Path to the directory or file containing knowledge
                         config for this workflow. The format and schema of
                         the returned objects are defined by the concrete
                         Layer C implementation.

        Returns:
            List of loaded knowledge objects. The concrete type depends on
            the workflow; callers that need type safety should use the
            concrete loader directly.
        """
