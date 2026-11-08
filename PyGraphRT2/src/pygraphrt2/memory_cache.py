"""In-memory storage with explicit writes and shallow snapshots."""
from .abstract_cache import AbstractCache
from collections.abc import Hashable, Iterator, Mapping


class MemoryCache[K: Hashable, V](AbstractCache[K, V]):
    def __init__(self, initial: Mapping[K, V] | None = None) -> None:
        self._entries: dict[K, V] = dict(initial) if initial is not None else {}

    def __getitem__(self, key: K) -> V:
        return self._entries[key]

    def __iter__(self) -> Iterator[K]:
        return iter(self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    def save(self, key: K, value: V) -> None:
        """Store or replace a value, including None."""
        self._entries[key] = value

    def remove(self, key: K) -> None:
        """Forget a key if present."""
        self._entries.pop(key, None)

    def clear(self) -> None:
        self._entries.clear()

    def snapshot(self) -> dict[K, V]:
        """Copy the lookup table while retaining references to its values."""
        return dict(self._entries)
