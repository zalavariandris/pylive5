"""Generic observable graph. No knowledge of operators or execution."""
from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Callable, Generic, Hashable, Iterable, Mapping, Protocol, Set, TypeVar

NodeT = TypeVar("NodeT", bound=Hashable)


@dataclass(eq=False, frozen=True)
class Node:
    """Convenient identity-based node. Any hashable object may also be a node."""
    label: str = ""


@dataclass(frozen=True)
class Link(Generic[NodeT]):
    source: NodeT
    target: NodeT
    inlet: str

    def __iter__(self):
        yield self.source
        yield self.target
        yield self.inlet


class GraphProtocol(Protocol[NodeT]):
    def nodes(self) -> Iterable[NodeT]: ...
    def attributes(self, node: NodeT) -> Mapping[str, object]: ...
    def in_links(self, node: NodeT) -> Iterable[Link[NodeT]]: ...
    def out_links(self, node: NodeT) -> Iterable[Link[NodeT]]: ...
    def links(self) -> Iterable[Link[NodeT]]: ...

class MutableGraphProtocol(GraphProtocol[NodeT], Protocol[NodeT]):
    def add_node(self, node: NodeT, **attributes: object) -> None: ...
    def remove_node(self, node: NodeT) -> None: ...
    def add_link(self, source: NodeT, target: NodeT, inlet: str) -> None: ...
    def remove_link(self, source: NodeT, target: NodeT, inlet: str) -> None: ...

class ObservableGraphProtocol(GraphProtocol[NodeT], Protocol[NodeT]):
    def listen(self, callback: Callable[[GraphChange[NodeT]], None]) -> Callable[[], None]:

def ancestors(graph: GraphProtocol[NodeT], node: NodeT) -> set[NodeT]:
    if node not in graph.nodes():
        raise ValueError("Node is not in graph")
    found, pending = set(), [link.source for link in graph.in_links(node)]
    while pending:
        current = pending.pop()
        if current not in found:
            found.add(current)
            pending.extend(link.source for link in graph.in_links(current))
    return found


def descendants(graph: GraphProtocol[NodeT], node: NodeT) -> set[NodeT]:
    if node not in graph.nodes():
        raise ValueError("Node is not in graph")
    found, pending = set(), [link.target for link in graph.out_links(node)]
    while pending:
        current = pending.pop()
        if current not in found:
            found.add(current)
            pending.extend(link.target for link in graph.out_links(current))
    return found


def topological_sort(graph: GraphProtocol[NodeT], root: NodeT | None = None) -> tuple[NodeT, ...]:
    if root is not None and root not in graph.nodes():
        raise ValueError("Root is not in graph")
    visited, active, order = set(), set(), []

    def visit(node: NodeT) -> None:
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

    for node in (root,) if root is not None else graph.nodes():
        visit(node)
    return tuple(order)



class Graph(Generic[NodeT]):
    """Stores node attributes and one incoming link per (target, input)."""

    def __init__(self) -> None:
        self._nodes: dict[NodeT, dict[str, object]] = {}
        self._inputs: dict[NodeT, dict[str, NodeT]] = {} # [dst, [inlet: source]]
        self._outputs: dict[NodeT, dict[NodeT, Set[str]]] = {} # [src, [dst: {in1, in2, ...}]]

    def nodes(self) -> tuple[NodeT, ...]:
        return tuple(self._nodes)

    def out_links(self, src: NodeT) -> Iterable[Link[NodeT]]:
        for dst, inlets in self._outputs[src].items():
            for inlet in inlets:
                yield Link(src, dst, inlet)

    def in_links(self, dst: NodeT) -> Iterable[Link[NodeT]]:
        for inlet, src in self._inputs[dst].items():
            yield Link(src, dst, inlet)

    def links(self) -> Iterable[Link[NodeT]]:
        for dst, inlets in self._inputs.items():
            for inlet, src in inlets.items():
                yield Link(src, dst, inlet)

    def add_node(self, node: NodeT, **attributes: object) -> None:
        if node in self._nodes:
            raise ValueError(f"Node already exists: {node!r}")
        
        self._nodes[node] = dict(attributes)
        self._outputs[node] = {}
        self._inputs[node] = {}

    def remove_node(self, node: NodeT) -> None:
        if node not in self._nodes:
            raise KeyError(node)

        for link in list(self.in_links(node)):
            self.__remove_link(link.source, link.target, link.inlet)

        for link in list(self.out_links(node)):
            self.__remove_link(link.source, link.target, link.inlet)

        del self._inputs[node]
        del self._outputs[node]
        del self._nodes[node]

    def add_link(self, source: NodeT, target: NodeT, inlet: str) -> None:
        """Add a link from source to target.inlet.
        Raises if the inlet is already connected.
        """
        if source not in self._nodes or target not in self._nodes:
            raise KeyError("Both link endpoints must exist")

        if target in self._inputs and inlet in self._inputs[target]:
            raise ValueError(f"Inlet already connected: {target!r}.{inlet!r}")

        self._inputs[target].setdefault(inlet, source)
        self._outputs[source].setdefault(target, set()).add(inlet)

    def remove_link(self, source: NodeT, target: NodeT, inlet: str) -> None:
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

    def __remove_link(self, source: NodeT, target: NodeT, inlet: str) -> None:
        """Remove a link from source to target.inlet"""
        self._inputs[target].pop(inlet, None)
        if target in self._outputs[source]:
            self._outputs[source][target].discard(inlet)
            if not self._outputs[source][target]:
                del self._outputs[source][target]

    def attributes(self, node: NodeT) -> Mapping[str, object]:
        return MappingProxyType(self._nodes[node])
    
    def set(self, node: NodeT, **attributes: object) -> None:
        if node not in self._nodes:
            raise KeyError(node)
        
        if not attributes:
            return

        self._nodes[node].update(attributes)

    def unset(self, node: NodeT, name: str) -> None:
        if node not in self._nodes:
            raise KeyError(node)

        del self._nodes[node][name]
