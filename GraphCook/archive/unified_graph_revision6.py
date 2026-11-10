
"""Synchronous operator graph with link queries and post-edit events."""
from __future__ import annotations

from abc import ABC, abstractmethod
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Callable, ClassVar, Iterable, Mapping


# --- Operator and request contracts -----------------------------------------

class Context(ABC):
    """Immutable request coverage; each domain implements its own set algebra."""

    @abstractmethod
    def union(self, other: Context) -> Context: ...

    @abstractmethod
    def intersection(self, other: Context) -> Context: ...

    @abstractmethod
    def subtract(self, other: Context) -> Context: ...

    @abstractmethod
    def is_empty(self) -> bool: ...


class Operator(ABC):
    """One graph node; operator implementations should be stateless."""

    def request(self, ctx: Context, **bindings: Any) -> Mapping[str, Context]:
        """Return upstream input contexts; omitted inputs inherit ctx.

        Receives the same named bindings as compute(), except inputs remain
        unresolved Operator instances. May inspect upstream identity, but must
        not modify graph structure, initiate computation, or cause side effects.
        """
        return {}

    @abstractmethod
    def compute(self, **bindings: Any) -> Any:
        """Compute with input Operators replaced by their evaluated results."""


def operator(fn: Callable[..., Any]) -> type[Operator]:
    """Use an ordinary function as an Operator class: @operator."""
    return type(fn.__name__, (Operator,), {
        "__module__": fn.__module__,
        "__doc__": fn.__doc__,
        "compute": staticmethod(fn),
    })


def _copy(value: Any) -> Any:
    return value if isinstance(value, Operator) else deepcopy(value)


def _inputs(bindings: Mapping[str, Any]) -> dict[str, Operator]:
    return {name: value for name, value in bindings.items() if isinstance(value, Operator)}


# --- Graph ------------------------------------------------------------------

@dataclass(frozen=True)
class Link:
    source: Operator
    target: Operator
    input: str


@dataclass(frozen=True)
class GraphSnapshot:
    bindings: Mapping[Operator, Mapping[str, Any]]


class Graph:
    """Private bindings and directed topology. No event or cache state."""

    def __init__(self) -> None:
        self._bindings: dict[Operator, Mapping[str, Any]] = {}
        self._dependents: dict[Operator, set[Operator]] = {}

    def nodes(self) -> tuple[Operator, ...]:
        return tuple(self._bindings)

    def links(self) -> tuple[Link, ...]:
        """All directed links, including distinct named inputs."""
        return tuple(link for node in self.nodes() for link in self.in_links(node))

    def in_links(self, node: Operator) -> tuple[Link, ...]:
        """Links entering node."""
        self._require(node)
        return tuple(Link(src, node, name) for name, src in _inputs(self._bindings[node]).items())

    def out_links(self, node: Operator) -> tuple[Link, ...]:
        """Links leaving node."""
        self._require(node)
        return tuple(
            Link(node, target, name)
            for target in self._dependents[node]
            for name, src in _inputs(self._bindings[target]).items()
            if src is node
        )

    def bindings(self, node: Operator) -> Mapping[str, Any]:
        """Detached, read-only record; ordinary parameters are copied."""
        self._require(node)
        return MappingProxyType({k: _copy(v) for k, v in self._bindings[node].items()})

    def _require(self, node: Operator) -> None:
        if node not in self._bindings:
            raise ValueError("Operator is not in this graph")

    def ancestors(self, node: Operator) -> set[Operator]:
        """All upstream operators, excluding node."""
        self._require(node)
        found, pending = set(), list(_inputs(self._bindings[node]).values())
        while pending:
            current = pending.pop()
            if current not in found:
                found.add(current)
                pending.extend(_inputs(self._bindings[current]).values())
        return found

    def descendants(self, node: Operator) -> set[Operator]:
        """All downstream operators, excluding node."""
        self._require(node)
        found, pending = set(), list(self._dependents[node])
        while pending:
            current = pending.pop()
            if current not in found:
                found.add(current)
                pending.extend(self._dependents[current])
        return found

    def add(self, node: Operator, **bindings: Any) -> Operator:
        """Register an existing Operator with its initial bindings atomically."""
        if not isinstance(node, Operator):
            raise TypeError("graph.add() expects an Operator instance")
        if node in self._bindings:
            raise ValueError("Operator is already in this graph")

        record = {k: _copy(v) for k, v in bindings.items()}
        sources = set(_inputs(record).values())

        if node in sources:
            raise ValueError("Self-dependency")
        for source in sources:
            self._require(source)

        self._bindings[node] = MappingProxyType(record)
        self._dependents[node] = set()
        for source in sources:
            self._dependents[source].add(node)
        return node

    def _replace(self, node: Operator, record: dict[str, Any]) -> None:
        before = set(_inputs(self._bindings[node]).values())
        after = set(_inputs(record).values())

        for source in after:
            self._require(source)
        if node in after or any(node in self.ancestors(source) for source in after):
            raise ValueError("Binding would create a cycle")

        self._bindings[node] = MappingProxyType(record)
        for source in before - after:
            self._dependents[source].discard(node)
        for source in after - before:
            self._dependents[source].add(node)

    def set(self, node: Operator, **changes: Any) -> None:
        self._require(node)
        if changes:
            record = dict(self._bindings[node])
            record.update({k: _copy(v) for k, v in changes.items()})
            self._replace(node, record)

    def unset(self, node: Operator, *names: str) -> None:
        self._require(node)
        if names:
            record = dict(self._bindings[node])
            for name in names:
                del record[name]
            self._replace(node, record)

    def add_link(self, source: Operator, target: Operator, input: str) -> None:
        """Connect (or replace) an input. Equivalent to set(target, ...)."""
        self.set(target, **{input: source})

    def remove_link(self, source: Operator, target: Operator, input: str) -> None:
        """Disconnect only if this exact source is still connected."""
        self._require(target)
        if self._bindings[target].get(input) is not source:
            raise ValueError("Link does not exist")
        self.unset(target, input)

    def remove(self, node: Operator) -> None:
        """Remove a node and all its incoming/outgoing links."""
        self._require(node)

        for dependent in tuple(self._dependents[node]):
            record = {k: v for k, v in self._bindings[dependent].items() if v is not node}
            self._bindings[dependent] = MappingProxyType(record)

        for source in set(_inputs(self._bindings[node]).values()):
            self._dependents[source].discard(node)

        del self._bindings[node], self._dependents[node]

    def snapshot(self, root: Operator) -> GraphSnapshot:
        """Capture upstream bindings independently of later graph edits."""
        self._require(root)
        records: dict[Operator, Mapping[str, Any]] = {}

        def visit(node: Operator) -> None:
            if node in records:
                return
            record = MappingProxyType({k: _copy(v) for k, v in self._bindings[node].items()})
            records[node] = record
            for source in _inputs(record).values():
                visit(source)

        visit(root)
        return GraphSnapshot(MappingProxyType(records))


# --- Change events ----------------------------------------------------------

class _Missing:
    def __repr__(self) -> str:
        return "MISSING"


MISSING = _Missing()


@dataclass(frozen=True)
class ValueChange:
    node: Operator
    name: str
    old: Any
    new: Any


@dataclass(frozen=True)
class GraphEvent:
    added_nodes: tuple[Operator, ...] = ()
    removed_nodes: tuple[Operator, ...] = ()
    added_links: tuple[Link, ...] = ()
    removed_links: tuple[Link, ...] = ()
    changed_values: tuple[ValueChange, ...] = ()


def _same(a: Any, b: Any) -> bool:
    if a is b:
        return True
    if a is MISSING or b is MISSING or isinstance(a, Operator) or isinstance(b, Operator):
        return False
    try:
        result = a == b
        return bool(result) if isinstance(result, bool) else False
    except (TypeError, ValueError):
        return False


def _binding_changes(node: Operator, before: Mapping, after: Mapping,
                     names: Iterable[str] | None = None):
    added, removed, values = [], [], []
    names = dict.fromkeys((*before, *after)) if names is None else names

    for name in names:
        old, new = before.get(name, MISSING), after.get(name, MISSING)
        if _same(old, new):
            continue
        if isinstance(old, Operator):
            removed.append(Link(old, node, name))
        if isinstance(new, Operator):
            added.append(Link(new, node, name))

        if not isinstance(old, Operator) and not isinstance(new, Operator):
            values.append(ValueChange(node, name, old, new))
        elif isinstance(old, Operator) and not isinstance(new, Operator) and new is not MISSING:
            values.append(ValueChange(node, name, MISSING, new))
        elif isinstance(new, Operator) and not isinstance(old, Operator) and old is not MISSING:
            values.append(ValueChange(node, name, old, MISSING))

    return tuple(added), tuple(removed), tuple(values)


class ObservableGraph(Graph):
    """Graph with one post-edit event for each successful, effective change."""

    def __init__(self) -> None:
        super().__init__()
        self._listeners: list[Callable[[GraphEvent], None]] = []

    def listen(self, callback: Callable[[GraphEvent], None]) -> None:
        self._listeners.append(callback)

    def _notify(self, event: GraphEvent) -> None:
        for callback in tuple(self._listeners):
            callback(event)

    def add(self, node: Operator, **bindings: Any) -> Operator:
        result = super().add(node, **bindings)
        added, removed, values = _binding_changes(node, {}, self.bindings(node))
        self._notify(GraphEvent(
            added_nodes=(node,), 
            added_links=added,
            removed_links=removed, 
            changed_values=values,
        ))
        return result

    def set(self, node: Operator, **changes: Any) -> None:
        if not changes:
            return super().set(node)

        before = self.bindings(node)
        super().set(node, **changes)
        added, removed, values = _binding_changes(node, before, self.bindings(node), changes)

        if added or removed or values:
            self._notify(GraphEvent(
                added_links=added, removed_links=removed, changed_values=values,
            ))

    def unset(self, node: Operator, *names: str) -> None:
        if not names:
            return super().unset(node)

        before = self.bindings(node)
        super().unset(node, *names)
        added, removed, values = _binding_changes(node, before, self.bindings(node), names)

        if added or removed or values:
            self._notify(GraphEvent(
                added_links=added, removed_links=removed, changed_values=values,
            ))

    def remove(self, node: Operator) -> None:
        # Capture the links before the underlying graph removes them.
        removed_links = self.in_links(node) + self.out_links(node)
        super().remove(node)
        self._notify(GraphEvent(removed_nodes=(node,), removed_links=removed_links))


# --- Synchronous evaluation -------------------------------------------------

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
        value = self.job.snapshot.bindings[self.node][name]
        if not isinstance(value, Operator):
            raise TypeError(f"{name!r} is not an upstream operator")
        return value


@dataclass
class _Entry:
    covered: Context
    value: Any  # Implements merge(other) and select(context).


class Job:
    """Plan requests, execute synchronously, cache coverage for this job only."""

    def __init__(self, snapshot: GraphSnapshot) -> None:
        self.snapshot = snapshot
        self._cache: dict[Operator, _Entry] = {}
        self._active: set[Operator] = set()
        self._requesting = False

    def _missing(self, node: Operator, ctx: Context) -> Context:
        entry = self._cache.get(node)
        return ctx if entry is None else ctx.subtract(entry.covered)

    def _get(self, node: Operator, ctx: Context) -> Any:
        entry = self._cache.get(node)
        if entry is None or not self._missing(node, ctx).is_empty():
            raise RuntimeError("Output is not available")
        return entry.value.select(ctx)

    def _store(self, node: Operator, ctx: Context, result: Any) -> None:
        entry = self._cache.get(node)
        if entry is None:
            self._cache[node] = _Entry(ctx, result)
        else:
            entry.value = entry.value.merge(result)
            entry.covered = entry.covered.union(ctx)

    def _upstream_of(self, candidate: Operator, caller: Operator) -> bool:
        pending = list(_inputs(self.snapshot.bindings[caller]).values())
        seen = set()

        while pending:
            node = pending.pop()
            if node is candidate:
                return True
            if node not in seen:
                seen.add(node)
                pending.extend(_inputs(self.snapshot.bindings[node]).values())
        return False

    def _plan(self, root: Operator, wanted: Context):
        order, visited = [], set()

        def visit(node: Operator) -> None:
            if node in visited:
                return
            visited.add(node)
            for source in _inputs(self.snapshot.bindings[node]).values():
                visit(source)
            order.append(node)

        visit(root)
        demand = {root: wanted}
        pending: dict[Operator, Context] = {}
        requests: dict[Operator, dict[str, Context]] = {}

        # Downstream -> upstream: merge requests before computing.
        for node in reversed(order):
            if node not in demand:
                continue

            ctx = self._missing(node, demand[node])
            if ctx.is_empty() and node in self._cache:
                continue
            if node in self._active:
                raise RuntimeError("Recursive evaluation of active operator")
            pending[node] = ctx

            record = self.snapshot.bindings[node]
            sources = _inputs(record)
            self._requesting = True

            try:
                overrides = node.request(ctx, **{k: _copy(v) for k, v in record.items()})
            finally:
                self._requesting = False

            if not isinstance(overrides, Mapping):
                raise TypeError("request() must return a mapping")
            if set(overrides) - set(sources):
                raise ValueError("request() named a non-input binding")

            requests[node] = {}
            for name, source in sources.items():
                required = overrides.get(name, ctx)
                if not isinstance(required, Context):
                    raise TypeError("Input request must be a Context")
                requests[node][name] = required
                demand[source] = demand[source].union(required) if source in demand else required

        return order, pending, requests

    def evaluate(self, node: Operator, ctx: Context) -> Any:
        """Ensure ctx is available; compute only missing coverage."""
        if self._requesting:
            raise RuntimeError("request() must not initiate computation")
        if node not in self.snapshot.bindings:
            raise ValueError("Operator is outside this Job's snapshot")

        scope = ExecutionScope._current.get()
        if scope is not None and scope.job is self and not self._upstream_of(node, scope.node):
            raise ValueError("On-demand evaluation must target an upstream operator")

        if node in self._cache and self._missing(node, ctx).is_empty():
            return self._get(node, ctx)
        if node in self._active:
            raise RuntimeError("Recursive evaluation of active operator")

        order, pending, requests = self._plan(node, ctx)

        # Execute upstream -> downstream.
        for op in order:
            if op not in pending:
                continue

            record = self.snapshot.bindings[op]
            resolved = {
                name: (self._get(value, requests[op][name])
                       if isinstance(value, Operator) else _copy(value))
                for name, value in record.items()
            }

            token = ExecutionScope._current.set(ExecutionScope(self, op, pending[op]))
            self._active.add(op)

            try:
                result = op.compute(**resolved)
                self._store(op, pending[op], result)
            finally:
                self._active.remove(op)
                ExecutionScope._current.reset(token)

        return self._get(node, ctx)


class Engine:
    """Top-level entry point: creates one Job per evaluation."""

    def evaluate(self, graph: Graph, root: Operator, ctx: Context) -> Any:
        return Job(graph.snapshot(root)).evaluate(root, ctx)


# --- Example data domain ----------------------------------------------------

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
    """Example result: frame-to-value mapping rather than image pixels."""
    frames: Mapping[int, float]

    def __post_init__(self) -> None:
        object.__setattr__(self, "frames", MappingProxyType(dict(self.frames)))

    def merge(self, other: Video) -> Video:
        return Video({**self.frames, **other.frames})

    def select(self, ctx: FrameContext) -> Video:
        return Video({frame: self.frames[frame] for frame in ctx.frames if frame in self.frames})


class ReadVideo(Operator):
    def compute(self, * , count: int = 12) -> Video:
        frames = ExecutionScope.current().ctx.frames
        return Video({f: float(f) for f in frames if 0 <= f < count})


class TemporalBlend(Operator):
    def request(self, 
        ctx: FrameContext, *,  
        source: Operator,
        duration: int = 3
    ) -> Mapping[str, Context]:
        return {
            "source": FrameContext({
                f - d for f in ctx.frames for d in range(duration)
            })
        }

    def compute(self, source: Video, duration: int = 3) -> Video:
        output = {}
        for frame in ExecutionScope.current().ctx.frames:
            samples = [source.frames[frame - d] for d in range(duration)
                       if frame - d in source.frames]
            if samples:
                output[frame] = sum(samples) / len(samples)
        return Video(output)


@operator
def DynamicLookback(source: Video, lookback: int = 1) -> Video:
    scope = ExecutionScope.current()
    output = {}

    for frame in scope.ctx.frames:
        previous = frame - lookback
        older = scope.job.evaluate(scope.input("source"), FrameContext({previous}))
        if frame in source.frames and previous in older.frames:
            output[frame] = (source.frames[frame] + older.frames[previous]) / 2

    return Video(output)


@operator
def Gain(source: Video, factor: float = 2.0) -> Video:
    return Video({frame: value * factor for frame, value in source.frames.items()})


# --- Example graph ----------------------------------------------------------

if __name__ == "__main__":
    graph = ObservableGraph()
    graph.listen(print)

    read = graph.add(ReadVideo(), count=12)
    blend = graph.add(TemporalBlend(), source=read, duration=3)
    lookback = graph.add(DynamicLookback(), source=blend, lookback=1)
    gain = graph.add(Gain(), source=lookback, factor=2)

    print("Links:", graph.links())
    print("Into blend:", graph.in_links(blend))
    print("Out of read:", graph.out_links(read))

    result = Engine().evaluate(graph, gain, FrameContext({5}))
    print("Frame 5:", result.frames[5])  # 7.0

    graph.set(gain, factor=3)
    graph.remove_link(lookback, gain, "source")
