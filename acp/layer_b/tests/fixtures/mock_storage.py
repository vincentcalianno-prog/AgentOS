"""MockStorageAdapter — synthetic storage fixture for layer_b tests.

Per Implementation Guide Section 7.1: synthetic fixtures only.

Provides:
    MockStorageAdapter  — in-memory StorageAdapter for unit and integration tests
"""

from __future__ import annotations

from acp.layer_b.core.adapters.storage_adapter import StorageAdapter, StoredFile


class MockStorageAdapter(StorageAdapter):
    """Configurable in-memory StorageAdapter for tests.

    Usage:
        storage = MockStorageAdapter()
        stored = storage.store("root/mepa/acme/round_1/20260101T000000Z_att-001.bin", b"data")
        assert storage.exists(stored.path)
        assert storage.retrieve(stored.path) == b"data"
    """

    def __init__(self) -> None:
        self._files: dict[str, bytes] = {}

    @property
    def stored_paths(self) -> set[str]:
        """All paths currently held in the mock store."""
        return set(self._files.keys())

    @property
    def stored_data(self) -> dict[str, bytes]:
        """Direct access to the backing store for test manipulation (e.g. pop to simulate missing files)."""
        return self._files

    def exists(self, path: str) -> bool:
        return path in self._files

    def store(self, path: str, content: bytes) -> StoredFile:
        if path in self._files:
            raise FileExistsError(f"File already exists at path: {path!r}")
        self._files[path] = content
        return StoredFile(path=path, size_bytes=len(content))

    def retrieve(self, path: str) -> bytes:
        if path not in self._files:
            raise FileNotFoundError(f"No file at path: {path!r}")
        return self._files[path]
