
"""Generic DAG, optional observation, and synchronous procedural evaluation."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Hashable, Mapping
from contextvars import ContextVar
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, ClassVar, Generic, Protocol, TypeVar

NodeT = TypeVar("NodeT", bound=Hashable)


# --- Graph protocol and algorithms -----------------------------------------

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
    """All upstream nodes, excluding node."""
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
    """All downstream nodes, excluding node."""
    if node not in graph.nodes():
        raise ValueError("Node is not in graph")

    found, pending = set(), [link.target for link in graph.out_links(node)]
    while pending:
        current = pending.pop()
        if current not in found:
            found.add(current)
            pending.extend(link.target for link in graph.out_links(current))
    return found


def topological_sort(
    graph: GraphProtocol[NodeT], root: NodeT | None = None
) -> tuple[NodeT, ...]:
    """Dependency-first order, optionally restricted to root's ancestors."""
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


# --- Generic graph ----------------------------------------------------------

class Graph(Generic[NodeT]):
    """Mutable DAG. Node attributes and named links are independent."""

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
        return tuple(
            Link(source, node, name)
            for name, source in self._inputs[node].items()
        )

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
            self._attributes[node] = MappingProxyType({
                **self._attributes[node], **attributes
            })

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

        if source == target or source in descendants(self, target):
            raise ValueError("Link would create a cycle")

        old = self._inputs[target].get(input)
        if old == source:
            return

        record = dict(self._inputs[target])
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
                name: source for name, source in self._inputs[target].items()
                if source != node
            })

        for source in set(self._inputs[node].values()):
            self._dependents[source].discard(node)

        del self._attributes[node], self._inputs[node], self._dependents[node]


# --- Change notifications ---------------------------------------------------

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


def _same(old: Any, new: Any) -> bool:
    if old is new:
        return True
    if old is MISSING or new is MISSING:
        return False
    try:
        result = old == new
        return result if isinstance(result, bool) else False
    except (ValueError, TypeError):
        return False


def _attributes_changed(
    node: NodeT, before: Mapping[str, Any], after: Mapping[str, Any]
) -> tuple[NodeChange[NodeT], ...]:
    changes = tuple(
        AttributeChange(
            name,
            before.get(name, MISSING),
            after.get(name, MISSING),
        )
        for name in dict.fromkeys((*before, *after))
        if not _same(before.get(name, MISSING), after.get(name, MISSING))
    )
    return (NodeChange(node, changes),) if changes else ()


# --- Observable graph -------------------------------------------------------

class ObservableGraph(Graph[NodeT]):
    """Emit notifications by overriding the public graph methods."""

    def __init__(self) -> None:
        super().__init__()
        self._listeners: list[Callable[[GraphChange[NodeT]], None]] = []

    def listen(
        self, listener: Callable[[GraphChange[NodeT]], None]
    ) -> Callable[[], None]:
        self._listeners.append(listener)

        def unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)
        return unsubscribe

    def _notify(self, change: GraphChange[NodeT]) -> None:
        for listener in tuple(self._listeners):
            listener(change)

    def add(self, node: NodeT, **attributes: Any) -> NodeT:
        result = super().add(node, **attributes)
        changed = _attributes_changed(node, {}, self.attributes(node))

        self._notify(GraphChange(
            nodes=NodeChanges(added=(node,), changed=changed),
        ))
        return result

    def set(self, node: NodeT, **attributes: Any) -> None:
        before = self.attributes(node)
        super().set(node, **attributes)
        changed = _attributes_changed(node, before, self.attributes(node))

        if changed:
            self._notify(GraphChange(nodes=NodeChanges(changed=changed)))

    def unset(self, node: NodeT, *names: str) -> None:
        before = self.attributes(node)
        super().unset(node, *names)
        changed = _attributes_changed(node, before, self.attributes(node))

        if changed:
            self._notify(GraphChange(nodes=NodeChanges(changed=changed)))

    def add_link(self, source: NodeT, target: NodeT, input: str) -> None:
        old = {link.input: link for link in self.in_links(target)}.get(input)
        super().add_link(source, target, input)
        new = Link(source, target, input)

        if old != new:
            self._notify(GraphChange(links=LinkChanges(
                added=(new,),
                removed=(old,) if old else (),
            )))

    def remove_link(self, source: NodeT, target: NodeT, input: str) -> None:
        super().remove_link(source, target, input)
        self._notify(GraphChange(
            links=LinkChanges(removed=(Link(source, target, input),)),
        ))

    def remove(self, node: NodeT) -> None:
        removed = self.in_links(node) + self.out_links(node)
        super().remove(node)

        self._notify(GraphChange(
            nodes=NodeChanges(removed=(node,)),
            links=LinkChanges(removed=removed),
        ))


# --- Operators --------------------------------------------------------------

class Context(ABC):
    @abstractmethod
    def union(self, other: Context) -> Context: ...

    @abstractmethod
    def intersection(self, other: Context) -> Context: ...

    @abstractmethod
    def subtract(self, other: Context) -> Context: ...

    @abstractmethod
    def is_empty(self) -> bool: ...


class Operator(ABC):
    """Stateless processing node, identified by its instance."""

    def request(self, ctx: Context, **bindings: Any) -> Mapping[str, Context]:
        """Describe upstream needs. Unmentioned inputs inherit ctx.

        Receives unresolved Operator bindings. Must not mutate the graph,
        evaluate operators, or cause side effects during request planning.
        """
        return {}

    @abstractmethod
    def compute(self, **bindings: Any) -> Any: ...


def operator(fn: Callable[..., Any]) -> type[Operator]:
    return type(fn.__name__, (Operator,), {
        "__module__": fn.__module__,
        "__doc__": fn.__doc__,
        "compute": staticmethod(fn),
    })


# --- Operator graph ---------------------------------------------------------

class OperatorGraph(ObservableGraph[Operator]):
    """Synchronize Operator-valued attributes with named input links."""

    def _validate_bindings(
        self, node: Operator, bindings: Mapping[str, Any]
    ) -> None:
        existing = set(self.nodes())

        for value in bindings.values():
            if isinstance(value, Operator):
                if value not in existing:
                    raise ValueError("Referenced operator is not in graph")
                if value == node or (
                    node in existing and value in descendants(self, node)
                ):
                    raise ValueError("Link would create a cycle")

    def add(self, node: Operator, **bindings: Any) -> Operator:
        if not isinstance(node, Operator):
            raise TypeError("OperatorGraph requires Operator nodes")
        if node in self.nodes():
            raise ValueError("Node already in graph")

        self._validate_bindings(node, bindings)
        super().add(node, **bindings)

        for name, value in bindings.items():
            if isinstance(value, Operator):
                super().add_link(value, node, name)

        return node

    def set(self, node: Operator, **bindings: Any) -> None:
        self._require(node)
        self._validate_bindings(node, bindings)
        super().set(node, **bindings)

        current = {
            link.input: link.source for link in self.in_links(node)
        }

        for name, value in bindings.items():
            if isinstance(value, Operator):
                super().add_link(value, node, name)
            elif name in current:
                super().remove_link(current[name], node, name)

    def unset(self, node: Operator, *names: str) -> None:
        self._require(node)
        names = tuple(dict.fromkeys(names))

        attrs = self.attributes(node)
        if any(name not in attrs for name in names):
            raise KeyError("Binding does not exist")

        current = {
            link.input: link.source for link in self.in_links(node)
        }

        super().unset(node, *names)

        for name in names:
            if name in current:
                super().remove_link(current[name], node, name)

    def add_link(self, source: Operator, target: Operator, input: str) -> None:
        self.set(target, **{input: source})

    def remove_link(self, source: Operator, target: Operator, input: str) -> None:
        current = {
            link.input: link.source for link in self.in_links(target)
        }

        if input not in current or current[input] != source:
            raise ValueError("Link does not exist")

        self.unset(target, input)

    def remove(self, node: Operator) -> None:
        self._require(node)

        for link in self.out_links(node):
            self.unset(link.target, link.input)

        super().remove(node)

    def bindings(self, node: Operator) -> Mapping[str, Any]:
        return self.attributes(node)


# --- Execution --------------------------------------------------------------

@dataclass(frozen=True)
class ExecutionScope:
    job: Job
    node: Operator
    ctx: Context

    _current: ClassVar[ContextVar[ExecutionScope | None]] = ContextVar(
        "execution_scope", default=None
    )

    @classmethod
    def current(cls) -> ExecutionScope:
        scope = cls._current.get()
        if scope is None:
            raise RuntimeError("No active computation")
        return scope

    def input(self, name: str) -> Operator:
        for link in self.job.graph.in_links(self.node):
            if link.input == name:
                return link.source
        raise KeyError(f"No input {name!r}")


@dataclass
class _Entry:
    covered: Context
    value: Any  # Implements merge(other) and select(context).


class Job:
    """Synchronous request planning and context-aware caching."""

    def __init__(self, graph: GraphProtocol[Operator], root: Operator) -> None:
        self.graph = graph
        self.order = topological_sort(graph, root)
        self._cache: dict[Operator, _Entry] = {}
        self._active: set[Operator] = set()
        self._planning = False

    def _missing(self, node: Operator, ctx: Context) -> Context:
        entry = self._cache.get(node)
        return ctx if entry is None else ctx.subtract(entry.covered)

    def _get(self, node: Operator, ctx: Context) -> Any:
        entry = self._cache.get(node)
        if entry is None or not self._missing(node, ctx).is_empty():
            raise RuntimeError("Output is not available")
        return entry.value.select(ctx)

    def _store(self, node: Operator, ctx: Context, value: Any) -> None:
        entry = self._cache.get(node)
        if entry is None:
            self._cache[node] = _Entry(ctx, value)
        else:
            entry.value = entry.value.merge(value)
            entry.covered = entry.covered.union(ctx)

    def _plan(self, root: Operator, ctx: Context):
        demand = {root: ctx}
        pending: dict[Operator, Context] = {}
        requests: dict[Operator, dict[str, Context]] = {}

        # Downstream to upstream.
        for node in reversed(self.order):
            if node not in demand:
                continue

            missing = self._missing(node, demand[node])
            if missing.is_empty():
                continue
            if node in self._active:
                raise RuntimeError("Recursive evaluation of active operator")

            pending[node] = missing
            sources = {
                link.input: link.source
                for link in self.graph.in_links(node)
            }

            previous = self._planning
            self._planning = True
            try:
                overrides = node.request(
                    missing, **self.graph.attributes(node)
                )
            finally:
                self._planning = previous

            if not isinstance(overrides, Mapping):
                raise TypeError("request() must return a mapping")
            if set(overrides) - set(sources):
                raise ValueError("request() named an unconnected input")

            requests[node] = {}
            for name, source in sources.items():
                required = overrides.get(name, missing)
                if not isinstance(required, Context):
                    raise TypeError("Input request must be a Context")

                requests[node][name] = required
                demand[source] = (
                    demand[source].union(required)
                    if source in demand else required
                )

        return pending, requests

    def evaluate(self, node: Operator, ctx: Context) -> Any:
        if self._planning:
            raise RuntimeError("request() must not initiate computation")
        if node not in self.order:
            raise ValueError("Operator is outside this Job")

        scope = ExecutionScope._current.get()
        if scope is not None and scope.job is self:
            if node not in ancestors(self.graph, scope.node):
                raise ValueError(
                    "On-demand evaluation must target an upstream node"
                )

        if node in self._cache and self._missing(node, ctx).is_empty():
            return self._get(node, ctx)
        if node in self._active:
            raise RuntimeError("Recursive evaluation of active operator")

        pending, requests = self._plan(node, ctx)

        # Upstream to downstream.
        for op in self.order:
            if op not in pending:
                continue

            sources = {
                link.input: link.source
                for link in self.graph.in_links(op)
            }

            resolved = {
                name: (
                    self._get(sources[name], requests[op][name])
                    if name in sources else value
                )
                for name, value in self.graph.attributes(op).items()
            }

            token = ExecutionScope._current.set(
                ExecutionScope(self, op, pending[op])
            )
            self._active.add(op)

            try:
                result = op.compute(**resolved)
                self._store(op, pending[op], result)
            finally:
                self._active.remove(op)
                ExecutionScope._current.reset(token)

        return self._get(node, ctx)


class Engine:
    """Construct an independent execution graph from the source."""

    def evaluate(
        self,
        source: GraphProtocol[Operator],
        root: Operator,
        ctx: Context,
    ) -> Any:
        graph = Graph[Operator]()

        for node in source.nodes():
            graph.add(node, **source.attributes(node))

        for link in source.links():
            graph.add_link(link.source, link.target, link.input)

        return Job(graph, root).evaluate(root, ctx)


# --- Example domain ---------------------------------------------------------

@dataclass(frozen=True)
class FrameContext(Context):
    frames: frozenset[int] = frozenset()

    def __post_init__(self) -> None:
        object.__setattr__(self, "frames", frozenset(self.frames))

    def union(self, other: FrameContext) -> FrameContext:
        return FrameContext(self.frames | other.frames)

    def intersection(self, other: FrameContext) -> FrameContext:
        return FrameContext(self.frames & other.frames)

    def subtract(self, other: FrameContext) -> FrameContext:
        return FrameContext(self.frames - other.frames)

    def is_empty(self) -> bool:
        return not self.frames


@dataclass(frozen=True)
class Video:
    frames: Mapping[int, float]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "frames", MappingProxyType(dict(self.frames))
        )

    def merge(self, other: Video) -> Video:
        return Video({**self.frames, **other.frames})

    def select(self, ctx: FrameContext) -> Video:
        return Video({
            f: self.frames[f]
            for f in ctx.frames if f in self.frames
        })


class ReadVideo(Operator):
    def compute(self, count: int = 12) -> Video:
        return Video({
            f: float(f)
            for f in ExecutionScope.current().ctx.frames
            if 0 <= f < count
        })


class TemporalBlend(Operator):
    def request(
        self, ctx: FrameContext, source: Operator, duration: int = 3
    ) -> Mapping[str, Context]:
        return {
            "source": FrameContext({
                f - d for f in ctx.frames
                for d in range(duration)
            })
        }

    def compute(self, source: Video, duration: int = 3) -> Video:
        output = {}
        for frame in ExecutionScope.current().ctx.frames:
            samples = [
                source.frames[frame - d]
                for d in range(duration)
                if frame - d in source.frames
            ]
            if samples:
                output[frame] = sum(samples) / len(samples)
        return Video(output)


@operator
def DynamicLookback(source: Video, lookback: int = 1) -> Video:
    scope = ExecutionScope.current()
    output = {}

    for frame in scope.ctx.frames:
        previous = frame - lookback
        older = scope.job.evaluate(
            scope.input("source"), FrameContext({previous})
        )
        if frame in source.frames and previous in older.frames:
            output[frame] = (
                source.frames[frame] + older.frames[previous]
            ) / 2

    return Video(output)


@operator
def Gain(source: Video, factor: float = 2.0) -> Video:
    return Video({
        frame: value * factor
        for frame, value in source.frames.items()
    })


# --- Example ---------------------------------------------------------------

if __name__ == "__main__":
    graph = OperatorGraph()

    read = graph.add(ReadVideo(), count=12)
    blend = graph.add(TemporalBlend(), source=read, duration=3)
    lookback = graph.add(DynamicLookback(), source=blend, lookback=1)
    gain = graph.add(Gain(), source=lookback, factor=2)

    print("Order:", [
        type(node).__name__
        for node in topological_sort(graph, gain)
    ])

    result = Engine().evaluate(graph, gain, FrameContext({5}))
    print("Frame 5:", result.frames[5])  # 7.0
