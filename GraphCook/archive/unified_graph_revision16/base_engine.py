"""Shared graph, cache, and Engine APIs for graph-processing implementations.

This module intentionally knows nothing about eager or contextual computation.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Hashable, Iterator, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Generic, Protocol, TypeVar

NodeT = TypeVar("NodeT", bound=Hashable)
ValueT = TypeVar("ValueT")

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

# --- Cache storage ---------------------------------------------------------

class CacheProtocol(Protocol[NodeT, ValueT]):
    """Structural mapping reads, explicit cache writes.

    Protocol cannot inherit collections.abc.Mapping directly at runtime.
    """

    def __getitem__(self, key: NodeT) -> ValueT: ...
    def __iter__(self) -> Iterator[NodeT]: ...
    def __len__(self) -> int: ...
    def get(self, key: NodeT, default: Any = None) -> ValueT | Any: ...

    def save(self, key: NodeT, value: ValueT) -> None: ...
    def remove(self, key: NodeT) -> None: ...
    def clear(self) -> None: ...


class MemoryCache(Mapping[NodeT, ValueT], Generic[NodeT, ValueT]):
    """In-memory cache; None is a valid stored value."""

    def __init__(self, initial: Mapping[NodeT, ValueT] | None = None) -> None:
        self._entries: dict[NodeT, ValueT] = dict(initial) if initial is not None else {}

    def __getitem__(self, key: NodeT) -> ValueT:
        return self._entries[key]

    def __iter__(self) -> Iterator[NodeT]:
        return iter(self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    def save(self, key: NodeT, value: ValueT) -> None:
        self._entries[key] = value

    def remove(self, key: NodeT) -> None:
        self._entries.pop(key, None)

    def clear(self) -> None:
        self._entries.clear()

@dataclass(frozen=True)
class ExecutionResult(Generic[NodeT, ValueT]):
    node: NodeT
    value: ValueT


@dataclass(frozen=True)
class EngineChange(Generic[NodeT, ValueT]):
    executed: tuple[ExecutionResult[NodeT, ValueT], ...] = ()
    invalidated: tuple[NodeT, ...] = ()

def copy_graph(graph: GraphProtocol[NodeT]) -> Graph[NodeT]:
    """Copy graph records, preserving references to nodes and attribute values."""
    snapshot = Graph[NodeT]()
    for node in graph.nodes():
        snapshot.add(node, **graph.attributes(node))
    for link in graph.links():
        snapshot.add_link(link.source, link.target, link.input)
    return snapshot

class Engine(Generic[NodeT, ValueT], ABC):
    """Style-independent lifecycle, invalidation, cache events and watches.

    evaluate(node) is the shared public interface. Subclasses decide how a
    job is created and how cached results are represented.
    """
    def __init__(self, graph: ObservableGraph[NodeT],
                 cache: CacheProtocol[NodeT, ValueT]):
        self.graph = graph
        self.cache = cache
        self._listeners: list[Callable[[EngineChange[NodeT, ValueT]], None]] = []
        self._watches: dict[NodeT, list[Callable[[ExecutionResult[NodeT, ValueT]], None]]] = {}
        self._dirty: set[NodeT] = set()
        self._generation = 0
        self._unsubscribe_graph = graph.listen(self._on_graph_change)

    def listen(self, callback: Callable[[EngineChange[NodeT, ValueT]], None]) -> Callable[[], None]:
        self._listeners.append(callback)
        def unsubscribe() -> None:
            if callback in self._listeners:
                self._listeners.remove(callback)
        return unsubscribe

    def watch(self, node: NodeT, callback: Callable[[ExecutionResult[NodeT, ValueT]], None]) -> Callable[[], None]:
        if node not in self.graph.nodes():
            raise ValueError('Node is not in graph')
        self._watches.setdefault(node, []).append(callback)
        self._dirty.add(node)
        def unsubscribe() -> None:
            callbacks = self._watches.get(node, [])
            if callback in callbacks:
                callbacks.remove(callback)
            if not callbacks:
                self._watches.pop(node, None)
                self._dirty.discard(node)
        return unsubscribe

    def _notify(self, change: EngineChange[NodeT, ValueT]) -> None:
        for callback in tuple(self._listeners):
            callback(change)

    def _on_graph_change(self, change: GraphChange[NodeT]) -> None:
        changed = {c.node for c in change.nodes.changed}
        changed.update(change.nodes.added)
        changed.update(link.target for link in (*change.links.added, *change.links.removed))
        changed.update(change.nodes.removed)
        self._invalidate_affected(changed)

    def invalidate(self, node: NodeT) -> None:
        if node not in self.graph.nodes():
            raise ValueError('Node is not in graph')
        self._invalidate_affected({node})

    def _invalidate_affected(self, nodes: set[NodeT]) -> None:
        existing = set(self.graph.nodes())
        affected = set(nodes)
        for node in nodes & existing:
            affected.update(descendants(self.graph, node))
        self._generation += 1
        self._evict(affected)
        self._dirty.update(affected & self._watches.keys())
        if affected:
            self._notify(EngineChange(invalidated=tuple(affected)))

    def _commit(self, results: list[ExecutionResult[NodeT, ValueT]], generation: int) -> None:
        if generation != self._generation:
            raise RuntimeError('Graph changed during evaluation; stale results discarded')
        for result in results:
            self._store(result)
        if results:
            self._notify(EngineChange(executed=tuple(results)))

    def refresh(self) -> None:
        for node in tuple(self._dirty):
            if node not in self._watches:
                self._dirty.discard(node)
                continue
            if node not in self.graph.nodes():
                continue
            value = self.evaluate(node)
            self._dirty.discard(node)
            result = ExecutionResult(node, self.results(node))
            for callback in tuple(self._watches.get(node, ())):
                callback(result)

    def close(self) -> None:
        self._unsubscribe_graph()
        self._listeners.clear()
        self._watches.clear()
        self._dirty.clear()

    @abstractmethod
    def evaluate(self, node: NodeT) -> Any: ...

    @abstractmethod
    def results(self, node: NodeT) -> ValueT | None: ...

    @abstractmethod
    def _evict(self, nodes: set[NodeT]) -> None: ...

    @abstractmethod
    def _store(self, result: ExecutionResult[NodeT, ValueT]) -> None: ...

