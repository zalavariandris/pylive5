
"""Synchronous operator graph with post-edit change events.

Graph stores only bindings and topology.
ObservableGraph emits one GraphEvent per successful edit.
Each Job plans requests and caches completed context coverage.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Callable, ClassVar, Iterable, Mapping


# ============================================================
# CONTEXT AND OPERATOR
# ============================================================

class Context(ABC):
    """Immutable request coverage with user-defined set operations."""

    @abstractmethod
    def union(self, other: Context) -> Context: ...

    @abstractmethod
    def intersection(self, other: Context) -> Context: ...

    @abstractmethod
    def subtract(self, other: Context) -> Context: ...

    @abstractmethod
    def is_empty(self) -> bool: ...


class Operator(ABC):
    """An instance is one graph node; implementations should be stateless."""

    def request(
        self,
        ctx: Context,
        **bindings: Any,
    ) -> Mapping[str, Context]:
        """Describe upstream requirements.

        Receives the same named bindings as compute(), but
        upstream inputs are unresolved Operator instances.

        Inputs not mentioned in the returned mapping inherit ctx.

        May inspect upstream operator identity, but must NOT:
        - modify graph structure;
        - initiate computation;
        - produce side effects.

        Planning may call this method repeatedly.
        """
        return {}

    @abstractmethod
    def compute(self, **bindings: Any) -> Any:
        """Compute with Operator bindings replaced by results."""


def operator(fn: Callable[..., Any]) -> type[Operator]:
    """Turn a function into an Operator class."""
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
    """Preserve Operator identity and copy ordinary parameters."""
    return value if isinstance(value, Operator) else deepcopy(value)


def _inputs(
    bindings: Mapping[str, Any],
) -> dict[str, Operator]:
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
    """Editable graph without observers or dirty state."""

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

    def ancestors(self, node: Operator) -> set[Operator]:
        """All upstream operators, excluding node itself."""
        self._require(node)

        result = set()
        pending = list(
            _inputs(self._bindings[node]).values()
        )

        while pending:
            current = pending.pop()

            if current not in result:
                result.add(current)
                pending.extend(
                    _inputs(self._bindings[current]).values()
                )

        return result

    def descendants(self, node: Operator) -> set[Operator]:
        """All downstream operators, excluding node itself."""
        self._require(node)

        result = set()
        pending = list(self._dependents[node])

        while pending:
            current = pending.pop()

            if current not in result:
                result.add(current)
                pending.extend(self._dependents[current])

        return result

    def add(
        self,
        node: Operator,
        **bindings: Any,
    ) -> Operator:
        """Register an existing Operator with initial bindings."""
        if not isinstance(node, Operator):
            raise TypeError(
                "graph.add() expects an Operator instance"
            )

        if node in self._bindings:
            raise ValueError("Operator already in this graph")

        record = {
            name: _copy(value)
            for name, value in bindings.items()
        }

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

        # A cycle exists if a proposed upstream source
        # already has this node among its ancestors.
        if node in after or any(
            node in self.ancestors(source)
            for source in after
        ):
            raise ValueError(
                "Binding would create a graph cycle"
            )

        # Replace the record rather than modifying it.
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
        """Remove node and disconnect all incident links."""
        self._require(node)

        # Remove references to node from its consumers.
        for dependent in tuple(self._dependents[node]):
            record = {
                name: value
                for name, value in self._bindings[dependent].items()
                if value is not node
            }
            self._bindings[dependent] = MappingProxyType(record)

        # Remove node from its sources' dependent sets.
        for source in set(
            _inputs(self._bindings[node]).values()
        ):
            self._dependents[source].discard(node)

        del self._bindings[node]
        del self._dependents[node]

    def snapshot(self, root: Operator) -> GraphSnapshot:
        """Capture upstream bindings independently of later edits."""
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
# GRAPH EVENTS
# ============================================================

@dataclass(frozen=True)
class Link:
    source: Operator
    target: Operator
    input: str


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
    """Avoid reporting changes for identical bindings."""
    if a is b:
        return True

    if a is MISSING or b is MISSING:
        return False

    if isinstance(a, Operator) or isinstance(b, Operator):
        return False

    try:
        equal = a == b
        return equal if isinstance(equal, bool) else False
    except (TypeError, ValueError):
        return False


def _binding_changes(
    node: Operator,
    before: Mapping[str, Any], 
    after: Mapping[str, Any],
    names: Iterable[str] | None = None,
) -> tuple[
    tuple[Link, ...],
    tuple[Link, ...],
    tuple[ValueChange, ...],
]:
    """Describe changes to bindings as links or ordinary values."""
    added = []
    removed = []
    values = []

    names = (
        dict.fromkeys((*before, *after))
        if names is None
        else names
    )

    for name in names:
        old = before.get(name, MISSING)
        new = after.get(name, MISSING)

        if _same(old, new):
            continue

        if isinstance(old, Operator):
            removed.append(Link(old, node, name))

        if isinstance(new, Operator):
            added.append(Link(new, node, name))

        if (
            not isinstance(old, Operator)
            and not isinstance(new, Operator)
        ):
            values.append(
                ValueChange(node, name, old, new)
            )

        elif isinstance(old, Operator) and new is not MISSING:
            values.append(
                ValueChange(node, name, MISSING, new)
            )

        elif isinstance(new, Operator) and old is not MISSING:
            values.append(
                ValueChange(node, name, old, MISSING)
            )

    return tuple(added), tuple(removed), tuple(values)


# ============================================================
# OBSERVABLE GRAPH
# ============================================================

class ObservableGraph(Graph):
    """Graph with one post-edit event per successful mutation."""

    def __init__(self) -> None:
        super().__init__()
        self._listeners: list[
            Callable[[GraphEvent], None]
        ] = []

    def listen(
        self,
        callback: Callable[[GraphEvent], None],
    ) -> None:
        self._listeners.append(callback)

    def _notify(self, event: GraphEvent) -> None:
        for callback in tuple(self._listeners):
            callback(event)

    def add(
        self,
        node: Operator,
        **bindings: Any,
    ) -> Operator:
        result = super().add(node, **bindings)

        added, removed, values = _binding_changes(
            node,
            {},
            self.bindings(node),
        )

        self._notify(GraphEvent(
            added_nodes=(node,),
            added_links=added,
            removed_links=removed,
            changed_values=values,
        ))

        return result

    def set(
        self,
        node: Operator,
        **changes: Any,
    ) -> None:
        if not changes:
            return super().set(node)

        before = self.bindings(node)
        super().set(node, **changes)

        added, removed, values = _binding_changes(
            node,
            before,
            self.bindings(node),
            changes,
        )

        if added or removed or values:
            self._notify(GraphEvent(
                added_links=added,
                removed_links=removed,
                changed_values=values,
            ))

    def unset(
        self,
        node: Operator,
        *names: str,
    ) -> None:
        if not names:
            return super().unset(node)

        before = self.bindings(node)
        super().unset(node, *names)

        added, removed, values = _binding_changes(
            node,
            before,
            self.bindings(node),
            names,
        )

        if added or removed or values:
            self._notify(GraphEvent(
                added_links=added,
                removed_links=removed,
                changed_values=values,
            ))

    def remove(self, node: Operator) -> None:
        self._require(node)

        # Capture incoming links.
        links = [
            Link(source, node, name)
            for name, source in _inputs(
                self._bindings[node]
            ).items()
        ]

        # Capture outgoing links, including multiple
        # named inputs connecting the same two nodes.
        for dependent in self._dependents[node]:
            links.extend(
                Link(node, dependent, name)
                for name, source in _inputs(
                    self._bindings[dependent]
                ).items()
                if source is node
            )

        super().remove(node)

        # One event represents the complete removal.
        self._notify(GraphEvent(
            removed_nodes=(node,),
            removed_links=tuple(links),
        ))


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
        """Get an upstream Operator from the Job snapshot."""
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
    value: Any  # Implements merge(other) and select(context).


class Job:
    """Synchronous evaluation with per-Job coverage caching."""

    def __init__(self, snapshot: GraphSnapshot) -> None:
        self.snapshot = snapshot
        self._cache: dict[Operator, _Entry] = {}
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
            raise RuntimeError("Output is not available")

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
        """Check upstream reachability in the immutable snapshot."""
        pending = list(
            _inputs(
                self.snapshot.bindings[caller]
            ).values()
        )

        visited = set()

        while pending:
            node = pending.pop()

            if node is candidate:
                return True

            if node not in visited:
                visited.add(node)
                pending.extend(
                    _inputs(
                        self.snapshot.bindings[node]
                    ).values()
                )

        return False

    def _plan(
        self,
        root: Operator,
        wanted: Context,
    ):
        order = []
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

        # First establish upstream-first topological order.
        visit(root)

        demand = {root: wanted}
        pending: dict[Operator, Context] = {}

        requests: dict[
            Operator, dict[str, Context]
        ] = {}

        # Then propagate requirements downstream -> upstream.
        # This merges shared requests before executing anything.
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
                        name: _copy(value)
                        for name, value in record.items()
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
        """Ensure output is available, computing only missing coverage."""
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
                    "On-demand evaluation must target upstream"
                )

        # Reuse any fully completed output.
        if (
            node in self._cache
            and self._missing(node, ctx).is_empty()
        ):
            return self._get(node, ctx)

        if node in self._active:
            raise RuntimeError(
                "Recursive evaluation of active operator"
            )

        order, pending, requests = self._plan(node, ctx)

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
                result = op.compute(**resolved)

                self._store(
                    op,
                    pending[op],
                    result,
                )

            finally:
                self._active.remove(op)
                ExecutionScope._current.reset(token)

        return self._get(node, ctx)


class Engine:
    """Top-level evaluation entry point."""

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
    """Simple frame-to-value result; not part of the generic engine."""

    frames: Mapping[int, Any]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "frames",
            MappingProxyType(dict(self.frames)),
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

    def compute(self, count: int = 12) -> Video:
        frames = ExecutionScope.current().ctx.frames

        return Video({
            frame: float(frame)
            for frame in frames
            if 0 <= frame < count
        })


class TemporalBlend(Operator):

    def request(
        self,
        ctx: FrameContext,
        source: Operator,
        duration: int = 3,
    ) -> Mapping[str, Context]:
        return {
            "source": FrameContext({
                frame - offset
                for frame in ctx.frames
                for offset in range(duration)
            })
        }

    def compute(
        self,
        source: Video,
        duration: int = 3,
    ) -> Video:
        output = {}

        for frame in ExecutionScope.current().ctx.frames:
            samples = [
                source.frames[frame - offset]
                for offset in range(duration)
                if frame - offset in source.frames
            ]

            if samples:
                output[frame] = sum(samples) / len(samples)

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
        frame: value * factor
        for frame, value in source.frames.items()
    })


# ============================================================
# EXAMPLE GRAPH
# ============================================================

if __name__ == "__main__":
    graph = ObservableGraph()

    graph.listen(print)

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

    print("Frame 5:", result.frames[5])
    # 7.0

    graph.set(gain, factor=3.0)
    # Event: one changed_values entry.

    graph.unset(gain, "source")
    # Event: one removed_links entry.
