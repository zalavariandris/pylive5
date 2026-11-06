"""Minimal synchronous operator graph with context-aware incremental evaluation.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Callable, ClassVar, Mapping

import numpy as np  # Only used by the example data type/operators below.


# --- User-extensible contracts --------------------------------------------

class Context(ABC):
    """Immutable request coverage; subclasses define the set operations."""

    @abstractmethod
    def union(self, other: Context) -> Context: ...

    @abstractmethod
    def intersection(self, other: Context) -> Context: ...

    @abstractmethod
    def subtract(self, other: Context) -> Context: ...

    @abstractmethod
    def is_empty(self) -> bool: ...


class Operator(ABC):
    """An instance is a graph node. Keep its implementation stateless."""

    def request(self, ctx: Context, **bindings: Any) -> Mapping[str, Context]:
        """Return input-name -> required-context overrides.

        Receives the same bindings as compute(), except upstream bindings are
        unresolved Operator instances. Unmentioned inputs inherit ctx.

        May inspect upstream operator identity, but MUST NOT modify the graph,
        initiate computation, or cause side effects. Planning may call this
        method repeatedly.
        """
        return {}

    @abstractmethod
    def compute(self, **bindings: Any) -> Any:
        """Compute output from resolved inputs and ordinary parameters."""


def operator(fn: Callable[..., Any]) -> type[Operator]:
    """Wrap a function in an Operator class: @operator def gain(...)."""
    return type(fn.__name__, (Operator,), {
        "__module__": fn.__module__, "__doc__": fn.__doc__,
        "compute": staticmethod(fn),
    })


def _copy(value: Any) -> Any:
    return value if isinstance(value, Operator) else deepcopy(value)


def _inputs(bindings: Mapping[str, Any]) -> dict[str, Operator]:
    return {
        key: value
        for key, value in bindings.items()
        if isinstance(value, Operator)
    }


# --- Graph: topology, editable bindings, invalidation ----------------------

@dataclass(frozen=True)
class GraphEvent:
    kind: str
    revision: int
    node: Operator
    affected: frozenset[Operator]


@dataclass(frozen=True)
class _Snapshot:
    bindings: Mapping[Operator, Mapping[str, Any]]


class Graph:
    """Owns private binding records. Every edit passes through Graph methods."""

    def __init__(self) -> None:
        self._bindings: dict[Operator, Mapping[str, Any]] = {}
        self._users: dict[Operator, set[Operator]] = {}
        self._dirty: dict[Operator, int] = {}
        self._listeners: list[Callable[[GraphEvent], None]] = []
        self.revision = 0

    def nodes(self) -> tuple[Operator, ...]:
        return tuple(self._bindings)

    def bindings(self, node: Operator) -> Mapping[str, Any]:
        """Detached, read-only mapping; nested parameter values are copies."""
        self._require(node)
        return MappingProxyType({k: _copy(v) for k, v in self._bindings[node].items()})

    def invalidated_at(self, node: Operator) -> int:
        self._require(node)
        return self._dirty[node]

    def on_change(self, listener: Callable[[GraphEvent], None]) -> None:
        self._listeners.append(listener)

    def _require(self, node: Operator) -> None:
        if node not in self._bindings:
            raise ValueError("Operator is not in this graph")

    def _emit(self, node: Operator, kind: str,
              starts: list[Operator] | None = None) -> None:
        self.revision += 1
        affected, pending = set(), ([node] if starts is None else starts)
        while pending:
            op = pending.pop()
            if op not in affected:
                affected.add(op)
                pending.extend(self._users[op])
        for op in affected:
            self._dirty[op] = self.revision
        event = GraphEvent(kind, self.revision, node, frozenset(affected))
        for callback in tuple(self._listeners):
            callback(event)

    def add(self, node: Operator, **bindings: Any) -> Operator:
        """Register an existing Operator with its initial bindings atomically."""
        if not isinstance(node, Operator):
            raise TypeError("graph.add() requires an Operator instance")
        if node in self._bindings:
            raise ValueError("Operator already in graph")

        record = {k: _copy(v) for k, v in bindings.items()}
        for source in _inputs(record).values():
            if source is node:
                raise ValueError("Self-dependency")
            self._require(source)

        self._bindings[node] = MappingProxyType(record)
        self._users[node] = set()
        for source in set(_inputs(record).values()):
            self._users[source].add(node)
        self._emit(node, "added")
        return node

    def _cycle(self, node: Operator, record: Mapping[str, Any]) -> bool:
        pending, seen = list(_inputs(record).values()), set()
        while pending:
            op = pending.pop()
            if op is node:
                return True
            if op not in seen:
                seen.add(op)
                pending.extend(_inputs(self._bindings[op]).values())
        return False

    def _replace(self, node: Operator, record: dict[str, Any]) -> None:
        before = set(_inputs(self._bindings[node]).values())
        after = set(_inputs(record).values())
        for source in after:
            self._require(source)
        if self._cycle(node, record):
            raise ValueError("Binding would create a cycle")

        self._bindings[node] = MappingProxyType(record)
        for source in before - after:
            self._users[source].discard(node)
        for source in after - before:
            self._users[source].add(node)
        self._emit(node, "changed")

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

    def remove(self, node: Operator) -> None:
        """Remove a node and unset references to it in its consumers."""
        self._require(node)
        consumers = list(self._users[node])
        for user in consumers:
            record = {k: v for k, v in self._bindings[user].items() if v is not node}
            self._bindings[user] = MappingProxyType(record)
        for source in set(_inputs(self._bindings[node]).values()):
            self._users[source].discard(node)
        del self._bindings[node], self._users[node], self._dirty[node]
        self._emit(node, "removed", consumers)

    def snapshot(self, root: Operator) -> _Snapshot:
        """Capture upstream bindings; future graph edits cannot alter this Job."""
        self._require(root)
        records: dict[Operator, Mapping[str, Any]] = {}

        def visit(op: Operator) -> None:
            if op in records:
                return
            record = {k: _copy(v) for k, v in self._bindings[op].items()}
            records[op] = MappingProxyType(record)
            for source in _inputs(record).values():
                visit(source)

        visit(root)
        return _Snapshot(MappingProxyType(records))


# --- Job: plan requested contexts, execute, reuse completed coverage -------

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
        source = self.job.snapshot.bindings[self.node][name]
        if not isinstance(source, Operator):
            raise TypeError(f"{name!r} is not an upstream operator")
        return source


@dataclass
class _Entry:
    covered: Context
    value: Any  # Implements merge(other) and select(context).


class Job:
    """Synchronous, re-entrant evaluation; cache exists only for this Job."""

    def __init__(self, snapshot: _Snapshot) -> None:
        self.snapshot = snapshot
        self._cache: dict[Operator, _Entry] = {}
        self._active: set[Operator] = set()
        self._requesting = False

    def _missing(self, op: Operator, ctx: Context) -> Context:
        entry = self._cache.get(op)
        return ctx if entry is None else ctx.subtract(entry.covered)

    def _get(self, op: Operator, ctx: Context) -> Any:
        if op not in self._cache or not self._missing(op, ctx).is_empty():
            raise RuntimeError("Upstream output is not available")
        return self._cache[op].value.select(ctx)

    def _store(self, op: Operator, ctx: Context, value: Any) -> None:
        entry = self._cache.get(op)
        if entry is None:
            self._cache[op] = _Entry(ctx, value)
        else:
            entry.value = entry.value.merge(value)
            entry.covered = entry.covered.union(ctx)

    def _upstream_of(self, candidate: Operator, caller: Operator) -> bool:
        pending = list(_inputs(self.snapshot.bindings[caller]).values())
        seen: set[Operator] = set()
        while pending:
            op = pending.pop()
            if op is candidate:
                return True
            if op not in seen:
                seen.add(op)
                pending.extend(_inputs(self.snapshot.bindings[op]).values())
        return False

    def _plan(self, root: Operator, requested: Context):
        order, seen = [], set()

        def visit(op: Operator) -> None:
            if op in seen:
                return
            seen.add(op)
            for source in _inputs(self.snapshot.bindings[op]).values():
                visit(source)
            order.append(op)

        visit(root)  # Upstream-first topological order.
        demand = {root: requested}
        pending: dict[Operator, Context] = {}
        inputs: dict[Operator, dict[str, Context]] = {}

        # Propagate requirements downstream -> upstream before computing.
        for op in reversed(order):
            if op not in demand:
                continue
            ctx = self._missing(op, demand[op])
            if ctx.is_empty() and op in self._cache:
                continue
            if op in self._active:
                raise RuntimeError("Recursive evaluation of active operator")
            pending[op] = ctx
            record = self.snapshot.bindings[op]
            sources = _inputs(record)
            self._requesting = True
            try:
                requests = op.request(ctx, **{k: _copy(v) for k, v in record.items()})
            finally:
                self._requesting = False
            if not isinstance(requests, Mapping):
                raise TypeError("request() must return a mapping")
            if set(requests) - set(sources):
                raise ValueError("request() named a non-input binding")

            inputs[op] = {}
            for name, source in sources.items():
                required = requests.get(name, ctx)
                if not isinstance(required, Context):
                    raise TypeError("Input request must be a Context")
                inputs[op][name] = required
                demand[source] = (demand[source].union(required)
                                  if source in demand else required)

        return order, pending, inputs

    def evaluate(self, op: Operator, ctx: Context) -> Any:
        """Ensure output for ctx is available, computing only missing coverage."""
        if self._requesting:
            raise RuntimeError("request() must not initiate computation")
        caller = ExecutionScope._current.get()
        if caller is not None and caller.job is self:
            if not self._upstream_of(op, caller.node):
                raise ValueError("On-demand evaluation requires an upstream operator")
        if op not in self.snapshot.bindings:
            raise ValueError("Operator is outside this Job's snapshot")
        if op in self._active:
            raise RuntimeError("Recursive evaluation of active operator")

        if op not in self._cache or not self._missing(op, ctx).is_empty():
            order, pending, inputs = self._plan(op, ctx)
            for node in order:
                if node not in pending:
                    continue
                record = self.snapshot.bindings[node]
                resolved = {
                    name: (self._get(value, inputs[node][name])
                           if isinstance(value, Operator) else _copy(value))
                    for name, value in record.items()
                }
                token = ExecutionScope._current.set(
                    ExecutionScope(self, node, pending[node])
                )
                self._active.add(node)
                try:
                    result = node.compute(**resolved)
                    self._store(node, pending[node], result)
                finally:
                    self._active.remove(node)
                    ExecutionScope._current.reset(token)

        return self._get(op, ctx)


class Engine:
    def evaluate(self, graph: Graph, root: Operator, ctx: Context) -> Any:
        return Job(graph.snapshot(root)).evaluate(root, ctx)


# --- Example implementations (not part of the generic engine) ------------

@dataclass(frozen=True)
class FrameContext(Context):
    frames: frozenset[int] = frozenset()

    def __post_init__(self) -> None:
        object.__setattr__(self, "frames", frozenset(self.frames))

    def union(self, other: 'FrameContext') -> FrameContext:
        return FrameContext(self.frames | other.frames)

    def intersection(self, other: 'FrameContext') -> FrameContext:
        return FrameContext(self.frames & other.frames)

    def subtract(self, other: 'FrameContext') -> FrameContext:
        return FrameContext(self.frames - other.frames)

    def is_empty(self) -> bool:
        return not self.frames


@dataclass(frozen=True)
class Video:
    """One example result type: it knows how to merge and select frames."""
    frames: Mapping[int, np.ndarray]

    def __post_init__(self) -> None:
        def readonly(image):
            image = np.ascontiguousarray(image)
            return np.frombuffer(image.tobytes(), image.dtype).reshape(image.shape)
        object.__setattr__(self, "frames", MappingProxyType({
            f: readonly(image) for f, image in self.frames.items()
        }))

    def merge(self, other: Video) -> Video:
        return Video({**self.frames, **other.frames})

    def select(self, ctx: FrameContext) -> Video:
        return Video({f: self.frames[f] for f in ctx.frames if f in self.frames})


class ReadVideo(Operator):
    def compute(self, *, count: int = 12) -> Video:
        frames = ExecutionScope.current().ctx.frames
        return Video({f: np.full((2, 2), float(f), dtype=np.float32)
                      for f in frames if 0 <= f < count})


class TemporalBlend(Operator):
    def request(self, ctx: FrameContext, *, source: Operator,
                duration: int = 3) -> Mapping[str, Context]:
        return {"source": FrameContext({f - i for f in ctx.frames
                                        for i in range(duration)})}

    def compute(self, *, source: Video, duration: int = 3) -> Video:
        output = {}
        for f in ExecutionScope.current().ctx.frames:
            samples = [source.frames[f-i] for i in range(duration)
                       if f-i in source.frames]
            if samples:
                output[f] = np.mean(np.stack(samples), axis=0)
        return Video(output)


@operator
def DynamicLookback(source: Video, lookback: int = 1) -> Video:
    scope = ExecutionScope.current()
    output = {}
    for frame in scope.ctx.frames:
        older = scope.job.evaluate(scope.input("source"),
                                   FrameContext({frame - lookback}))
        if frame in source.frames and frame - lookback in older.frames:
            output[frame] = (source.frames[frame] + older.frames[frame-lookback]) / 2
    return Video(output)


@operator
def Gain(source: Video, factor: float = 2.0) -> Video:
    return Video({f: image * factor for f, image in source.frames.items()})


if __name__ == "__main__":
    graph = Graph()
    read = graph.add(ReadVideo(), count=12)
    blend = graph.add(TemporalBlend(), source=read, duration=3)
    lookback = graph.add(DynamicLookback(), source=blend, lookback=1)
    gain = graph.add(Gain(), source=lookback, factor=2)

    print(Engine().evaluate(graph, gain, FrameContext({5})).frames[5][0, 0])
    # Prints 7.0; the on-demand request computes only the missing source frame 2.
