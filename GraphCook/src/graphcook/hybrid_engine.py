"""Hybrid execution: demand planning and context-aware on-demand computation.

The Job is specific to this strategy; BaseEngine does not know Jobs exist.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Generic, Literal, Protocol, Self

from .base_engine import (BaseEngine, EngineChange, OPERATOR_ATTRIBUTE,
                         OperatorHandle, OperatorProvider, ProviderSnapshot, UNSET,
                         UnresolvedOperatorError)
from .cache import CacheProtocol, MemoryCache
from .graph import Graph, NodeT, ObservableGraph


class Context(Protocol):
    def merge(self, other: Self) -> Self: ...


class ContextualValue(Protocol):
    def select(self, context: Context) -> Self: ...
    def merge(self, other: Self) -> Self: ...


class HybridOperator(Protocol):
    def request(self, context: Context, /, **parameters: Any) -> Mapping[str, Context]: ...
    def compute(self, context: Context,
                get: Callable[[str, Context], ContextualValue],
                /, **parameters: Any) -> ContextualValue: ...


@dataclass(frozen=True, kw_only=True)
class JobEvent(EngineChange[NodeT]):
    """Hybrid-specific execution event with a correlation ID."""
    job_id: int


class HybridJob(Generic[NodeT]):
    def __init__(self, graph: Graph[NodeT], provider: ProviderSnapshot,
                 cached: Mapping[NodeT, Any], job_id: int,
                 callback: Callable[[JobEvent[NodeT]], None]) -> None:
        self.graph = graph
        self.provider = provider
        self.cached = dict(cached)
        self.job_id = job_id
        self.completed: dict[NodeT, Any] = {}
        self._callback = callback
        self.requested: dict[NodeT, Context] = {}
        self._planning: set[NodeT] = set()
        self._computing: set[NodeT] = set()

    def _report(self, kind: Literal["started", "executed", "failed", "cache_hit"],
                node: NodeT, *, result: Any = UNSET,
                error: BaseException | None = None) -> None:
        self._callback(JobEvent(kind, node, result, error, job_id=self.job_id))

    def run(self, node: NodeT, context: Context) -> ContextualValue:
        self._plan(node, context)
        return self._pull(node, context)

    def _plan(self, node: NodeT, context: Context) -> None:
        if node in self._planning:
            raise ValueError(f"Cycle detected during request at {node!r}")
        previous = self.requested.get(node)
        combined = context if previous is None else previous.merge(context)
        if previous is not None and combined == previous:
            return
        self.requested[node] = combined
        self._planning.add(node)
        try:
            try:
                attributes = dict(self.graph.attributes(node))
                handle = attributes.pop(OPERATOR_ATTRIBUTE, None)
                if not isinstance(handle, OperatorHandle):
                    raise UnresolvedOperatorError(
                        f"Node {node!r} has no valid {OPERATOR_ATTRIBUTE}"
                    )
                operator: HybridOperator = self.provider.resolve(handle)
                demands = operator.request(combined, **attributes)
            except Exception as exc:
                self._report("failed", node, error=exc)
                raise
            inputs = {link.inlet: link.source for link in self.graph.in_links(node)}
            for name, demanded_context in demands.items():
                if name not in inputs:
                    error = KeyError(f"Unconnected requested input {name!r} on {node!r}")
                    self._report("failed", node, error=error)
                    raise error
                self._plan(inputs[name], demanded_context)
        finally:
            self._planning.remove(node)

    def _pull(self, node: NodeT, context: Context) -> ContextualValue:
        existing = self.completed.get(node, self.cached.get(node, UNSET))
        if existing is not UNSET:
            try:
                selected = existing.select(context)
            except KeyError:
                pass
            else:
                self._report("cache_hit", node, result=selected)
                return selected

        # Support additional demands discovered dynamically in compute().
        self._plan(node, context)
        if node in self._computing:
            raise ValueError(f"Cycle detected during compute at {node!r}")
        self._computing.add(node)
        try:
            attributes = dict(self.graph.attributes(node))
            handle = attributes.pop(OPERATOR_ATTRIBUTE, None)
            if not isinstance(handle, OperatorHandle):
                raise UnresolvedOperatorError(
                    f"Node {node!r} has no valid {OPERATOR_ATTRIBUTE}"
                )
            operator: HybridOperator = self.provider.resolve(handle)
            inputs = {link.inlet: link.source for link in self.graph.in_links(node)}

            def get(input_name: str, wanted: Context) -> ContextualValue:
                if input_name not in inputs:
                    raise KeyError(f"Unconnected input {input_name!r} on {node!r}")
                return self._pull(inputs[input_name], wanted)

            self._report("started", node)
            fresh = operator.compute(self.requested[node], get, **attributes)
            result = fresh if existing is UNSET else existing.merge(fresh)
            selected = result.select(context)
            self.completed[node] = result
            self._report("executed", node, result=result)
            return selected
        except Exception as exc:
            self._report("failed", node, error=exc)
            raise
        finally:
            self._computing.remove(node)


class HybridEngine(BaseEngine[NodeT]):
    def __init__(self, graph: ObservableGraph[NodeT], provider: OperatorProvider,
                 cache: CacheProtocol[NodeT, Any] | None = None) -> None:
        super().__init__(graph, provider)
        self.cache: CacheProtocol[NodeT, Any] = cache if cache is not None else MemoryCache()
        self._cache_revisions: dict[NodeT, int] = {}
        self._revision_counter = 0
        self._next_job_id = 1

    def invalidate_hook(self, nodes: frozenset[NodeT]) -> None:
        self._revision_counter += 1
        for node in nodes:
            self._cache_revisions[node] = self._revision_counter
            self.cache.remove(node)

    def evaluate(self, node: NodeT, context: Context) -> ContextualValue:
        job_id = self._next_job_id
        self._next_job_id += 1
        revisions = dict(self._cache_revisions)
        job = HybridJob(
            graph=self.graph.snapshot(),
            provider=self.provider.snapshot(),
            cached=dict(self.cache),
            job_id=job_id,
            callback=self._notify,
        )
        try:
            return job.run(node, context)
        finally:
            live_nodes = set(self.graph.nodes())
            for finished, result in job.completed.items():
                if (finished in live_nodes and
                        self._cache_revisions.get(finished, 0) == revisions.get(finished, 0)):
                    self.cache.save(finished, result)
