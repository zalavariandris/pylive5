
"""Synchronous operator graph with user-defined context algebra.

Graph owns topology; ObservableGraph adds edit notifications.
Each evaluation Job has its own incremental result cache.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Callable, ClassVar, Mapping

import numpy as np  # Used only by the example operators.


# ============================================================
# CONTEXT AND OPERATOR
# ============================================================

class Context(ABC):
    """Immutable coverage description with user-defined set algebra."""

    @abstractmethod
    def union(self, other: Context) -> Context: ...

    @abstractmethod
    def intersection(self, other: Context) -> Context: ...

    @abstractmethod
    def subtract(self, other: Context) -> Context: ...

    @abstractmethod
    def is_empty(self) -> bool: ...


class Operator(ABC):
    """An instance is one graph node. Operators should be stateless."""

    def request(
        self,
        ctx: Context,
        **bindings: Any,
    ) -> Mapping[str, Context]:
        """Return context overrides for upstream bindings.

        Receives the same named arguments as compute(), but upstream
        inputs are unresolved Operator instances instead of results.

        Inputs omitted from the returned mapping inherit ctx.

        May inspect upstream operator identity, but must NOT:
        - modify the graph;
        - initiate computation;
        - cause side effects.

        Called during request planning.
        """
        return {}

    @abstractmethod
    def compute(self, **bindings: Any) -> Any:
        """Compute output with upstream inputs replaced by results."""


def operator(fn: Callable[..., Any]) -> type[Operator]:
    """Wrap an ordinary function as an Operator class."""
    return type(
        fn.__name__,
        (Operator,),
        {
            "__module__": fn.__module__,
            "__doc__": fn.__doc__,
            "compute": staticmethod(fn),
        },
    )


def _copy(value: Any) -> Any:
    """Preserve Operator identity, copy ordinary parameter values."""
    return value if isinstance(value, Operator) else deepcopy(value)


def _inputs(bindings: Mapping[str, Any]) -> dict[str, Operator]:
    return {
        name: value
        for name, value in bindings.items()
        if isinstance(value, Operator)
    }


# ============================================================
# GRAPH
# ============================================================

@dataclass(frozen=True)
class GraphSnapshot:
    bindings: Mapping[Operator, Mapping[str, Any]]


class Graph:
    """Editable directed graph without observers or dirty state."""

    def __init__(self) -> None:
        self._bindings: dict[
            Operator, Mapping[str, Any]
        ] = {}

        self._dependents: dict[
            Operator, set[Operator]
        ] = {}

    def nodes(self) -> tuple[Operator, ...]:
        return tuple(self._bindings)

    def bindings(
        self,
        node: Operator,
    ) -> Mapping[str, Any]:
        """Return detached, read-only bindings."""
        self._require(node)

        return MappingProxyType({
            name: _copy(value)
            for name, value in self._bindings[node].items()
        })

    def _require(self, node: Operator) -> None:
        if node not in self._bindings:
            raise ValueError("Operator is not in this graph")

    def add(
        self,
        node: Operator,
        **bindings: Any,
    ) -> Operator:
        """Register an existing operator with initial bindings."""
        if not isinstance(node, Operator):
            raise TypeError(
                "graph.add() expects an Operator instance"
            )

        if node in self._bindings:
            raise ValueError(
                "Operator is already in this graph"
            )

        record = {
            name: _copy(value)
            for name, value in bindings.items()
        }

        for source in _inputs(record).values():
            if source is node:
                raise ValueError("Self-dependency")

            self._require(source)

        self._bindings[node] = MappingProxyType(record)
        self._dependents[node] = set()

        for source in set(_inputs(record).values()):
            self._dependents[source].add(node)

        return node

    def _would_cycle(
        self,
        node: Operator,
        record: Mapping[str, Any],
    ) -> bool:
        """Check whether an upstream path leads back to node."""
        pending = list(_inputs(record).values())
        visited = set()

        while pending:
            current = pending.pop()

            if current is node:
                return True

            if current not in visited:
                visited.add(current)
                pending.extend(
                    _inputs(self._bindings[current]).values()
                )

        return False

    def _replace(
        self,
        node: Operator,
        record: dict[str, Any],
    ) -> None:
        before = set(
            _inputs(self._bindings[node]).values()
        )
        after = set(_inputs(record).values())

        for source in after:
            self._require(source)

        if self._would_cycle(node, record):
            raise ValueError(
                "Binding would create a graph cycle"
            )

        # Copy-on-write: old snapshots stay intact.
        self._bindings[node] = MappingProxyType(record)

        for source in before - after:
            self._dependents[source].discard(node)

        for source in after - before:
            self._dependents[source].add(node)

    def set(
        self,
        node: Operator,
        **changes: Any,
    ) -> None:
        self._require(node)

        if changes:
            record = dict(self._bindings[node])
            record.update({
                name: _copy(value)
                for name, value in changes.items()
            })
            self._replace(node, record)

    def unset(
        self,
        node: Operator,
        *names: str,
    ) -> None:
        self._require(node)

        if names:
            record = dict(self._bindings[node])

            for name in names:
                del record[name]

            self._replace(node, record)

    def remove(self, node: Operator) -> None:
        """Remove a node and disconnect its consumers."""
        self._require(node)

        for dependent in self._dependents[node]:
            record = {
                key: value
                for key, value in self._bindings[dependent].items()
                if value is not node
            }
            self._bindings[dependent] = MappingProxyType(record)

        for source in set(
            _inputs(self._bindings[node]).values()
        ):
            self._dependents[source].discard(node)

        del self._bindings[node]
        del self._dependents[node]

    def snapshot(self, root: Operator) -> GraphSnapshot:
        """Capture an upstream subgraph independently of later edits."""
        self._require(root)

        records: dict[
            Operator, Mapping[str, Any]
        ] = {}

        def visit(node: Operator) -> None:
            if node in records:
                return

            record = MappingProxyType({
                name: _copy(value)
                for name, value in self._bindings[node].items()
            })

            records[node] = record

            for source in _inputs(record).values():
                visit(source)

        visit(root)

        return GraphSnapshot(
            MappingProxyType(records)
        )


# ============================================================
# OBSERVABLE GRAPH
# ============================================================

@dataclass(frozen=True)
class GraphEvent:
    kind: str
    revision: int
    node: Operator
    affected: frozenset[Operator]


class ObservableGraph(Graph):
    """Graph with edit notifications and downstream invalidation."""

    def __init__(self) -> None:
        super().__init__()

        self.revision = 0

        self._invalidated: dict[
            Operator, int
        ] = {}

        self._listeners: list[
            Callable[[GraphEvent], None]
        ] = []

    def listen(
        self,
        callback: Callable[[GraphEvent], None],
    ) -> None:
        self._listeners.append(callback)

    def invalidated_at(self, node: Operator) -> int:
        self._require(node)
        return self._invalidated[node]

    def _affected(
        self,
        node: Operator,
    ) -> set[Operator]:
        """Collect the node and its downstream dependents."""
        affected = set()
        pending = [node]

        while pending:
            current = pending.pop()

            if current not in affected:
                affected.add(current)
                pending.extend(
                    self._dependents[current]
                )

        return affected

    def _notify(
        self,
        kind: str,
        node: Operator,
        affected: set[Operator],
    ) -> None:
        self.revision += 1

        for op in affected:
            if op in self._bindings:
                self._invalidated[op] = self.revision

        event = GraphEvent(
            kind,
            self.revision,
            node,
            frozenset(affected),
        )

        for callback in tuple(self._listeners):
            callback(event)

    def add(
        self,
        node: Operator,
        **bindings: Any,
    ) -> Operator:
        result = super().add(node, **bindings)
        self._notify("added", node, {node})
        return result

    def set(
        self,
        node: Operator,
        **changes: Any,
    ) -> None:
        super().set(node, **changes)

        if changes:
            self._notify(
                "changed",
                node,
                self._affected(node),
            )

    def unset(
        self,
        node: Operator,
        *names: str,
    ) -> None:
        super().unset(node, *names)

        if names:
            self._notify(
                "changed",
                node,
                self._affected(node),
            )

    def remove(self, node: Operator) -> None:
        self._require(node)

        # Capture downstream dependents before disconnecting.
        affected = self.    (node)

        super().remove(node)

        self._invalidated.pop(node, None)
        self._notify("removed", node, affected)


# ============================================================
# EXECUTION SCOPE
# ============================================================

@dataclass(frozen=True)
class ExecutionScope:
    job: Job
    node: Operator
    ctx: Context

    _current: ClassVar[
        ContextVar[ExecutionScope | None]
    ] = ContextVar(
        "execution_scope",
        default=None,
    )

    @classmethod
    def current(cls) -> ExecutionScope:
        scope = cls._current.get()

        if scope is None:
            raise RuntimeError("No active computation")

        return scope

    def input(self, name: str) -> Operator:
        """Retrieve an upstream operator from the Job snapshot."""
        value = self.job.snapshot.bindings[
            self.node
        ][name]

        if not isinstance(value, Operator):
            raise TypeError(
                f"{name!r} is not an upstream operator"
            )

        return value


# ============================================================
# JOB
# ============================================================

@dataclass
class _Entry:
    covered: Context
    value: Any  # Must implement merge() and select().


class Job:
    """Synchronous evaluation with a per-Job result cache."""

    def __init__(self, snapshot: GraphSnapshot) -> None:
        self.snapshot = snapshot

        self._cache: dict[
            Operator, _Entry
        ] = {}

        self._active: set[Operator] = set()
        self._requesting = False

    def _missing(
        self,
        node: Operator,
        ctx: Context,
    ) -> Context:
        entry = self._cache.get(node)

        return (
            ctx
            if entry is None
            else ctx.subtract(entry.covered)
        )

    def _get(
        self,
        node: Operator,
        ctx: Context,
    ) -> Any:
        entry = self._cache.get(node)

        if (
            entry is None
            or not self._missing(node, ctx).is_empty()
        ):
            raise RuntimeError(
                "Output is not available"
            )

        return entry.value.select(ctx)

    def _store(
        self,
        node: Operator,
        ctx: Context,
        result: Any,
    ) -> None:
        entry = self._cache.get(node)

        if entry is None:
            self._cache[node] = _Entry(ctx, result)
        else:
            entry.value = entry.value.merge(result)
            entry.covered = entry.covered.union(ctx)

    def _upstream_of(
        self,
        candidate: Operator,
        caller: Operator,
    ) -> bool:
        """Verify an on-demand request follows existing graph edges."""
        pending = list(
            _inputs(
                self.snapshot.bindings[caller]
            ).values()
        )

        visited = set()

        while pending:
            current = pending.pop()

            if current is candidate:
                return True

            if current not in visited:
                visited.add(current)
                pending.extend(
                    _inputs(
                        self.snapshot.bindings[current]
                    ).values()
                )

        return False

    def _plan(
        self,
        root: Operator,
        wanted: Context,
    ):
        order: list[Operator] = []
        visited = set()

        def visit(node: Operator) -> None:
            if node in visited:
                return

            visited.add(node)

            for source in _inputs(
                self.snapshot.bindings[node]
            ).values():
                visit(source)

            order.append(node)

        # Build upstream-first topological order.
        visit(root)

        demand = {root: wanted}

        pending: dict[
            Operator, Context
        ] = {}

        requests: dict[
            Operator, dict[str, Context]
        ] = {}

        # Plan downstream -> upstream, combining requests
        # before executing any operator.
        for node in reversed(order):
            if node not in demand:
                continue

            ctx = self._missing(
                node,
                demand[node],
            )

            if ctx.is_empty() and node in self._cache:
                continue

            if node in self._active:
                raise RuntimeError(
                    "Recursive evaluation of active operator"
                )

            pending[node] = ctx
            record = self.snapshot.bindings[node]
            sources = _inputs(record)

            self._requesting = True

            try:
                overrides = node.request(
                    ctx,
                    **{
                        key: _copy(value)
                        for key, value in record.items()
                    },
                )
            finally:
                self._requesting = False

            if not isinstance(overrides, Mapping):
                raise TypeError(
                    "request() must return a mapping"
                )

            if set(overrides) - set(sources):
                raise ValueError(
                    "request() named a non-input binding"
                )

            requests[node] = {}

            for name, source in sources.items():
                required = overrides.get(name, ctx)

                if not isinstance(required, Context):
                    raise TypeError(
                        "Input request must be a Context"
                    )

                requests[node][name] = required

                if source in demand:
                    demand[source] = demand[source].union(
                        required
                    )
                else:
                    demand[source] = required

        return order, pending, requests

    def evaluate(
        self,
        node: Operator,
        ctx: Context,
    ) -> Any:
        """Ensure output is available for ctx, computing missing coverage."""
        if self._requesting:
            raise RuntimeError(
                "request() must not initiate computation"
            )

        if node not in self.snapshot.bindings:
            raise ValueError(
                "Operator is outside this Job's snapshot"
            )

        caller = ExecutionScope._current.get()

        if caller is not None and caller.job is self:
            if not self._upstream_of(node, caller.node):
                raise ValueError(
                    "On-demand evaluation must target "
                    "an upstream operator"
                )

        if node in self._active:
            raise RuntimeError(
                "Recursive evaluation of active operator"
            )

        if (
            node not in self._cache
            or not self._missing(node, ctx).is_empty()
        ):
            order, pending, requests = self._plan(
                node, ctx
            )

            # Execute upstream -> downstream.
            for op in order:
                if op not in pending:
                    continue

                record = self.snapshot.bindings[op]

                resolved = {
                    name: (
                        self._get(
                            value,
                            requests[op][name],
                        )
                        if isinstance(value, Operator)
                        else _copy(value)
                    )
                    for name, value in record.items()
                }

                token = ExecutionScope._current.set(
                    ExecutionScope(
                        self,
                        op,
                        pending[op],
                    )
                )

                self._active.add(op)

                try:
                    output = op.compute(**resolved)
                    self._store(
                        op,
                        pending[op],
                        output,
                    )
                finally:
                    self._active.remove(op)
                    ExecutionScope._current.reset(token)

        return self._get(node, ctx)


# ============================================================
# ENGINE
# ============================================================

class Engine:
    def evaluate(
        self,
        graph: Graph,
        root: Operator,
        ctx: Context,
    ) -> Any:
        return Job(
            graph.snapshot(root)
        ).evaluate(root, ctx)


# ============================================================
# EXAMPLE: FRAME CONTEXT
# ============================================================

@dataclass(frozen=True)
class FrameContext(Context):
    frames: frozenset[int] = frozenset()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "frames",
            frozenset(self.frames),
        )

    def union(
        self,
        other: FrameContext,
    ) -> FrameContext:
        return FrameContext(
            self.frames | other.frames
        )

    def intersection(
        self,
        other: FrameContext,
    ) -> FrameContext:
        return FrameContext(
            self.frames & other.frames
        )

    def subtract(
        self,
        other: FrameContext,
    ) -> FrameContext:
        return FrameContext(
            self.frames - other.frames
        )

    def is_empty(self) -> bool:
        return not self.frames


# ============================================================
# EXAMPLE: VIDEO RESULT
# ============================================================

@dataclass(frozen=True)
class Video:
    """Example result implementing merge() and select()."""

    frames: Mapping[int, np.ndarray]

    def __post_init__(self) -> None:

        def readonly(image: np.ndarray) -> np.ndarray:
            image = np.ascontiguousarray(image)

            return np.frombuffer(
                image.tobytes(),
                image.dtype,
            ).reshape(image.shape)

        object.__setattr__(
            self,
            "frames",
            MappingProxyType({
                frame: readonly(image)
                for frame, image in self.frames.items()
            }),
        )

    def merge(self, other: Video) -> Video:
        return Video({
            **self.frames,
            **other.frames,
        })

    def select(self, ctx: FrameContext) -> Video:
        return Video({
            frame: self.frames[frame]
            for frame in ctx.frames
            if frame in self.frames
        })


# ============================================================
# EXAMPLE OPERATORS
# ============================================================

class ReadVideo(Operator):

    def compute(self, *, count: int = 12) -> Video:
        frames = ExecutionScope.current().ctx.frames

        return Video({
            f: np.full(
                (2, 2),
                float(f),
                dtype=np.float32,
            )
            for f in frames
            if 0 <= f < count
        })


class TemporalBlend(Operator):

    def request(
        self,
        ctx: FrameContext,
        *,
        source: Operator,
        duration: int = 3,
    ) -> Mapping[str, Context]:
        return {
            "source": FrameContext({
                f - offset
                for f in ctx.frames
                for offset in range(duration)
            })
        }

    def compute(
        self,
        *,
        source: Video,
        duration: int = 3,
    ) -> Video:
        output = {}

        for f in ExecutionScope.current().ctx.frames:
            samples = [
                source.frames[f - i]
                for i in range(duration)
                if f - i in source.frames
            ]

            if samples:
                output[f] = np.mean(
                    np.stack(samples),
                    axis=0,
                )

        return Video(output)


@operator
def DynamicLookback(
    source: Video,
    lookback: int = 1,
) -> Video:
    scope = ExecutionScope.current()
    output = {}

    for frame in scope.ctx.frames:
        previous = frame - lookback

        older = scope.job.evaluate(
            scope.input("source"),
            FrameContext({previous}),
        )

        if (
            frame in source.frames
            and previous in older.frames
        ):
            output[frame] = (
                source.frames[frame]
                + older.frames[previous]
            ) / 2

    return Video(output)


@operator
def Gain(
    source: Video,
    factor: float = 2.0,
) -> Video:
    return Video({
        f: image * factor
        for f, image in source.frames.items()
    })


# ============================================================
# EXAMPLE GRAPH
# ============================================================

if __name__ == "__main__":

    graph = ObservableGraph()

    graph.listen(
        lambda event: print(
            event.kind,
            event.revision,
            len(event.affected),
        )
    )

    read = graph.add(ReadVideo(), count=12)

    blend = graph.add(
        TemporalBlend(),
        source=read,
        duration=3,
    )

    lookback = graph.add(
        DynamicLookback(),
        source=blend,
        lookback=1,
    )

    gain = graph.add(
        Gain(),
        source=lookback,
        factor=2.0,
    )

    result = Engine().evaluate(
        graph,
        gain,
        FrameContext({5}),
    )

    print("Frame 5:", result.frames[5][0, 0])

    graph.set(read, count=20)

    print(
        "Gain invalidated at revision:",
        graph.invalidated_at(gain),
    )
