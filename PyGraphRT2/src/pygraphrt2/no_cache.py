from collections.abc import Hashable, Iterator

from .abstract_cache import AbstractCache


class NoCache[K: Hashable, V](AbstractCache[K, V]):
    """Accept writes without retaining results."""

    def __getitem__(self, key: K) -> V:
        raise KeyError(key)

    def __iter__(self) -> Iterator[K]:
        return iter(())

    def __len__(self) -> int:
        return 0

    def save(self, key: K, value: V) -> None:
        pass

    def remove(self, key: K) -> None:
        pass

    def clear(self) -> None:
        pass