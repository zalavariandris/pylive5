"""Latest valid node outputs, with validity supplied by the invalidator."""

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from .graph_definition_rt import NodeRef


@dataclass(frozen=True)
class _CacheEntry:
    value: Any
    duration_seconds: float | None


class GraphCache(Mapping[NodeRef, Any]):
    """Store outputs for one graph without fingerprints or signal connections.

    The evaluator owns invalidation and writes on its owning thread. Membership
    means an output is valid, including when its value is ``None``. Values are
    borrowed: callers must not mutate stored objects. Plan preparation copies
    the values needed by a worker before dispatch. Each entry also retains the
    duration of the computation that produced its value.
    """

    def __init__(self) -> None:
        self._entries: dict[NodeRef, _CacheEntry] = {}

    def __getitem__(self, node: NodeRef) -> Any:
        return self._entries[node].value

    def __iter__(self) -> Iterator[NodeRef]:
        return iter(self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    def duration_seconds(self, node: NodeRef) -> float | None:
        """Return the original execution duration for a cached node."""
        return self._entries[node].duration_seconds

    def save(
        self,
        node: NodeRef,
        value: Any,
        *,
        duration_seconds: float | None = None,
    ) -> None:
        """Replace a node's output and timing after execution is accepted."""
        self._entries[node] = _CacheEntry(value, duration_seconds)

    def remove(self, node: NodeRef) -> None:
        """Forget a node's output if present."""
        self._entries.pop(node, None)

    def invalidate(self, nodes: Iterable[NodeRef]) -> None:
        """Forget affected nodes; the caller supplies downstream nodes too."""
        # A snapshot also permits cache.invalidate(cache).
        for node in tuple(nodes):
            self.remove(node)

    def clear(self) -> None:
        self._entries.clear()
