"""Generic DAG structure, traversal algorithms, and observable graph changes."""
from __future__ import annotations

from collections.abc import Callable, Hashable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Generic, Protocol, TypeVar

NodeT = TypeVar("NodeT", bound=Hashable)

# --- Generic graph ---------------------------------------------------------

@dataclass(frozen=True)
class Link(Generic[NodeT]):
    source: NodeT
    target: NodeT
    input: str


class GraphProtocol(Protocol[NodeT]):
    def nodes(self) -> tuple[NodeT, ...]: ...
    def links(self) -> tuple[Link[NodeT], ...]: ...
    def attributes(self, node: NodeT) -> Mapping[str, Any]: ...
    def in_links(self, node: NodeT) -> tuple[Link[NodeT], ...]: ...
    def out_links(self, node: NodeT) -> tuple[Link[NodeT], ...]: ...


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
    """Mutable DAG. Attributes and named input links are independent."""

    def __init__(self) -> None:
        self._attributes: dict[NodeT, Mapping[str, Any]] = {}
        self._inputs: dict[NodeT, Mapping[str, NodeT]] = {}
        self._dependents: dict[NodeT, set[NodeT]] = {}

    def nodes(self) -> tuple[NodeT, ...]:
        return tuple(self._attributes)

    def links(self) -> tuple[Link[NodeT], ...]:
        return tuple(link for node in self.nodes() for link in self.in_links(node))

    def attributes(self, node: NodeT) -> Mapping[str, Any]:
        self._require(node)
        return self._attributes[node]

    def in_links(self, node: NodeT) -> tuple[Link[NodeT], ...]:
        self._require(node)
        return tuple(Link(source, node, name) for name, source in self._inputs[node].items())

    def out_links(self, node: NodeT) -> tuple[Link[NodeT], ...]:
        self._require(node)
        return tuple(
            Link(node, target, name)
            for target in self._dependents[node]
            for name, source in self._inputs[target].items()
            if source == node
        )

    def _require(self, node: NodeT) -> None:
        if node not in self._attributes:
            raise ValueError("Node is not in graph")

    def add(self, node: NodeT, **attributes: Any) -> NodeT:
        if node in self._attributes:
            raise ValueError("Node already in graph")
        self._attributes[node] = MappingProxyType(dict(attributes))
        self._inputs[node] = MappingProxyType({})
        self._dependents[node] = set()
        return node

    def set(self, node: NodeT, **attributes: Any) -> None:
        self._require(node)
        if attributes:
            self._attributes[node] = MappingProxyType({**self._attributes[node], **attributes})

    def unset(self, node: NodeT, *names: str) -> None:
        self._require(node)
        record = dict(self._attributes[node])
        for name in names:
            del record[name]
        if names:
            self._attributes[node] = MappingProxyType(record)

    def add_link(self, source: NodeT, target: NodeT, input: str) -> None:
        self._require(source)
        self._require(target)
        record = dict(self._inputs[target])
        old = record.get(input)
        if old == source:
            return
        if source == target or source in descendants(self, target):
            raise ValueError("Link would create a cycle")
        record[input] = source
        self._inputs[target] = MappingProxyType(record)
        if old is not None and old not in record.values():
            self._dependents[old].discard(target)
        self._dependents[source].add(target)

    def remove_link(self, source: NodeT, target: NodeT, input: str) -> None:
        self._require(target)
        if input not in self._inputs[target] or self._inputs[target][input] != source:
            raise ValueError("Link does not exist")
        record = dict(self._inputs[target])
        del record[input]
        self._inputs[target] = MappingProxyType(record)
        if source not in record.values():
            self._dependents[source].discard(target)

    def remove(self, node: NodeT) -> None:
        self._require(node)
        for target in tuple(self._dependents[node]):
            self._inputs[target] = MappingProxyType({
                name: source for name, source in self._inputs[target].items() if source != node
            })
        for source in set(self._inputs[node].values()):
            self._dependents[source].discard(node)
        del self._attributes[node], self._inputs[node], self._dependents[node]


# --- Observation -----------------------------------------------------------

class _Missing:
    def __repr__(self) -> str:
        return "MISSING"


MISSING = _Missing()


@dataclass(frozen=True)
class AttributeChange:
    name: str
    old: Any
    new: Any


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


def _same(a: Any, b: Any) -> bool:
    if a is b:
        return True
    if a is MISSING or b is MISSING:
        return False
    try:
        result = a == b
        return result if isinstance(result, bool) else False
    except (ValueError, TypeError):
        return False


def _attribute_changes(node: NodeT, before: Mapping[str, Any], after: Mapping[str, Any]) -> tuple[NodeChange[NodeT], ...]:
    changes = tuple(
        AttributeChange(name, before.get(name, MISSING), after.get(name, MISSING))
        for name in dict.fromkeys((*before, *after))
        if not _same(before.get(name, MISSING), after.get(name, MISSING))
    )
    return (NodeChange(node, changes),) if changes else ()


class ObservableGraph(Graph[NodeT]):
    """Emit post-edit changes by overriding public methods."""

    def __init__(self) -> None:
        super().__init__()
        self._listeners: list[Callable[[GraphChange[NodeT]], None]] = []

    def listen(self, callback: Callable[[GraphChange[NodeT]], None]) -> Callable[[], None]:
        self._listeners.append(callback)

        def unsubscribe() -> None:
            if callback in self._listeners:
                self._listeners.remove(callback)
        return unsubscribe

    def _notify(self, change: GraphChange[NodeT]) -> None:
        for callback in tuple(self._listeners):
            callback(change)

    def add(self, node: NodeT, **attributes: Any) -> NodeT:
        result = super().add(node, **attributes)
        self._notify(GraphChange(nodes=NodeChanges(
            added=(node,), changed=_attribute_changes(node, {}, self.attributes(node))
        )))
        return result

    def set(self, node: NodeT, **attributes: Any) -> None:
        before = self.attributes(node)
        super().set(node, **attributes)
        changed = _attribute_changes(node, before, self.attributes(node))
        if changed:
            self._notify(GraphChange(nodes=NodeChanges(changed=changed)))

    def unset(self, node: NodeT, *names: str) -> None:
        before = self.attributes(node)
        super().unset(node, *names)
        changed = _attribute_changes(node, before, self.attributes(node))
        if changed:
            self._notify(GraphChange(nodes=NodeChanges(changed=changed)))

    def add_link(self, source: NodeT, target: NodeT, input: str) -> None:
        old = next((link for link in self.in_links(target) if link.input == input), None)
        super().add_link(source, target, input)
        new = Link(source, target, input)
        if old != new:
            self._notify(GraphChange(links=LinkChanges(
                added=(new,), removed=(old,) if old is not None else ()
            )))

    def remove_link(self, source: NodeT, target: NodeT, input: str) -> None:
        super().remove_link(source, target, input)
        self._notify(GraphChange(links=LinkChanges(removed=(Link(source, target, input),))))

    def remove(self, node: NodeT) -> None:
        removed_links = self.in_links(node) + self.out_links(node)
        super().remove(node)
        self._notify(GraphChange(
            nodes=NodeChanges(removed=(node,)), links=LinkChanges(removed=removed_links)
        ))

