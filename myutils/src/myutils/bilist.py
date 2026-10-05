from collections.abc import Hashable, Iterator, Mapping
from types import MappingProxyType
from typing import Generic, TypeVar


T = TypeVar("T", bound=Hashable)


class BiList(Generic[T]):
    """
    A mutable list of unique hashable items with O(1) average lookup
    in both directions: index -> item and item -> index.

    Arbitrary insertion and removal are O(n).

    Example:
        >>> items = BiList[str]()
        >>> items.append("a")
        >>> items.append("b")
        >>> items.insert(1, "c")
        >>>
        >>> items[1]
        'c'
        >>> items.inverse["c"]
        1
        >>> items.index("b")
        2
        >>>
        >>> items.pop(1)
        'c'
        >>> items.inverse["b"]
        1
    """

    def __init__(self) -> None:
        self._items: list[T] = []
        self._index_by_item: dict[T, int] = {}
        self._inverse: Mapping[T, int] = MappingProxyType(
            self._index_by_item
        )

    @property
    def inverse(self) -> Mapping[T, int]:
        return self._inverse

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self) -> Iterator[T]:
        return iter(self._items)

    def __getitem__(self, idx: int) -> T:
        return self._items[idx]

    def __contains__(self, item: object) -> bool:
        return item in self._index_by_item

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self._items!r})"

    def append(self, item: T) -> None:
        if item in self._index_by_item:
            raise ValueError(f"{item!r} is already in BiList")

        self._index_by_item[item] = len(self._items)
        self._items.append(item)

    def insert(self, idx: int, item: T) -> None:
        if item in self._index_by_item:
            raise ValueError(f"{item!r} is already in BiList")

        # Normalize idx according to list.insert() semantics.
        n = len(self._items)
        if idx < 0:
            idx = max(0, n + idx)
        else:
            idx = min(idx, n)

        self._items.insert(idx, item)

        # Everything from idx onward may have moved.
        for i in range(idx, len(self._items)):
            self._index_by_item[self._items[i]] = i

    def pop(self, idx: int = -1) -> T:
        # Access first so invalid indices raise before we mutate anything.
        item = self._items[idx]

        # The inverse gives us the normalized non-negative index.
        idx = self._index_by_item[item]

        self._items.pop(idx)
        del self._index_by_item[item]

        # Everything after idx shifted left.
        for i in range(idx, len(self._items)):
            self._index_by_item[self._items[i]] = i

        return item

    def clear(self) -> None:
        self._items.clear()
        self._index_by_item.clear()