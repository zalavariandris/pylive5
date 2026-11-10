"""Generic observable graph. No knowledge of operators or execution."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Generic, Hashable, Mapping, Protocol, TypeVar
from types import MappingProxyType

NodeT = TypeVar("NodeT", bound=Hashable)
MISSING = object()


@dataclass(eq=False, frozen=True)
class Node:
    """Convenient identity-based node. Any hashable object may also be a node."""
    label: str = ""


@dataclass(frozen=True)
class Link(Generic[NodeT]):
    source: NodeT
    target: NodeT
    input: str


@dataclass(frozen=True)
class AttributeChange:
    name: str
    old: object = MISSING
    new: object = MISSING


@dataclass(frozen=True)
class NodeChange(Generic[NodeT]):
    node: NodeT
    attributes: tuple[AttributeChange, ...]


@dataclass(frozen=True)
class NodeChanges(Generic[NodeT]):
    added: tuple[NodeT, ...] = ()
    removed: tuple[NodeT, ...] = ()
    changed: tuple[NodeChange[NodeT], ...] = ()


@dataclass(frozen=True)
class LinkChanges(Generic[NodeT]):
    added: tuple[Link[NodeT], ...] = ()
    removed: tuple[Link[NodeT], ...] = ()


@dataclass(frozen=True)
class GraphChange(Generic[NodeT]):
    nodes: NodeChanges[NodeT] = field(default_factory=NodeChanges)
    links: LinkChanges[NodeT] = field(default_factory=LinkChanges)


class GraphProtocol(Protocol[NodeT]):
    def nodes(self) -> tuple[NodeT, ...]: ...
    def links(self) -> tuple[Link[NodeT], ...]: ...
    def attributes(self, node: NodeT) -> Mapping[str, object]: ...
    def in_links(self, node: NodeT) -> tuple[Link[NodeT], ...]: ...
    def out_links(self, node: NodeT) -> tuple[Link[NodeT], ...]: ...


class Graph(Generic[NodeT]):
    """Stores node attributes and one incoming link per (target, input)."""

    def __init__(self) -> None:
        self._attributes: dict[NodeT, dict[str, object]] = {}
        self._inputs: dict[tuple[NodeT, str], NodeT] = {}

    def nodes(self) -> tuple[NodeT, ...]:
        return tuple(self._attributes)

    def links(self) -> tuple[Link[NodeT], ...]:
        return tuple(Link(source, target, name)
                     for (target, name), source in self._inputs.items())

    def attributes(self, node: NodeT) -> Mapping[str, object]:
        return MappingProxyType(self._attributes[node])

    def in_links(self, node: NodeT) -> tuple[Link[NodeT], ...]:
        return tuple(Link(source, target, name)
                     for (target, name), source in self._inputs.items()
                     if target == node)

    def out_links(self, node: NodeT) -> tuple[Link[NodeT], ...]:
        return tuple(Link(source, target, name)
                     for (target, name), source in self._inputs.items()
                     if source == node)

    def add(self, node: NodeT, **attributes: object) -> None:
        if node in self._attributes:
            raise ValueError(f"Node already exists: {node!r}")
        self._attributes[node] = dict(attributes)
        self._emit(GraphChange(nodes=NodeChanges(added=(node,))))

    def set(self, node: NodeT, **attributes: object) -> None:
        current = self._attributes[node]
        changes = tuple(AttributeChange(name, current.get(name, MISSING), value)
                        for name, value in attributes.items())
        if not changes:
            return
        current.update(attributes)
        self._emit(GraphChange(nodes=NodeChanges(changed=(NodeChange(node, changes),))))

    def unset(self, node: NodeT, name: str) -> None:
        old = self._attributes[node].pop(name)
        self._emit(GraphChange(nodes=NodeChanges(
            changed=(NodeChange(node, (AttributeChange(name, old, MISSING),)),))))

    def remove(self, node: NodeT) -> None:
        if node not in self._attributes:
            raise KeyError(node)
        removed = tuple(link for link in self.links()
                        if link.source == node or link.target == node)
        for link in removed:
            del self._inputs[(link.target, link.input)]
        del self._attributes[node]
        self._emit(GraphChange(nodes=NodeChanges(removed=(node,)),
                               links=LinkChanges(removed=removed)))

    def add_link(self, source: NodeT, target: NodeT, input: str) -> None:
        if source not in self._attributes or target not in self._attributes:
            raise KeyError("Both link endpoints must exist")
        key = (target, input)
        old = self._inputs.get(key, MISSING)
        if old is not MISSING and old == source:
            return
        self._inputs[key] = source
        removed = () if old is MISSING else (Link(old, target, input),)
        self._emit(GraphChange(links=LinkChanges(
            added=(Link(source, target, input),), removed=removed)))

    def remove_link(self, target: NodeT, input: str) -> None:
        source = self._inputs.pop((target, input))
        self._emit(GraphChange(links=LinkChanges(
            removed=(Link(source, target, input),))))

    def snapshot(self) -> Graph[NodeT]:
        """Copy the graph tables; attribute values and node objects remain shared."""
        copy = Graph[NodeT]()
        copy._attributes = {node: attrs.copy() for node, attrs in self._attributes.items()}
        copy._inputs = self._inputs.copy()
        return copy

    def _emit(self, change: GraphChange[NodeT]) -> None:
        pass


class ObservableGraph(Graph[NodeT]):
    def __init__(self) -> None:
        super().__init__()
        self._listeners: list[Callable[[GraphChange[NodeT]], None]] = []

    def listen(self, callback: Callable[[GraphChange[NodeT]], None]) -> Callable[[], None]:
        self._listeners.append(callback)
        def unsubscribe() -> None:
            self._listeners.remove(callback)
        return unsubscribe

    def _emit(self, change: GraphChange[NodeT]) -> None:
        for callback in tuple(self._listeners):
            callback(change)
