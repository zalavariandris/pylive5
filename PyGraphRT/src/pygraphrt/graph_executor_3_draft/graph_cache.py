"""Latest valid node outputs, with validity supplied by the invalidator."""

from collections.abc import Iterable, Iterator, Mapping
from typing import Any

from ..graph_definition_rt import NodeRef


class GraphCache(Mapping[NodeRef, Any]):
    """Store outputs for one graph without fingerprints or signal connections.

    The evaluator owns invalidation and writes on its owning thread. Membership
    means an output is valid, including when its value is ``None``. Values are
    borrowed: callers must not mutate stored objects. Plan preparation copies
    the values needed by a worker before dispatch.
    """

    def __init__(self) -> None:
        self._outputs: dict[NodeRef, Any] = {}

    def __getitem__(self, node: NodeRef) -> Any:
        return self._outputs[node]

    def __iter__(self) -> Iterator[NodeRef]:
        return iter(self._outputs)

    def __len__(self) -> int:
        return len(self._outputs)

    def save(self, node: NodeRef, value: Any) -> None:
        """Replace a node's output after its execution has been accepted."""
        self._outputs[node] = value

    def remove(self, node: NodeRef) -> None:
        """Forget a node's output if present."""
        self._outputs.pop(node, None)

    def invalidate(self, nodes: Iterable[NodeRef]) -> None:
        """Forget affected nodes; the caller supplies downstream nodes too."""
        # A snapshot also permits cache.invalidate(cache).
        for node in tuple(nodes):
            self.remove(node)

    def clear(self) -> None:
        self._outputs.clear()
