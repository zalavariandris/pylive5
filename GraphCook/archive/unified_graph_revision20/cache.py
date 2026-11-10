"""Storage protocol and in-memory cache for node results."""
from __future__ import annotations

from collections.abc import Hashable, Iterator, Mapping
from typing import Protocol, TypeVar


ValueT = TypeVar("ValueT")
KeyT = TypeVar("KeyT", bound=Hashable)


class CacheProtocol(Protocol[KeyT, ValueT]):
    def __getitem__(self, key: KeyT) -> ValueT: ...
    def __iter__(self) -> Iterator[KeyT]: ...
    def __len__(self) -> int: ...
    def save(self, key: KeyT, value: ValueT) -> None: ...
    def remove(self, key: KeyT) -> None: ...
    def clear(self) -> None: ...


class MemoryCache(Mapping[KeyT, ValueT]):
    def __init__(self) -> None:
        self._items: dict[KeyT, ValueT] = {}

    def __getitem__(self, key: KeyT) -> ValueT:
        return self._items[key]

    def __iter__(self) -> Iterator[KeyT]:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def save(self, key: KeyT, value: ValueT) -> None:
        self._items[key] = value

    def remove(self, key: KeyT) -> None:
        self._items.pop(key, None)

    def clear(self) -> None:
        self._items.clear()
