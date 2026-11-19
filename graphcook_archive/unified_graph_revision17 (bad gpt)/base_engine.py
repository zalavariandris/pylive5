"""Shared Engine interface, execution notifications, and cache abstractions."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Hashable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any, Generic, Protocol, TypeAlias, TypeVar
from uuid import UUID

from graph import Graph, GraphProtocol, GraphChange, ObservableGraph, descendants

NodeT = TypeVar("NodeT", bound=Hashable)
ValueT = TypeVar("ValueT")

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
    """The result of one completed node computation."""
    node: NodeT
    value: ValueT


@dataclass(frozen=True)
class NodeStarted(Generic[NodeT]):
    job_id: UUID
    node: NodeT


@dataclass(frozen=True)
class NodeFinished(Generic[NodeT, ValueT]):
    job_id: UUID
    result: ExecutionResult[NodeT, ValueT]

    @property
    def node(self) -> NodeT:
        return self.result.node


@dataclass(frozen=True)
class NodeFailed(Generic[NodeT]):
    job_id: UUID
    node: NodeT
    error: Exception


# A Job emits one chronological event at a time through its owner's callback.
JobEvent: TypeAlias = (
    NodeStarted[NodeT] | NodeFinished[NodeT, ValueT] | NodeFailed[NodeT]
)


@dataclass(frozen=True)
class EngineChange(Generic[NodeT, ValueT]):
    """UI-facing notifications, independent of the execution algorithm.

    A finished node may still have its result rejected from persistent cache,
    e.g. if the graph was modified during evaluation.
    """
    started: tuple[NodeStarted[NodeT], ...] = ()
    finished: tuple[NodeFinished[NodeT, ValueT], ...] = ()
    failed: tuple[NodeFailed[NodeT], ...] = ()
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

    def _on_job_event(self, event: JobEvent[NodeT, ValueT]) -> None:
        """Forward node lifecycle events immediately, before cache commit."""
        if isinstance(event, NodeStarted):
            self._notify(EngineChange(started=(event,)))
        elif isinstance(event, NodeFinished):
            self._notify(EngineChange(finished=(event,)))
        elif isinstance(event, NodeFailed):
            self._notify(EngineChange(failed=(event,)))
        else:
            raise TypeError(f'Unexpected job event: {type(event).__name__}')

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

