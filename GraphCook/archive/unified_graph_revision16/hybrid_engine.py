"""Contextual hybrid operators, graph, Job, Engine and runnable example."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, ClassVar, Protocol, Self, runtime_checkable

from base_engine import (
    CacheProtocol, Engine, ExecutionResult, GraphProtocol, MemoryCache,
    ObservableGraph, ancestors, copy_graph, descendants, topological_sort,
)

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

def hybrid_operator(fn: Callable[..., ContextualResult]) -> type[HybridOperator]:
    return type(fn.__name__, (HybridOperator,), {
        '__module__': fn.__module__, '__doc__': fn.__doc__, 'compute': staticmethod(fn)
    })

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

@dataclass(frozen=True)
class CacheEntry:
    covered: Context
    value: ContextualResult


def merge_entry(entry: CacheEntry | None, result: ExecutionResult[HybridOperator, CacheEntry]) -> CacheEntry:
    portion = result.value
    if entry is None:
        return portion
    return CacheEntry(entry.covered.union(portion.covered), entry.value.merge(portion.value))

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

if __name__ == "__main__":
    graph = HybridGraph()
    read = graph.add(ReadVideo(), count=12)
    blend = graph.add(TemporalBlend(), source=read, duration=3)
    lookback = graph.add(DynamicLookback(), source=blend, lookback=1)
    gain = graph.add(Gain(), source=lookback, factor=2)
    engine = HybridEngine(graph, FrameContext({5}))
    engine.watch(gain, lambda result: print("Watched:", result.value.value.frames))
    engine.refresh()  # {5: 7.0}
    graph.set(gain, factor=3)
    engine.refresh()  # {5: 10.5}
