"""Synchronous eager execution, without a Job abstraction."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .base_engine import (
    BaseEngine, 
    EngineChange, 
    OPERATOR_ATTRIBUTE,
    OperatorHandle, 
    OperatorProvider, 
)
from .provider import UnresolvedOperatorError
from .cache import CacheProtocol, MemoryCache
from .graph import NodeT
from .observable_graph import ObservableGraph, GraphChange


class EagerProvider(OperatorProvider):
    """A simple eager operator provider."""

    def resolve(self, handle: OperatorHandle) -> Any:
        return handle.operator


class EagerEngine(BaseEngine[NodeT]):
    def __init__(self, graph: ObservableGraph[NodeT], provider: OperatorProvider,
                 cache: CacheProtocol[NodeT, Any] | None = None) -> None:
        super().__init__(graph, provider)
        self.cache: CacheProtocol[NodeT, Any] = cache if cache is not None else MemoryCache()
        self._cache_revisions: dict[NodeT, int] = {}
        self._revision_counter = 0

    def invalidate_hook(self, nodes: frozenset[NodeT]) -> None:
        self._revision_counter += 1
        for node in nodes:
            self._cache_revisions[node] = self._revision_counter
            self.cache.remove(node)

    def evaluate(self, node: NodeT) -> Any:
        graph = self.graph.snapshot()
        provider = self.provider.snapshot()
        cached = dict(self.cache)
        revisions = dict(self._cache_revisions)
        completed: dict[NodeT, Any] = {}
        visiting: set[NodeT] = set()

        def compute(current: NodeT) -> Any:
            if current in completed:
                return completed[current]
            if current in cached:
                result = cached[current]
                self._notify(EngineChange("cache_hit", current, result=result))
                return result
            if current in visiting:
                raise ValueError(f"Cycle detected at node {current!r}")

            visiting.add(current)
            try:
                arguments = dict(graph.attributes(current))
                handle = arguments.pop(OPERATOR_ATTRIBUTE, None)
                if not isinstance(handle, OperatorHandle):
                    raise UnresolvedOperatorError(
                        f"Node {current!r} has no valid {OPERATOR_ATTRIBUTE}"
                    )
                operator = provider.resolve(handle)
                for link in graph.in_links(current):
                    arguments[link.input] = compute(link.source)

                self._notify(EngineChange("started", current))
                result = operator(**arguments)
                completed[current] = result
                # Execution is reported when it happens, irrespective of caching.
                self._notify(EngineChange("executed", current, result=result))
                return result
            except Exception as exc:
                self._notify(EngineChange("failed", current, error=exc))
                raise
            finally:
                visiting.remove(current)

        try:
            return compute(node)
        finally:
            # Cache consistency is an EagerEngine concern, not a BaseEngine rule.
            live_nodes = set(self.graph.nodes())
            for finished, result in completed.items():
                if (finished in live_nodes and
                        self._cache_revisions.get(finished, 0) == revisions.get(finished, 0)):
                    self.cache.save(finished, result)
