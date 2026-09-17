from typing import Any
from dataclasses import dataclass
from .node_rt import NodeRT

@dataclass(frozen=True)
class CacheEntry:
    fingerprint: tuple
    value: Any
    revision: int


class MemoryCache:
    """Stores the latest result for each node."""

    def __init__(self):
        self._entries: dict[NodeRT, CacheEntry] = {}
        self._revision = 0

    def lookup(self, node: NodeRT, fingerprint: tuple) -> CacheEntry | None:
        entry = self._entries.get(node)
        if entry is not None and entry.fingerprint == fingerprint:
            return entry
        return None

    def save(self, node: NodeRT, fingerprint: tuple, value: Any) -> CacheEntry:
        self._revision += 1
        entry = CacheEntry(fingerprint, value, self._revision)
        self._entries[node] = entry
        return entry

    def remove(self, node: NodeRT) -> None:
        self._entries.pop(node, None)

    def clear(self) -> None:
        self._entries.clear()
