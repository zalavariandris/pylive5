# remove shared Attribute-Input sync behaviour, 
#   and move the actuall implementation to both Eager and Hybrid Graph
"""Generic graph + observable edits + eager and hybrid execution.

Python 3.11+. EagerGraph and HybridGraph each own their binding behavior.
Engine cache storage uses CacheProtocol and MemoryCache.
Graph/job snapshots are shallow: referenced values should be treated as immutable.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Hashable, Iterator, Mapping
from contextvars import ContextVar
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, ClassVar, Generic, Protocol, Self, TypeVar, runtime_checkable

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


# --- Operator styles -------------------------------------------------------

class EagerOperator(ABC):
    @abstractmethod
    def compute(self, **bindings: Any) -> Any: ...


class Context(ABC):
    @abstractmethod
    def union(self, other: Context) -> Context: ...

    @abstractmethod
    def subtract(self, other: Context) -> Context: ...

    @abstractmethod
    def is_empty(self) -> bool: ...


@runtime_checkable
class ContextualResult(Protocol):
    def merge(self, other: Self) -> Self: ...
    def select(self, ctx: Context) -> Self: ...


class HybridOperator(ABC):
    def request(self, ctx: Context, **bindings: Any) -> Mapping[str, Context]:
        return {}

    @abstractmethod
    def compute(self, **bindings: Any) -> ContextualResult: ...


def eager_operator(fn: Callable[..., Any]) -> type[EagerOperator]:
    return type(fn.__name__, (EagerOperator,), {
        '__module__': fn.__module__, '__doc__': fn.__doc__, 'compute': staticmethod(fn)
    })


def hybrid_operator(fn: Callable[..., ContextualResult]) -> type[HybridOperator]:
    return type(fn.__name__, (HybridOperator,), {
        '__module__': fn.__module__, '__doc__': fn.__doc__, 'compute': staticmethod(fn)
    })


class EagerGraph(ObservableGraph[EagerOperator]):
    """Keep EagerOperator input bindings synchronized with graph links."""

    def _validate(self, node: EagerOperator, bindings: Mapping[str, Any]) -> None:
        existing = set(self.nodes())
        for value in bindings.values():
            if isinstance(value, EagerOperator):
                if value not in existing:
                    raise ValueError('Referenced operator is not in graph')
                if value is node or (node in existing and value in descendants(self, node)):
                    raise ValueError('Link would create a cycle')

    def add(self, node: EagerOperator, **bindings: Any) -> EagerOperator:
        if not isinstance(node, EagerOperator):
            raise TypeError(f'Expected {EagerOperator.__name__}')
        if node in self.nodes():
            raise ValueError('Node already in graph')
        self._validate(node, bindings)
        super().add(node, **bindings)
        for name, value in bindings.items():
            if isinstance(value, EagerOperator):
                super().add_link(value, node, name)
        return node

    def set(self, node: EagerOperator, **bindings: Any) -> None:
        self._require(node)
        self._validate(node, bindings)
        super().set(node, **bindings)
        incoming = {link.input: link.source for link in self.in_links(node)}
        for name, value in bindings.items():
            if isinstance(value, EagerOperator):
                super().add_link(value, node, name)
            elif name in incoming:
                super().remove_link(incoming[name], node, name)

    def unset(self, node: EagerOperator, *names: str) -> None:
        self._require(node)
        names = tuple(dict.fromkeys(names))
        if any(name not in self.attributes(node) for name in names):
            raise KeyError('Binding does not exist')
        incoming = {link.input: link.source for link in self.in_links(node)}
        super().unset(node, *names)
        for name in names:
            if name in incoming:
                super().remove_link(incoming[name], node, name)

    def add_link(self, source: EagerOperator, target: EagerOperator, input: str) -> None:
        self.set(target, **{input: source})

    def remove_link(self, source: EagerOperator, target: EagerOperator, input: str) -> None:
        if not any(link.source == source and link.input == input
                   for link in self.in_links(target)):
            raise ValueError('Link does not exist')
        self.unset(target, input)

    def remove(self, node: EagerOperator) -> None:
        self._require(node)
        for link in self.out_links(node):
            self.unset(link.target, link.input)
        super().remove(node)



class HybridGraph(ObservableGraph[HybridOperator]):
    """Keep HybridOperator input bindings synchronized with graph links."""

    def _validate(self, node: HybridOperator, bindings: Mapping[str, Any]) -> None:
        existing = set(self.nodes())
        for value in bindings.values():
            if isinstance(value, HybridOperator):
                if value not in existing:
                    raise ValueError('Referenced operator is not in graph')
                if value is node or (node in existing and value in descendants(self, node)):
                    raise ValueError('Link would create a cycle')

    def add(self, node: HybridOperator, **bindings: Any) -> HybridOperator:
        if not isinstance(node, HybridOperator):
            raise TypeError(f'Expected {HybridOperator.__name__}')
        if node in self.nodes():
            raise ValueError('Node already in graph')
        self._validate(node, bindings)
        super().add(node, **bindings)
        for name, value in bindings.items():
            if isinstance(value, HybridOperator):
                super().add_link(value, node, name)
        return node

    def set(self, node: HybridOperator, **bindings: Any) -> None:
        self._require(node)
        self._validate(node, bindings)
        super().set(node, **bindings)
        incoming = {link.input: link.source for link in self.in_links(node)}
        for name, value in bindings.items():
            if isinstance(value, HybridOperator):
                super().add_link(value, node, name)
            elif name in incoming:
                super().remove_link(incoming[name], node, name)

    def unset(self, node: HybridOperator, *names: str) -> None:
        self._require(node)
        names = tuple(dict.fromkeys(names))
        if any(name not in self.attributes(node) for name in names):
            raise KeyError('Binding does not exist')
        incoming = {link.input: link.source for link in self.in_links(node)}
        super().unset(node, *names)
        for name in names:
            if name in incoming:
                super().remove_link(incoming[name], node, name)

    def add_link(self, source: HybridOperator, target: HybridOperator, input: str) -> None:
        self.set(target, **{input: source})

    def remove_link(self, source: HybridOperator, target: HybridOperator, input: str) -> None:
        if not any(link.source == source and link.input == input
                   for link in self.in_links(target)):
            raise ValueError('Link does not exist')
        self.unset(target, input)

    def remove(self, node: HybridOperator) -> None:
        self._require(node)
        for link in self.out_links(node):
            self.unset(link.target, link.input)
        super().remove(node)



# --- Cache storage ---------------------------------------------------------

ValueT = TypeVar('ValueT')


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


# --- Execution records and notifications ----------------------------------


@dataclass(frozen=True)
class ExecutionResult(Generic[NodeT, ValueT]):
    node: NodeT
    value: ValueT


@dataclass(frozen=True)
class EngineChange(Generic[NodeT, ValueT]):
    executed: tuple[ExecutionResult[NodeT, ValueT], ...] = ()
    invalidated: tuple[NodeT, ...] = ()


@dataclass(frozen=True)
class CacheEntry:
    covered: Context
    value: ContextualResult


def merge_entry(entry: CacheEntry | None, result: ExecutionResult[HybridOperator, CacheEntry]) -> CacheEntry:
    portion = result.value
    if entry is None:
        return portion
    return CacheEntry(entry.covered.union(portion.covered), entry.value.merge(portion.value))


def copy_graph(graph: GraphProtocol[NodeT]) -> Graph[NodeT]:
    """Copy graph records, preserving references to nodes and attribute values."""
    snapshot = Graph[NodeT]()
    for node in graph.nodes():
        snapshot.add(node, **graph.attributes(node))
    for link in graph.links():
        snapshot.add_link(link.source, link.target, link.input)
    return snapshot


def resolved_bindings(graph: GraphProtocol[NodeT], node: NodeT,
                      values: Mapping[NodeT, Any]) -> dict[str, Any]:
    bindings = dict(graph.attributes(node))
    for link in graph.in_links(node):
        bindings[link.input] = values[link.source]
    return bindings


# --- Jobs ------------------------------------------------------------------

class EagerJob:
    """Evaluate ancestors in dependency-first order, memoized for one run."""
    def __init__(self, graph: GraphProtocol[EagerOperator], node: EagerOperator,
                 cached: Mapping[EagerOperator, Any]):
        self.graph = graph
        self.node = node
        self._memo = dict(cached)
        self.results: list[ExecutionResult[EagerOperator, Any]] = []

    def run(self) -> Any:
        for node in topological_sort(self.graph, self.node):
            if node in self._memo:
                continue
            value = node.compute(**resolved_bindings(self.graph, node, self._memo))
            self._memo[node] = value
            self.results.append(ExecutionResult(node, value))
        return self._memo[self.node]


@dataclass(frozen=True)
class ExecutionScope:
    job: HybridJob
    node: HybridOperator
    ctx: Context

    _current: ClassVar[ContextVar[ExecutionScope | None]] = ContextVar(
        'execution_scope', default=None
    )

    @classmethod
    def current(cls) -> ExecutionScope:
        scope = cls._current.get()
        if scope is None:
            raise RuntimeError('No active hybrid computation')
        return scope

    def input(self, name: str) -> HybridOperator:
        for link in self.job.graph.in_links(self.node):
            if link.input == name:
                return link.source
        raise KeyError(name)


class HybridJob:
    """Plan requests, compute topologically, allow nested upstream evaluation."""
    def __init__(self, graph: GraphProtocol[HybridOperator], root: HybridOperator,
                 cached: Mapping[HybridOperator, CacheEntry]):
        self.graph = graph
        self.root = root
        self.order = topological_sort(graph, root)
        self._memo = dict(cached)
        self._active: set[HybridOperator] = set()
        self._planning = False
        self.results: list[ExecutionResult[HybridOperator, CacheEntry]] = []

    def _missing(self, node: HybridOperator, ctx: Context) -> Context:
        entry = self._memo.get(node)
        return ctx if entry is None else ctx.subtract(entry.covered)

    def _get(self, node: HybridOperator, ctx: Context) -> ContextualResult:
        entry = self._memo.get(node)
        if entry is None or not self._missing(node, ctx).is_empty():
            raise RuntimeError('Requested output is unavailable')
        return entry.value.select(ctx)

    def _store(self, node: HybridOperator, ctx: Context, value: ContextualResult) -> None:
        result = ExecutionResult(node, CacheEntry(ctx, value))
        self._memo[node] = merge_entry(self._memo.get(node), result)
        self.results.append(result)

    def _plan(self, root: HybridOperator, wanted: Context):
        demand = {root: wanted}
        pending: dict[HybridOperator, Context] = {}
        requests: dict[HybridOperator, dict[str, Context]] = {}
        for node in reversed(self.order):
            if node not in demand:
                continue
            missing = self._missing(node, demand[node])
            if missing.is_empty():
                continue
            if node in self._active:
                raise RuntimeError('Recursive evaluation of active operator')
            pending[node] = missing
            sources = {link.input: link.source for link in self.graph.in_links(node)}
            self._planning = True
            try:
                overrides = node.request(missing, **self.graph.attributes(node))
            finally:
                self._planning = False
            if not isinstance(overrides, Mapping) or set(overrides) - set(sources):
                raise ValueError('Invalid input requests')
            requests[node] = {}
            for name, source in sources.items():
                required = overrides.get(name, missing)
                if not isinstance(required, Context):
                    raise TypeError('Request must be a Context')
                requests[node][name] = required
                demand[source] = (demand[source].union(required)
                                  if source in demand else required)
        return pending, requests

    def evaluate(self, node: HybridOperator, ctx: Context) -> ContextualResult:
        if self._planning:
            raise RuntimeError('request() cannot evaluate')
        if node not in self.order:
            raise ValueError('Node is outside this job')
        scope = ExecutionScope._current.get()
        if scope is not None and scope.job is self:
            if node not in ancestors(self.graph, scope.node):
                raise ValueError('Nested evaluation must target an upstream node')
        if self._missing(node, ctx).is_empty():
            return self._get(node, ctx)
        if node in self._active:
            raise RuntimeError('Recursive evaluation of active operator')

        pending, requests = self._plan(node, ctx)
        for op in self.order:
            if op not in pending:
                continue
            sources = {link.input: link.source for link in self.graph.in_links(op)}
            bindings = dict(self.graph.attributes(op))
            for name, source in sources.items():
                bindings[name] = self._get(source, requests[op][name])
            token = ExecutionScope._current.set(ExecutionScope(self, op, pending[op]))
            self._active.add(op)
            try:
                self._store(op, pending[op], op.compute(**bindings))
            finally:
                self._active.remove(op)
                ExecutionScope._current.reset(token)
        return self._get(node, ctx)

    def run(self, ctx: Context) -> ContextualResult:
        return self.evaluate(self.root, ctx)


# --- Engines ---------------------------------------------------------------

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


class EagerEngine(Engine[EagerOperator, Any]):
    def __init__(self, graph: EagerGraph,
                 cache: CacheProtocol[EagerOperator, Any] | None = None):
        super().__init__(graph, cache if cache is not None else MemoryCache())

    def evaluate(self, node: EagerOperator) -> Any:
        generation = self._generation
        job = EagerJob(copy_graph(self.graph), node, dict(self.cache))
        try:
            value = job.run()
        except Exception:
            self._commit(job.results, generation)
            raise
        self._commit(job.results, generation)
        return value

    def results(self, node: EagerOperator) -> Any:
        return self.cache.get(node)

    def _evict(self, nodes: set[EagerOperator]) -> None:
        for node in nodes:
            self.cache.remove(node)

    def _store(self, result: ExecutionResult[EagerOperator, Any]) -> None:
        self.cache.save(result.node, result.value)


class HybridEngine(Engine[HybridOperator, CacheEntry]):
    def __init__(self, graph: HybridGraph, context: Context,
                 cache: CacheProtocol[HybridOperator, CacheEntry] | None = None):
        super().__init__(graph, cache if cache is not None else MemoryCache())
        self.context = context

    def evaluate(self, node: HybridOperator) -> ContextualResult:
        generation = self._generation
        job = HybridJob(copy_graph(self.graph), node, dict(self.cache))
        try:
            value = job.run(self.context)
        except Exception:
            self._commit(job.results, generation)
            raise
        self._commit(job.results, generation)
        return value

    def results(self, node: HybridOperator) -> CacheEntry | None:
        return self.cache.get(node)

    def _evict(self, nodes: set[HybridOperator]) -> None:
        for node in nodes:
            self.cache.remove(node)

    def _store(self, result: ExecutionResult[HybridOperator, CacheEntry]) -> None:
        self.cache.save(result.node, merge_entry(self.cache.get(result.node), result))

    def set_context(self, context: Context) -> None:
        self.context = context
        self._dirty.update(self._watches)


# --- Examples --------------------------------------------------------------

@dataclass(frozen=True)
class FrameContext(Context):
    frames: frozenset[int]

    def __post_init__(self) -> None:
        object.__setattr__(self, 'frames', frozenset(self.frames))

    def union(self, other: Context) -> FrameContext:
        assert isinstance(other, FrameContext)
        return FrameContext(self.frames | other.frames)

    def subtract(self, other: Context) -> FrameContext:
        assert isinstance(other, FrameContext)
        return FrameContext(self.frames - other.frames)

    def is_empty(self) -> bool:
        return not self.frames


@dataclass(frozen=True)
class Video:
    frames: Mapping[int, float]

    def merge(self, other: Self) -> Self:
        return type(self)({**self.frames, **other.frames})

    def select(self, ctx: Context) -> Self:
        assert isinstance(ctx, FrameContext)
        return type(self)({f: self.frames[f] for f in ctx.frames if f in self.frames})


@eager_operator
def Add(a: int, b: int) -> int:
    return a + b


class ReadVideo(HybridOperator):
    def compute(self, count: int = 12) -> Video:
        return Video({f: float(f) for f in ExecutionScope.current().ctx.frames if 0 <= f < count})


class TemporalBlend(HybridOperator):
    def request(self, ctx: Context, source: HybridOperator, duration: int = 3) -> Mapping[str, Context]:
        assert isinstance(ctx, FrameContext)
        return {'source': FrameContext({f - d for f in ctx.frames for d in range(duration)})}

    def compute(self, source: Video, duration: int = 3) -> Video:
        output = {}
        for f in ExecutionScope.current().ctx.frames:
            samples = [source.frames[f - d] for d in range(duration) if f - d in source.frames]
            if samples:
                output[f] = sum(samples) / len(samples)
        return Video(output)


@hybrid_operator
def DynamicLookback(source: Video, lookback: int = 1) -> Video:
    scope = ExecutionScope.current()
    output = {}
    for f in scope.ctx.frames:
        previous = f - lookback
        older = scope.job.evaluate(scope.input('source'), FrameContext({previous}))
        if f in source.frames and previous in older.frames:
            output[f] = (source.frames[f] + older.frames[previous]) / 2
    return Video(output)


@hybrid_operator
def Gain(source: Video, factor: float = 2) -> Video:
    return Video({f: value * factor for f, value in source.frames.items()})


if __name__ == '__main__':
    eager_graph = EagerGraph()
    left = eager_graph.add(Add(), a=1, b=2)
    right = eager_graph.add(Add(), a=left, b=3)
    eager = EagerEngine(eager_graph)
    eager.listen(lambda change: print('Eager event:', change))
    print('Eager:', eager.evaluate(right))   # 6
    eager_graph.set(left, a=10)
    print('Eager updated:', eager.evaluate(right))  # 15

    hybrid_graph = HybridGraph()
    read = hybrid_graph.add(ReadVideo(), count=12)
    blend = hybrid_graph.add(TemporalBlend(), source=read, duration=3)
    lookback = hybrid_graph.add(DynamicLookback(), source=blend, lookback=1)
    gain = hybrid_graph.add(Gain(), source=lookback, factor=2)
    hybrid = HybridEngine(hybrid_graph, FrameContext({5}))
    hybrid.watch(gain, lambda result: print('Watched:', result.value.value.frames))
    hybrid.refresh()  # {5: 7.0}
    hybrid_graph.set(gain, factor=3)
    hybrid.refresh()  # {5: 10.5}
