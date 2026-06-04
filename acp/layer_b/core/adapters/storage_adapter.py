"""Abstract interface for document storage backends.

Implementations live in layer_c_antora/adapters/ (production) or
layer_b/tests/fixtures/ (synthetic). layer_b code never imports concrete adapters.

Per Implementation Guide Section 3: every external integration in layer_b is
mediated by an abstract interface. The StorageAdapter decouples Agent 2
(Document Extraction) from any specific storage provider.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class StoredFile:
    """Metadata returned after a successful store operation."""
    path: str           # canonical path at which the file was stored
    size_bytes: int     # byte count of the stored content


class StorageAdapter(ABC):
    """Write, read, and existence-check interface for a generic document store.

    Deliberately narrow: Agent 2 needs to check existence, persist files, and
    retrieve them. Path construction is the caller's responsibility.
    """

    @abstractmethod
    def exists(self, path: str) -> bool:
        """Return True if a file exists at the given path."""
        ...

    @abstractmethod
    def store(self, path: str, content: bytes) -> StoredFile:
        """Persist content at the given path and return metadata.

        Callers are responsible for constructing unique timestamped paths.
        Implementations must not silently overwrite existing files.

        Args:
            path: Full canonical path in the provider's namespace.
            content: Raw file bytes to persist.

        Returns:
            StoredFile with the confirmed path and stored byte count.

        Raises:
            FileExistsError: If a file already exists at path.
            OSError: On any storage-layer failure.
        """
        ...

    @abstractmethod
    def retrieve(self, path: str) -> bytes:
        """Return the raw bytes stored at the given path.

        Raises:
            FileNotFoundError: If no file exists at path.
        """
        ...
