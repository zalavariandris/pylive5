from abc import abstractmethod
from collections.abc import Hashable, Mapping


class AbstractCache[K: Hashable, V](Mapping[K, V]):
    @abstractmethod
    def save(self, key: K, value: V) -> None:
        ...

    @abstractmethod
    def remove(self, key: K) -> None:
        ...

    @abstractmethod
    def clear(self) -> None:
        ...

    def snapshot(self) -> dict[K, V]:
        return dict(self)
    