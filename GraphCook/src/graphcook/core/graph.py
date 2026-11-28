"""Graph structure with dictionary node data; no evaluation or observation."""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Generic, Hashable, Iterable, Mapping, Protocol, Set
from typing_extensions import TypeVar
from typing import NamedTuple

NodeKeyT = TypeVar("NodeKeyT", bound=Hashable)
NodeValueT = TypeVar("NodeValueT", bound=Mapping[str, object])
# TypedDict is compatible with Mapping, but not with mutable dict annotations.
# Mapping keys are invariant; Any allows schemas with different key types.
# Storage validates actual dictionaries at runtime and exposes read-only views.


@dataclass(eq=False, frozen=True)
class Node:
    """Convenient identity-based node. Any hashable object may also be a node."""
    label: str = ""

AttributesT = TypeVar(
    "AttributesT",
    bound=Mapping[str, object],
    default=Mapping[str, object],
)

class Link(Generic[NodeKeyT], NamedTuple):
    source: NodeKeyT
    target: NodeKeyT
    inlet: str



class GraphProtocol(Protocol[NodeKeyT]):
    def nodes(self) -> Iterable[NodeKeyT]: ...
    def attributes(self, node: NodeKeyT) -> Mapping[str, object]: ...
    def in_links(self, node: NodeKeyT) -> Iterable[Link[NodeKeyT]]: ...
    def out_links(self, node: NodeKeyT) -> Iterable[Link[NodeKeyT]]: ...
    def links(self) -> Iterable[Link[NodeKeyT]]: ...


class MutableGraphProtocol(
    GraphProtocol[NodeKeyT], Protocol[NodeKeyT],
):
    def add_node(self, node: NodeKeyT, **attributes: object) -> None: ...
    def remove_node(self, node: NodeKeyT) -> None: ...
    def add_link(self, source: NodeKeyT, target: NodeKeyT, inlet: str) -> None: ...
    def remove_link(self, source: NodeKeyT, target: NodeKeyT, inlet: str) -> None: ...
    def set(self, node: NodeKeyT, name: str, value: object) -> None: ...
    def update(self, node: NodeKeyT, /, **attributes: object) -> None: ...
    def unset(self, node: NodeKeyT, name: str) -> None: ...


def ancestors(graph: GraphProtocol[NodeKeyT], node: NodeKeyT) -> set[NodeKeyT]:
    if node not in graph.nodes():
        raise ValueError("Node is not in graph")
    found, pending = set(), [link.source for link in graph.in_links(node)]
    while pending:
        current = pending.pop()
        if current not in found:
            found.add(current)
            pending.extend(link.source for link in graph.in_links(current))
    return found


def descendants(graph: GraphProtocol[NodeKeyT], node: NodeKeyT) -> set[NodeKeyT]:
    if node not in graph.nodes():
        raise ValueError("Node is not in graph")
    found, pending = set(), [link.target for link in graph.out_links(node)]
    while pending:
        current = pending.pop()
        if current not in found:
            found.add(current)
            pending.extend(link.target for link in graph.out_links(current))
    return found


def topological_sort(graph: GraphProtocol[NodeKeyT], *roots: NodeKeyT) -> tuple[NodeKeyT, ...]:
    nodes = tuple(graph.nodes())
    known_nodes = set(nodes)
    for root in roots:
        if root not in known_nodes:
            raise ValueError(f"Root is not in graph: {root!r}")

    visited: set[NodeKeyT] = set()
    active: set[NodeKeyT] = set()
    order: list[NodeKeyT] = []

    def visit(node: NodeKeyT) -> None:
        if node in active:
            raise ValueError("Graph contains a cycle")
        if node in visited:
            return
        active.add(node)
        for link in graph.in_links(node):
            visit(link.source)
        active.remove(node)
        visited.add(node)
        order.append(node)

    for node in roots if roots else nodes:
        visit(node)

    return tuple(order)


class Graph(Generic[NodeKeyT, NodeValueT]):
    """Store node dictionaries and one incoming link per (target, inlet).

    Incoming dictionaries are shallow-copied. attributes() returns a live,
    read-only mapping; edit attributes through set(), update(), and unset(). Nested
    values remain shared and may be mutable. dict describes input data,
    including TypedDict schemas; per-key edits do not validate that schema.
    """

    def __init__(self) -> None:
        self._nodes: dict[NodeKeyT, Mapping[str, object]] = {}
        self._inputs: dict[NodeKeyT, dict[str, NodeKeyT]] = {} # [dst, [inlet: source]]
        self._outputs: dict[NodeKeyT, dict[NodeKeyT, Set[str]]] = {} # [src, [dst: {in1, in2, ...}]]

    def nodes(self) -> tuple[NodeKeyT, ...]:
        return tuple(self._nodes)

    def out_links(self, node: NodeKeyT) -> Iterable[Link[NodeKeyT]]:
        for dst, inlets in self._outputs[node].items():
            for inlet in inlets:
                yield Link(node, dst, inlet)

    def in_links(self, node: NodeKeyT) -> Iterable[Link[NodeKeyT]]:
        for inlet, src in self._inputs[node].items():
            yield Link(src, node, inlet)

    def links(self) -> Iterable[Link[NodeKeyT]]:
        for dst, inlets in self._inputs.items():
            for inlet, src in inlets.items():
                yield Link(src, dst, inlet)

    def add_node(self, node: NodeKeyT, **attributes: object) -> None:
        """Add a node with one positional dictionary or keyword attributes.

        Passing no data creates an empty dictionary. Positional data keeps
        legacy keyword names such as 'data' available as ordinary attributes.
        """
        if node in self._nodes:
            raise ValueError(f"Node already exists: {node!r}")

        self._nodes[node] = attributes
        self._outputs[node] = {}
        self._inputs[node] = {}

    def remove_node(self, node: NodeKeyT) -> None:
        if node not in self._nodes:
            raise KeyError(node)

        for link in list(self.in_links(node)):
            self.__remove_link(link.source, link.target, link.inlet)

        for link in list(self.out_links(node)):
            self.__remove_link(link.source, link.target, link.inlet)

        del self._inputs[node]
        del self._outputs[node]
        del self._nodes[node]

    def add_link(self, source: NodeKeyT, target: NodeKeyT, inlet: str) -> None:
        """Add a link from source to target.inlet.
        Raises if the inlet is already connected.
        """
        if source not in self._nodes or target not in self._nodes:
            raise KeyError("Both link endpoints must exist")

        if target in self._inputs and inlet in self._inputs[target]:
            raise ValueError(f"Inlet already connected: {target!r}.{inlet!r}")

        self._inputs[target].setdefault(inlet, source)
        self._outputs[source].setdefault(target, set()).add(inlet)

    def remove_link(self, source: NodeKeyT, target: NodeKeyT, inlet: str) -> None:
        """Remove a link from source to target.inlet.
        Raises if the link does not exist.
        """
        if source not in self._outputs:
            raise KeyError(f"Source node not found: {source!r}")
        
        if target not in self._inputs:
            raise KeyError(f"Target node not found: {target!r}")

        if inlet not in self._inputs[target]:
            raise KeyError(f"Inlet not found: {target!r}.{inlet!r}")
            
        if self._inputs[target][inlet] != source:
            raise KeyError(f"Link not found: {source!r} -> {target!r}.{inlet!r}")

        self.__remove_link(source, target, inlet)

    def __remove_link(self, source: NodeKeyT, target: NodeKeyT, inlet: str) -> None:
        """Remove a link from source to target.inlet"""
        self._inputs[target].pop(inlet, None)
        if target in self._outputs[source]:
            self._outputs[source][target].discard(inlet)
            if not self._outputs[source][target]:
                del self._outputs[source][target]

    def attributes(self, node: NodeKeyT) -> NodeValueT:
        """Return a live, shallow read-only view of the node's attributes."""
        return MappingProxyType(self._nodes[node])

    def set_attribute(self, node: NodeKeyT, name: str, value: object) -> None:
        """Assign one attribute, preserving the node's other attributes."""
        self.update_attributes(node, **{name: value})

    def update_attributes(self, node: NodeKeyT, /, **attributes: object) -> None:
        """Merge keyword attributes into the node's existing dictionary."""
        self._nodes[node].update(attributes)

    def unset_attribute(self, node: NodeKeyT, name: str) -> None:
        """Remove one attribute; missing nodes or keys raise KeyError."""
        del self._nodes[node][name]
