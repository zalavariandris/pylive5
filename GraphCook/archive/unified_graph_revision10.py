
"""Generic DAG, observable changes, and synchronous operator evaluation."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Hashable, Mapping
from contextvars import ContextVar
from copy import copy, deepcopy
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
    """Read-only structural interface, independent of the node type."""

    def nodes(self) -> tuple[NodeT, ...]: ...
    def links(self) -> tuple[Link[NodeT], ...]: ...
    def attributes(self, node: NodeT) -> Mapping[str, Any]: ...
    def in_links(self, node: NodeT) -> tuple[Link[NodeT], ...]: ...
    def out_links(self, node: NodeT) -> tuple[Link[NodeT], ...]: ...


def ancestors(graph: GraphProtocol[NodeT], node: NodeT) -> set[NodeT]:
    """All upstream nodes, excluding node itself."""
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
    """All downstream nodes, excluding node itself."""
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
    """Dependency-first order, optionally restricted to root and its ancestors."""
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


# --- Graph change records ---------------------------------------------------

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
    except (TypeError, ValueError):
        return False


# --- Generic mutable graph --------------------------------------------------

class Graph(Generic[NodeT]):
    """Mutable DAG with arbitrary hashable nodes and named input links."""

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
        return MappingProxyType(deepcopy(dict(self._attributes[node])))

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

    def _changed(self, change: GraphChange[NodeT]) -> None:
        """Hook used by ObservableGraph."""

    def _add(
        self,
        node: NodeT,
        attrs: Mapping[str, Any],
        inputs: Mapping[str, NodeT],
    ) -> NodeT:
        if node in self._attributes:
            raise ValueError("Node already in graph")
        if node in inputs.values():
            raise ValueError("Self-dependency")

        for source in inputs.values():
            self._require(source)

        attrs = deepcopy(dict(attrs))
        self._attributes[node] = MappingProxyType(attrs)
        self._inputs[node] = MappingProxyType(dict(inputs))
        self._dependents[node] = set()

        for source in set(inputs.values()):
            self._dependents[source].add(node)

        changes = tuple(
            AttributeChange(k, MISSING, deepcopy(v))
            for k, v in attrs.items()
        )
        links = tuple(Link(src, node, name) for name, src in inputs.items())
        changed = (NodeChange(node, changes),) if changes else ()

        self._changed(GraphChange(
            NodeChanges(added=(node,), changed=changed),
            LinkChanges(added=links),
        ))
        return node

    def add(self, node: NodeT, **attributes: Any) -> NodeT:
        return self._add(node, attributes, {})

    def _update(
        self,
        node: NodeT,
        *,
        attributes: Mapping[str, Any] | None = None,
        unset: tuple[str, ...] = (),
        links: Mapping[str, NodeT] | None = None,
        unlink: tuple[str, ...] = (),
    ) -> None:
        self._require(node)
        old_attrs, old_inputs = self._attributes[node], self._inputs[node]
        attrs, inputs = dict(old_attrs), dict(old_inputs)

        for name in unset:
            del attrs[name]
        for name in unlink:
            del inputs[name]

        attrs.update(deepcopy(dict(attributes or {})))
        inputs.update(links or {})

        for source in inputs.values():
            self._require(source)
            if source == node or source in descendants(self, node):
                raise ValueError("Link would create a cycle")

        attrs_changed = tuple(
            AttributeChange(
                name,
                deepcopy(old_attrs[name]) if name in old_attrs else MISSING,
                deepcopy(attrs[name]) if name in attrs else MISSING,
            )
            for name in dict.fromkeys((*old_attrs, *attrs))
            if not _same(old_attrs.get(name, MISSING), attrs.get(name, MISSING))
        )

        added, removed = [], []
        for name in dict.fromkeys((*old_inputs, *inputs)):
            old, new = old_inputs.get(name, MISSING), inputs.get(name, MISSING)
            if _same(old, new):
                continue
            if old is not MISSING:
                removed.append(Link(old, node, name))
            if new is not MISSING:
                added.append(Link(new, node, name))

        if not (attrs_changed or added or removed):
            return

        self._attributes[node] = MappingProxyType(attrs)
        self._inputs[node] = MappingProxyType(inputs)

        before, after = set(old_inputs.values()), set(inputs.values())
        for source in before - after:
            self._dependents[source].discard(node)
        for source in after - before:
            self._dependents[source].add(node)

        changed = (NodeChange(node, attrs_changed),) if attrs_changed else ()
        self._changed(GraphChange(
            NodeChanges(changed=changed),
            LinkChanges(tuple(added), tuple(removed)),
        ))

    def set(self, node: NodeT, **attributes: Any) -> None:
        self._update(node, attributes=attributes)

    def unset(self, node: NodeT, *names: str) -> None:
        self._update(node, unset=names)

    def add_link(self, source: NodeT, target: NodeT, input: str) -> None:
        self._update(target, links={input: source})

    def remove_link(self, source: NodeT, target: NodeT, input: str) -> None:
        self._require(target)
        if self._inputs[target].get(input, MISSING) != source:
            raise ValueError("Link does not exist")
        self._update(target, unlink=(input,))

    def remove(self, node: NodeT) -> None:
        self._require(node)
        removed = self.in_links(node) + self.out_links(node)

        for target in tuple(self._dependents[node]):
            self._inputs[target] = MappingProxyType({
                k: v for k, v in self._inputs[target].items() if v != node
            })

        for source in set(self._inputs[node].values()):
            self._dependents[source].discard(node)

        del self._attributes[node], self._inputs[node], self._dependents[node]
        self._changed(GraphChange(
            NodeChanges(removed=(node,)),
            LinkChanges(removed=removed),
        ))

    def __copy__(self) -> Graph[NodeT]:
        """Copy graph data while preserving node identities.

        Always returns a plain Graph, without observers or specialization.
        """
        result = Graph[NodeT]()
        result._attributes = {
            node: MappingProxyType(deepcopy(dict(attrs)))
            for node, attrs in self._attributes.items()
        }
        result._inputs = {
            node: MappingProxyType(dict(inputs))
            for node, inputs in self._inputs.items()
        }
        result._dependents = {
            node: set(targets) for node, targets in self._dependents.items()
        }
        return result


# --- Observable graph -------------------------------------------------------

class ObservableGraph(Graph[NodeT]):
    """Emits one post-edit change; no duplicate mutation logic."""

    def __init__(self) -> None:
        super().__init__()
        self._listeners: list[Callable[[GraphChange[NodeT]], None]] = []

    def listen(
        self,
        callback: Callable[[GraphChange[NodeT]], None],
    ) -> Callable[[], None]:
        self._listeners.append(callback)

        def unsubscribe() -> None:
            if callback in self._listeners:
                self._listeners.remove(callback)

        return unsubscribe

    def _changed(self, change: GraphChange[NodeT]) -> None:
        for listener in tuple(self._listeners):
            listener(change)


# --- Processing specialization ---------------------------------------------

class Context(ABC):
    """Immutable request coverage, with domain-specific set operations."""

    @abstractmethod
    def union(self, other: Context) -> Context: ...

    @abstractmethod
    def intersection(self, other: Context) -> Context: ...

    @abstractmethod
    def subtract(self, other: Context) -> Context: ...

    @abstractmethod
    def is_empty(self) -> bool: ...


class Operator(ABC):
    """An operator instance is a processing graph node."""

    def request(self, ctx: Context, **bindings: Any) -> Mapping[str, Context]:
        """Describe upstream contexts; omitted inputs inherit ctx.

        Receives unresolved upstream Operator objects and ordinary attributes.
        May inspect upstream identity, but must not mutate the graph, initiate
        computation, or cause side effects. Called during request planning.
        """
        return {}

    @abstractmethod
    def compute(self, **bindings: Any) -> Any:
        """Compute with upstream Operators resolved to their results."""


def operator(fn: Callable[..., Any]) -> type[Operator]:
    return type(fn.__name__, (Operator,), {
        "__module__": fn.__module__,
        "__doc__": fn.__doc__,
        "compute": staticmethod(fn),
    })


class OperatorGraph(ObservableGraph[Operator]):
    """Operator-valued bindings are links; other bindings are attributes."""

    def add(self, node: Operator, **bindings: Any) -> Operator:
        if not isinstance(node, Operator):
            raise TypeError("OperatorGraph requires Operator nodes")

        attrs = {k: v for k, v in bindings.items() if not isinstance(v, Operator)}
        links = {k: v for k, v in bindings.items() if isinstance(v, Operator)}
        return self._add(node, attrs, links)

    def set(self, node: Operator, **bindings: Any) -> None:
        attrs = {k: v for k, v in bindings.items() if not isinstance(v, Operator)}
        links = {k: v for k, v in bindings.items() if isinstance(v, Operator)}

        unset = tuple(k for k in links if k in self._attributes.get(node, {}))
        unlink = tuple(k for k in attrs if k in self._inputs.get(node, {}))
        self._update(node, attributes=attrs, unset=unset, links=links, unlink=unlink)

    def unset(self, node: Operator, *names: str) -> None:
        self._require(node)
        attrs = tuple(k for k in names if k in self._attributes[node])
        links = tuple(k for k in names if k in self._inputs[node])

        if len(attrs) + len(links) != len(set(names)):
            raise KeyError("Binding does not exist")

        self._update(node, unset=attrs, unlink=links)

    def add_link(self, source: Operator, target: Operator, input: str) -> None:
        self.set(target, **{input: source})

    def remove_link(self, source: Operator, target: Operator, input: str) -> None:
        super().remove_link(source, target, input)

    def bindings(self, node: Operator) -> Mapping[str, Any]:
        return MappingProxyType({
            **self.attributes(node),
            **{link.input: link.source for link in self.in_links(node)},
        })


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


def _bindings(graph: GraphProtocol[Operator], node: Operator) -> dict[str, Any]:
    return {
        **graph.attributes(node),
        **{link.input: link.source for link in graph.in_links(node)},
    }


class Job:
    """Synchronous evaluation, planning, and partial memoization for one root."""

    def __init__(self, graph: GraphProtocol[Operator], root: Operator):
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

        for node in reversed(self.order):
            if node not in demand:
                continue

            missing = self._missing(node, demand[node])
            if missing.is_empty() and node in self._cache:
                continue
            if node in self._active:
                raise RuntimeError("Recursive evaluation of active operator")

            pending[node] = missing
            bindings = _bindings(self.graph, node)
            sources = {k: v for k, v in bindings.items() if isinstance(v, Operator)}

            self._planning = True
            try:
                overrides = node.request(missing, **bindings)
            finally:
                self._planning = False

            if not isinstance(overrides, Mapping):
                raise TypeError("request() must return a mapping")
            if set(overrides) - set(sources):
                raise ValueError("request() named an unconnected input")

            requests[node] = {}
            for name, source in sources.items():
                needed = overrides.get(name, missing)
                if not isinstance(needed, Context):
                    raise TypeError("Input request must be a Context")

                requests[node][name] = needed
                demand[source] = (
                    demand[source].union(needed) if source in demand else needed
                )

        return pending, requests

    def evaluate(self, node: Operator, ctx: Context) -> Any:
        """Ensure requested coverage is available, computing missing parts."""
        if self._planning:
            raise RuntimeError("request() must not initiate computation")
        if node not in self.order:
            raise ValueError("Operator is outside this Job")

        scope = ExecutionScope._current.get()
        if scope is not None and scope.job is self:
            if node not in ancestors(self.graph, scope.node):
                raise ValueError("On-demand evaluation must target an upstream node")

        if node in self._cache and self._missing(node, ctx).is_empty():
            return self._get(node, ctx)
        if node in self._active:
            raise RuntimeError("Recursive evaluation of active operator")

        pending, requests = self._plan(node, ctx)

        for op in self.order:
            if op not in pending:
                continue

            bindings = _bindings(self.graph, op)
            resolved = {
                name: self._get(value, requests[op][name])
                if isinstance(value, Operator) else value
                for name, value in bindings.items()
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
    """Copies the full graph for a consistent evaluation."""

    def evaluate(
        self, graph: Graph[Operator], root: Operator, ctx: Context
    ) -> Any:
        return Job(copy(graph), root).evaluate(root, ctx)


# --- Example domain ---------------------------------------------------------

@dataclass(frozen=True)
class FrameContext(Context):
    frames: frozenset[int] = frozenset()

    def __post_init__(self):
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

    def __post_init__(self):
        object.__setattr__(self, "frames", MappingProxyType(dict(self.frames)))

    def merge(self, other: Video) -> Video:
        return Video({**self.frames, **other.frames})

    def select(self, ctx: FrameContext) -> Video:
        return Video({f: self.frames[f] for f in ctx.frames if f in self.frames})


class ReadVideo(Operator):
    def compute(self, count: int = 12) -> Video:
        frames = ExecutionScope.current().ctx.frames
        return Video({f: float(f) for f in frames if 0 <= f < count})


class TemporalBlend(Operator):
    def request(
        self, ctx: FrameContext, source: Operator, duration: int = 3
    ) -> Mapping[str, Context]:
        return {"source": FrameContext({
            f - d for f in ctx.frames for d in range(duration)
        })}

    def compute(self, source: Video, duration: int = 3) -> Video:
        output = {}
        for frame in ExecutionScope.current().ctx.frames:
            samples = [
                source.frames[frame - d] for d in range(duration)
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
        frame: value * factor for frame, value in source.frames.items()
    })


# --- Example ---------------------------------------------------------------

if __name__ == "__main__":
    graph = OperatorGraph()
    graph.listen(print)

    read = graph.add(ReadVideo(), count=12)
    blend = graph.add(TemporalBlend(), source=read, duration=3)
    lookback = graph.add(DynamicLookback(), source=blend, lookback=1)
    gain = graph.add(Gain(), source=lookback, factor=2)

    print("Order:", [
        type(node).__name__ for node in topological_sort(graph, gain)
    ])

    result = Engine().evaluate(graph, gain, FrameContext({5}))
    print("Frame 5:", result.frames[5])  # 7.0
