"""Shared engine infrastructure: operator convention, provider, cache and events."""
from __future__ import annotations

from collections import deque
from collections.abc import Callable, Hashable, Mapping, Iterator, Iterable
from dataclasses import dataclass
from typing import Any, Generic, Literal, Protocol, TypeVar

from graph import Graph, GraphChange, NodeT, ObservableGraph
from myutils.relations import ManyToOneRelation

OPERATOR_ATTRIBUTE = "__operator__"
UNSET = object()


@dataclass(frozen=True)
class OperatorHandle:
    name: str


class UnresolvedOperatorError(LookupError):
    pass


@dataclass(frozen=True)
class ProviderChange:
    added: tuple[OperatorHandle, ...] = ()
    removed: tuple[OperatorHandle, ...] = ()
    changed: tuple[OperatorHandle, ...] = ()
    unknown: bool = False  # Provider cannot identify which operators changed.


class ProviderSnapshot:
    def __init__(self, operators: Mapping[OperatorHandle, Any]) -> None:
        self._operators = dict(operators)

    def resolve(self, handle: OperatorHandle) -> Any:
        try:
            return self._operators[handle]
        except KeyError:
            raise UnresolvedOperatorError(f"Missing operator: {handle.name}") from None


class OperatorProvider(Protocol):
    def snapshot(self) -> ProviderSnapshot: ...
    def listen(self, callback: Callable[[ProviderChange], None]) -> Callable[[], None]: ...


class DictOperatorProvider:
    """Demo provider. A script provider can use the same interface."""

    def __init__(self, operators: Mapping[OperatorHandle, Any] | None = None) -> None:
        self._operators = dict(operators or {})
        self._listeners: list[Callable[[ProviderChange], None]] = []

    def snapshot(self) -> ProviderSnapshot:
        return ProviderSnapshot(self._operators)

    def listen(self, callback: Callable[[ProviderChange], None]) -> Callable[[], None]:
        self._listeners.append(callback)
        def unsubscribe() -> None:
            self._listeners.remove(callback)
        return unsubscribe

    def register(self, handle: OperatorHandle, implementation: Any) -> None:
        existed = handle in self._operators
        self._operators[handle] = implementation
        self._emit(ProviderChange(changed=(handle,) if existed else (),
                                  added=() if existed else (handle,)))

    def unregister(self, handle: OperatorHandle) -> None:
        del self._operators[handle]
        self._emit(ProviderChange(removed=(handle,)))

    def replace_all(self, implementations: Mapping[OperatorHandle, Any], *,
                    unknown: bool = False) -> None:
        """Publish an entire refreshed environment (as a script provider would)."""
        old, new = self._operators, dict(implementations)
        change = ProviderChange(
            added=tuple(new.keys() - old.keys()),
            removed=tuple(old.keys() - new.keys()),
            changed=tuple(h for h in new.keys() & old.keys() if new[h] is not old[h]),
            unknown=unknown,
        )
        self._operators = new
        if change.added or change.removed or change.changed or change.unknown:
            self._emit(change)

    def _emit(self, change: ProviderChange) -> None:
        for callback in tuple(self._listeners):
            callback(change)


ValueT = TypeVar("ValueT")
KeyT = TypeVar("KeyT", bound=Hashable)


class CacheProtocol(Protocol[KeyT, ValueT]):
    def __getitem__(self, key: KeyT) -> ValueT: ...
    def __iter__(self) -> Iterator[KeyT]: ...
    def __len__(self) -> int: ...
    def save(self, key: KeyT, value: ValueT) -> None: ...
    def remove(self, key: KeyT) -> None: ...
    def clear(self) -> None: ...


class MemoryCache(Mapping[KeyT, ValueT]):
    def __init__(self) -> None:
        self._items: dict[KeyT, ValueT] = {}

    def __getitem__(self, key: KeyT) -> ValueT:
        return self._items[key]

    def __iter__(self) -> Iterator[KeyT]:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def save(self, key: KeyT, value: ValueT) -> None:
        self._items[key] = value

    def remove(self, key: KeyT) -> None:
        self._items.pop(key, None)

    def clear(self) -> None:
        self._items.clear()


@dataclass(frozen=True)
class JobEvent(Generic[NodeT]):
    kind: Literal["started", "computed", "failed", "cache_hit"]
    node: NodeT
    job_id: int
    result: Any = UNSET
    error: BaseException | None = None


@dataclass(frozen=True)
class EngineChange(Generic[NodeT]):
    kind: Literal["invalidated", "executed", "job"]
    node: NodeT
    job_id: int | None = None
    result: Any = UNSET
    job_event: JobEvent[NodeT] | None = None


class BaseJob(Generic[NodeT]):
    def __init__(self, graph: Graph[NodeT], provider: ProviderSnapshot,
                 cached: Mapping[NodeT, Any], job_id: int,
                 emit: Callable[[JobEvent[NodeT]], None]) -> None:
        self.graph = graph
        self.provider = provider
        self.cached = dict(cached)
        self.job_id = job_id
        self.completed: dict[NodeT, Any] = {}
        self._emit_event = emit

    def operator(self, node: NodeT) -> Any:
        handle = self.graph.attributes(node).get(OPERATOR_ATTRIBUTE)
        if not isinstance(handle, OperatorHandle):
            raise UnresolvedOperatorError(f"Node {node!r} has no valid {OPERATOR_ATTRIBUTE}")
        return self.provider.resolve(handle)

    def parameters(self, node: NodeT) -> dict[str, Any]:
        params = dict(self.graph.attributes(node))
        params.pop(OPERATOR_ATTRIBUTE, None)
        return params

    def notify(self, kind: Literal["started", "computed", "failed", "cache_hit"],
               node: NodeT, *, result: Any = UNSET,
               error: BaseException | None = None) -> None:
        self._emit_event(JobEvent(kind, node, self.job_id, result, error))

    def evaluate(self, node: NodeT, **kwargs: Any) -> Any:
        raise NotImplementedError


class BaseEngine(Generic[NodeT]):
    """Shared graph/provider integration; subclasses only choose execution strategy."""

    def __init__(self, graph: ObservableGraph[NodeT], provider: OperatorProvider,
                 cache: CacheProtocol[NodeT, Any] | None = None) -> None:
        self.graph = graph
        self.provider = provider
        self.cache: CacheProtocol[NodeT, Any] = cache if cache is not None else MemoryCache()
        self._listeners: list[Callable[[EngineChange[NodeT]], None]] = []
        self._operator_nodes = ManyToOneRelation[NodeT, OperatorHandle]()
        self._revisions: dict[NodeT, int] = {}
        self._revision_counter = 0
        self._next_job_id = 1
        for node in graph.nodes():
            self._sync_operator(node)
        self._unlisten_graph = graph.listen(self._on_graph_change)
        self._unlisten_provider = provider.listen(self._on_provider_change)

    def operator_of(self, node: NodeT) -> OperatorHandle | None:
        handle = self.graph.attributes(node).get(OPERATOR_ATTRIBUTE)
        return handle if isinstance(handle, OperatorHandle) else None

    def nodes_using(self, handle: OperatorHandle) -> frozenset[NodeT]:
        return self._operator_nodes.children_of(handle)

    def parameters_of(self, node: NodeT) -> dict[str, Any]:
        params = dict(self.graph.attributes(node))
        params.pop(OPERATOR_ATTRIBUTE, None)
        return params

    def listen(self, callback: Callable[[EngineChange[NodeT]], None]) -> Callable[[], None]:
        self._listeners.append(callback)
        def unsubscribe() -> None:
            self._listeners.remove(callback)
        return unsubscribe

    def watch(self, node: NodeT,
              callback: Callable[[EngineChange[NodeT]], None]) -> Callable[[], None]:
        return self.listen(lambda change: callback(change) if change.node == node else None)

    def invalidate(self, nodes: Iterable[NodeT]) -> None:
        """Invalidate the supplied nodes and all currently reachable descendants."""
        queue = deque(nodes)
        live_nodes = set(self.graph.nodes())
        seen: set[NodeT] = set()
        while queue:
            node = queue.popleft()
            if node in seen:
                continue
            seen.add(node)
            if node in live_nodes:
                queue.extend(link.target for link in self.graph.out_links(node))
        if not seen:
            return
        self._revision_counter += 1
        for node in seen:
            self._revisions[node] = self._revision_counter
            self.cache.remove(node)
            self._publish(EngineChange("invalidated", node))

    def replace_provider(self, provider: OperatorProvider) -> None:
        self._unlisten_provider()
        self.provider = provider
        self._unlisten_provider = provider.listen(self._on_provider_change)
        self.invalidate(self.graph.nodes())

    def close(self) -> None:
        self._unlisten_graph()
        self._unlisten_provider()

    def _sync_operator(self, node: NodeT) -> None:
        previous = self._operator_nodes.parent_of(node)
        handle = self.operator_of(node)
        if previous is not None and previous != handle:
            self._operator_nodes.delete(node, previous)
        if handle is not None:
            self._operator_nodes.set(node, handle)

    def _on_graph_change(self, change: GraphChange[NodeT]) -> None:
        for node in change.nodes.removed:
            old = self._operator_nodes.parent_of(node)
            if old is not None:
                self._operator_nodes.delete(node, old)
        for node in (*change.nodes.added,
                     *(entry.node for entry in change.nodes.changed)):
            self._sync_operator(node)
        dirty = set(change.nodes.added) | set(change.nodes.removed)
        dirty.update(entry.node for entry in change.nodes.changed)
        dirty.update(link.target for link in change.links.added)
        dirty.update(link.target for link in change.links.removed)
        self.invalidate(dirty)

    def _on_provider_change(self, change: ProviderChange) -> None:
        if change.unknown:
            self.invalidate(self.graph.nodes())
            return
        dirty: set[NodeT] = set()
        for handle in (*change.added, *change.removed, *change.changed):
            dirty.update(self._operator_nodes.children_of(handle))
        self.invalidate(dirty)

    def _publish(self, change: EngineChange[NodeT]) -> None:
        for callback in tuple(self._listeners):
            callback(change)

    def _make_job(self, graph: Graph[NodeT], provider: ProviderSnapshot,
                  cached: Mapping[NodeT, Any], job_id: int,
                  emit: Callable[[JobEvent[NodeT]], None]) -> BaseJob[NodeT]:
        raise NotImplementedError

    def _run_job(self, node: NodeT, **kwargs: Any) -> Any:
        graph_snapshot = self.graph.snapshot()
        revisions_at_start = dict(self._revisions)
        job_id = self._next_job_id
        self._next_job_id += 1
        def forward(event: JobEvent[NodeT]) -> None:
            self._publish(EngineChange("job", event.node, job_id, job_event=event))
        job = self._make_job(graph_snapshot, self.provider.snapshot(),
                             dict(self.cache), job_id, forward)
        try:
            return job.evaluate(node, **kwargs)
        finally:
            # Accept only values still valid for the live graph.
            live_nodes = set(self.graph.nodes())
            for completed_node, result in job.completed.items():
                if (completed_node in live_nodes
                        and self._revisions.get(completed_node, 0)
                        == revisions_at_start.get(completed_node, 0)):
                    self.cache.save(completed_node, result)
                    self._publish(EngineChange("executed", completed_node,
                                               job_id, result=result))
