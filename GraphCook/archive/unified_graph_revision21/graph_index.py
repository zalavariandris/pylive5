"""Derived, explicitly updated index of a node attribute's hashable values."""
from __future__ import annotations

from typing import Generic, Hashable, TypeVar

from .graph import GraphChange, GraphProtocol, NodeT
from myutils.relations import ManyToOneRelation

ValueT = TypeVar("ValueT", bound=Hashable)


class GraphAttributeIndex(Generic[NodeT, ValueT]):
    """Index nodes by a non-None, hashable attribute value of the requested type.

    The graph is the source of truth; this is only a derived reverse lookup.

    The owner calls update(change) after a graph mutation has been emitted.
    The index deliberately does not subscribe on its own, so the owner can
    update it before acting on the same change (e.g. cache invalidation).
    """

    def __init__(self, graph: GraphProtocol[NodeT], attribute: str,
                 value_type: type[ValueT]) -> None:
        self.graph = graph
        self.attribute = attribute
        self.value_type = value_type
        self._relation = ManyToOneRelation[NodeT, ValueT]()
        for node in graph.nodes():
            self._sync(node)

    def value_of(self, node: NodeT) -> ValueT | None:
        return self._relation.parent_of(node)

    def nodes_with(self, value: ValueT) -> frozenset[NodeT]:
        return self._relation.children_of(value)

    def update(self, change: GraphChange[NodeT]) -> None:
        # The graph has already applied the mutation by the time it emits.
        for node in change.nodes.removed:
            self._remove(node)
        for node in change.nodes.added:
            self._sync(node)
        for node, changes in change.attributes.items():
            if node in change.nodes.removed:
                continue
            if (self.attribute in changes.added
                    or self.attribute in changes.removed
                    or self.attribute in changes.changed):
                self._sync(node)

    def _remove(self, node: NodeT) -> None:
        previous = self._relation.parent_of(node)
        if previous is not None:
            self._relation.delete(node, previous)

    def _sync(self, node: NodeT) -> None:
        value = self.graph.attributes(node).get(self.attribute)
        previous = self._relation.parent_of(node)
        if value is None or not isinstance(value, self.value_type):
            self._remove(node)
        elif previous != value:
            self._relation.set(node, value)
