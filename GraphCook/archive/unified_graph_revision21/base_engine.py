"""Shared graph/provider change handling, invalidation and notifications.

Execution algorithms, Jobs and result caching belong to concrete engines.
"""
from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Generic, Literal, Protocol

from .graph import GraphChange, NodeT, ObservableGraph
from .graph_index import GraphAttributeIndex

OPERATOR_ATTRIBUTE = "__operator__"
UNSET = object()  # A computed result may legitimately be None.

from .provider import (
    OperatorHandle,
    OperatorProvider,
    ProviderChange,
)

@dataclass(frozen=True)
class EngineChange(Generic[NodeT]):
    """An event about execution or invalidation, not cache persistence."""
    kind: Literal["invalidated", "started", "executed", "failed", "cache_hit"]
    node: NodeT
    result: Any = UNSET
    error: BaseException | None = None


class BaseEngine(Generic[NodeT]):
    """Common observable graph/provider integration; no execution or cache policy."""

    def __init__(self, graph: ObservableGraph[NodeT], provider: OperatorProvider) -> None:
        self.graph = graph
        self._provider = provider
        self._listeners: list[Callable[[EngineChange[NodeT]], None]] = []
        self._operator_index = GraphAttributeIndex(graph, OPERATOR_ATTRIBUTE, OperatorHandle)
        self._unlisten_graph = graph.listen(self._handle_graph_change)
        self._unlisten_provider = provider.listen(self._handle_provider_change)

    @property
    def provider(self) -> OperatorProvider:
        """Provider identity is fixed; its implementations may still refresh."""
        return self._provider

    def listen(self, callback: Callable[[EngineChange[NodeT]], None]) -> Callable[[], None]:
        self._listeners.append(callback)

        def unsubscribe() -> None:
            self._listeners.remove(callback)

        return unsubscribe

    def watch(self, node: NodeT,
              callback: Callable[[EngineChange[NodeT]], None]) -> Callable[[], None]:
        return self.listen(lambda change: callback(change) if change.node == node else None)

    def invalidate(self, nodes: Iterable[NodeT]) -> None:
        """Invalidate specified nodes and all descendants in the live graph."""
        queue = deque(nodes)
        live_nodes = set(self.graph.nodes())
        affected: set[NodeT] = set()
        while queue:
            node = queue.popleft()
            if node in affected:
                continue
            affected.add(node)
            if node in live_nodes:
                queue.extend(link.target for link in self.graph.out_links(node))
        if not affected:
            return

        # Subclasses discard any state they need to before observers hear about it.
        self.invalidate_hook(frozenset(affected))
        for node in affected:
            self._notify(EngineChange("invalidated", node))

    def invalidate_hook(self, nodes: frozenset[NodeT]) -> None:
        """Optional hook for engine-specific state (such as a cache)."""
        pass

    def _handle_graph_change(self, change: GraphChange[NodeT]) -> None:
        self._operator_index.update(change)
        dirty = set(change.nodes.added) | set(change.nodes.removed)
        dirty.update(change.attributes)
        dirty.update(link.target for link in change.links.added)
        dirty.update(link.target for link in change.links.removed)
        self.invalidate(dirty)

    def _handle_provider_change(self, change: ProviderChange) -> None:
        if change.unknown:
            self.invalidate(self.graph.nodes())
            return
        dirty: set[NodeT] = set()
        for handle in (*change.added, *change.removed, *change.changed):
            dirty.update(self._operator_index.nodes_with(handle))
        self.invalidate(dirty)

    def _notify(self, change: EngineChange[NodeT]) -> None:
        for callback in tuple(self._listeners):
            callback(change)

    def close(self) -> None:
        self._unlisten_graph()
        self._unlisten_provider()
