"""Latest valid node outputs, with validity supplied by the invalidator."""

from typing import Hashable, Iterable, Iterator, Mapping, Any
from dataclasses import dataclass

from .graph import NodeRef


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
        self._context_entries: dict[
            tuple[NodeRef, Hashable],
            _CacheEntry,
        ] = {}

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
        for key in tuple(self._context_entries):
            if key[0] == node:
                del self._context_entries[key]

    def invalidate(self, nodes: Iterable[NodeRef]) -> None:
        """Forget affected nodes; the caller supplies downstream nodes too."""
        # A snapshot also permits cache.invalidate(cache).
        for node in tuple(nodes):
            self.remove(node)

    def clear(self) -> None:
        """Forget all ordinary and contextual results."""
        self._entries.clear()
        self._context_entries.clear()

    def _has_context(self, node: NodeRef, context: Hashable) -> bool:
        return (node, context) in self._context_entries

    def _get_context(self, node: NodeRef, context: Hashable) -> Any:
        """Return a cached contextual result; raise KeyError if absent."""
        return self._context_entries[node, context].value

    def save_context(
        self,
        node: NodeRef,
        context: Hashable,
        value: Any,
        *,
        duration_seconds: float | None = None,
    ) -> None:
        """Store a contextual result after execution is accepted."""
        self._context_entries[node, context] = _CacheEntry(
            value=value,
            duration_seconds=duration_seconds,
        )

    def context_duration_seconds(
        self,
        node: NodeRef,
        context: Hashable,
    ) -> float | None:
        return self._context_entries[node, context].duration_seconds

    def contextual_outputs(
        self,
    ) -> dict[tuple[NodeRef, Hashable], Any]:
        """Copy the contextual lookup table; stored values remain borrowed."""
        return {
            key: entry.value
            for key, entry in self._context_entries.items()
        }