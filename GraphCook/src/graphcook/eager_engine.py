"""Synchronous eager execution, without a Job abstraction."""
from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from typing import Any, Callable, Iterable, Literal, cast
from .core.changes import MappingChanges, ValueChange, SetChanges

from .core.base_engine import (
    BaseEngine, 
    OPERATOR_ATTRIBUTE,
    OperatorHandle, 
    OperatorProvider, 
)
from .provider import UnresolvedOperatorError
from .core.cache import CacheProtocol, MemoryCache
from .core.graph import Graph, GraphProtocol, NodeT
from .core.graph import topological_sort
from .observable_graph import ObservableGraph, GraphChange

from dataclasses import dataclass

class EagerScriptProvider(OperatorProvider):
    def __init__(self, script: str):
        self._script = script
        self._functions: dict[str, Callable[..., Any]] = dict()
        self._exec()

    def _exec(self):
        namespace = {}
        exec(self._script, namespace)
        self._functions = {k: v for k, v in namespace.items() if callable(v)}

    def operators(self) -> Iterable[OperatorHandle]:
        return [OperatorHandle(name) for name in self._functions]

    def resolve(self, handle: OperatorHandle) -> Any:
        try:
            return self._functions[handle.name]
        except KeyError:
            raise ValueError(f"Function for handle {handle} not found.")

    def get_operator_by_name(self, name: str) -> OperatorHandle:
        return OperatorHandle(name)

    def set_script(self, script: str) -> None:
        self._script = script
        self._exec()

    def script(self) -> str:
        return self._script

    def listen(self, callback: Callable[[ProviderChange], None]) -> Callable[[], None]: 
        return lambda: None

@dataclass(frozen=True)
class ProviderChange:
    added: tuple[OperatorHandle, ...] = ()
    removed: tuple[OperatorHandle, ...] = ()
    changed: tuple[OperatorHandle, ...] = ()
    unknown: bool = False

from dataclasses import dataclass

@dataclass(frozen=True)
class NodeId:
    id: str


from dataclasses import dataclass

@dataclass(frozen=True)
class EagerEngineChange:
    graph: GraphChange|None
    script: ValueChange|None


@dataclass(frozen=True)
class DirtyState:
    pass


@dataclass(frozen=True)
class RunningState:
    progress: float | None = None  # 0–1; None means unknown


@dataclass(frozen=True)
class SucceededState:
    duration_seconds: float | None = None


@dataclass(frozen=True)
class FailedState:
    error: Exception


type NodeState = DirtyState | RunningState | SucceededState | FailedState


from typing import TypedDict

class NodeSignature(TypedDict):
    """Public node information, without computed results."""
    operator: OperatorHandle
    inlets: tuple[str, ...]
    state: NodeState
    
from .graph_index import GraphAttributeIndex

class EagerEngine:
    def __init__(self, script:str):
        self._graph = ObservableGraph[NodeId]()
        self._provider = EagerScriptProvider(script)
        self._cache = MemoryCache[NodeId, Any]()
        self._listeners: list[Callable[[EagerEngineChange], None]] = []

        self._operator_index = GraphAttributeIndex(self._graph, 'operator', OperatorHandle)

        self._unsubscribe_graph = self._graph.listen(self._handle_graph_change)
        self._unsubscribe_provider = self._provider.listen(self._handle_provider_change)

    def _notify(self, change: EagerEngineChange) -> None:
        for listener in self._listeners:
            listener(change)

    def listen(self, callback: Callable[[EagerEngineChange], None]) -> Callable[[], None]:
        self._listeners.append(callback)

        def unsubscribe() -> None:
            self._listeners.remove(callback)

        return unsubscribe

    def watch(self, node: NodeT, callback: Callable[[EagerEngineChange[NodeId]], None]) -> Callable[[], None]:
        return self.listen(lambda change: callback(change) if change.node == node else None)

    def _handle_graph_change(self, change: GraphChange) -> None:
        # forward graph changes
        self._notify(EagerEngineChange(graph=change, script=None))
        self._operator_index.update(change)
        dirty = set(change.nodes.added) | set(change.nodes.removed)
        dirty.update(change.attributes)
        dirty.update(link.target for link in change.links.added)
        dirty.update(link.target for link in change.links.removed)
        self.invalidate(dirty)

    def _resolve_graph(self) -> Graph[NodeId]:
        resolved_graph = Graph[NodeId]()
        for node in self._graph.nodes():
            operator_handle = self._graph.attributes(node)[OPERATOR_ATTRIBUTE]
            assert isinstance(operator_handle, OperatorHandle)
            resolved_operator = self._provider.resolve(operator_handle)
            resolved_graph.add_node(
                node,
                operator = resolved_operator,
                kwargs = {
                    k: v 
                    for k, v in self._graph.attributes(node).items()
                    if k!=OPERATOR_ATTRIBUTE
                }
            )

        for src, dst, inlet in self._graph.links():
            assert isinstance(src, NodeId)
            assert isinstance(dst, NodeId)
            assert isinstance(inlet, str)
            resolved_graph.add_link(src, dst, inlet)

        return resolved_graph

    def evaluate(self, node: NodeId) -> Any:
        # resolve the graph, basically create a static graph, with real functions
        
        resolved_graph = self._resolve_graph()


        memo:dict[NodeId, Any] = dict()        
        for current in topological_sort(resolved_graph, node):
            if current in self._cache:
                memo[current] = self._cache[current]

            # resolve kwargs from memo
            kwargs = resolved_graph.attributes(current)['kwargs']
            assert isinstance(kwargs, dict)
            resolved_kwargs = {
                k: memo[v] if isinstance(v, NodeId) else v
                for k, v in kwargs.items()
            }

            # get operator from node attribute
            resolved_operator = resolved_graph.attributes(current)['operator']
            assert callable(resolved_operator)

            self._notify(EagerEngineChange("started", current))
            try:
                result = resolved_operator(**resolved_kwargs)
                self._notify(EagerEngineChange("executed", current, result=result))
                
            except Exception as exc:
                self._notify(EagerEngineChange("failed", current, error=exc))
                raise exc
            else:
                memo[current] = result
                self._cache.save(current, result)

    # read graph
    def nodes(self) -> tuple[NodeId, ...]:
        return self._graph.nodes()

    def attributes(self, node: NodeId) -> NodeSignature:
        attributes = self._graph.attributes(node)
        operator: OperatorHandle|None = attributes.get(OPERATOR_ATTRIBUTE)
        inputs: dict = {
            k: v 
            for k, v in attributes.items() 
            if k != OPERATOR_ATTRIBUTE
        }

        inlets = []
        for k in inputs.keys():
            inlets.append(k)
        # resolve the operator
        if operator is not None:
            eager_provider = cast(EagerScriptProvider, self._provider)
            func = eager_provider.resolve(operator)
            import inspect
            sig = inspect.signature(func)
            for param in sig.parameters.values():
                inlets.append(param.name)

        return NodeSignature(
            operator=operator,
            inlets=inlets
        )

    def in_links(self, node: NodeId) -> Iterable[(NodeId, NodeId, str)]:
        for link in self._graph.in_links(node):
            yield (link.source, link.target, link.inlet)

    def out_links(self, node: NodeId) -> Iterable[(NodeId, NodeId, str)]:
        for link in self._graph.out_links(node):
            yield (link.source, link.target, link.inlet)

    def links(self) -> Iterable[(NodeId, NodeId, str)]:
        for link in self._graph.links():
            yield (link.source, link.target, link.inlet)

    # mutate graph
    def node(self, funcname, **kwargs)->NodeId:
        # generate random_id for node
        import uuid
        node_id = NodeId(str(uuid.uuid4()))
        self._graph.add_node(
            node_id, 
            **{OPERATOR_ATTRIBUTE: OperatorHandle(funcname)},
            **kwargs
        )
        for inlet, src in kwargs.items():
            if isinstance(src, NodeId):
                self._graph.add_link(src, node_id, inlet)

        return node_id

    def delete(self, node: NodeId) -> None:
        self._graph.remove_node(node)

    def set(self, node: NodeId, **attributes: object) -> None:
        ...

    def unset(self, node: NodeId, name: str) -> None:
        ...

    def add_link(self, src: NodeId, dst: NodeId, inlet: str) -> None:
        self._graph.add_link(src, dst, inlet)

    def remove_link(
        self,
        src: NodeId,
        dst: NodeId,
        inlet: str,
    ) -> None:
        self._graph.remove_link(src, dst, inlet)

    # read provider
    def operators(self) -> Iterable[OperatorHandle]:
        return self._provider.operators()

    # mutate provider
    def script(self) -> str:
        return self._provider._script

    def set_script(self, script: str) -> None:
        self._script = script
        self._notify(EagerEngineChange(
            graph=None, 
            script=ValueChange(old=None, new=script)
        ))

    def _handle_provider_change(self, change: ProviderChange) -> None:
        if change.unknown:
            self.invalidate(self._graph.nodes())
            return
        dirty: set[NodeId] = set()
        for handle in (*change.added, *change.removed, *change.changed):
            dirty.update(self._operator_index.nodes_with(handle))
        self.invalidate(dirty)
    
    # executor
    def invalidate(self, nodes: Iterable[NodeId]) -> None:
        """Invalidate specified nodes and all descendants in the live graph."""
        queue = deque(nodes)
        live_nodes = set(self._graph.nodes())
        affected: set[NodeId] = set()
        while queue:
            node = queue.popleft()
            if node in affected:
                continue
            affected.add(node)
            if node in live_nodes:
                queue.extend(link.target for link in self._graph.out_links(node))
        if not affected:
            return

        # Subclasses discard any state they need to before observers hear about it.
        self.invalidate_hook(frozenset(affected))
        for node in affected:
            self._notify(EagerEngineChange(
                graph=GraphChange(
                    attributes={
                        node: MappingChanges(
                            changed={
                                'state': ValueChange(
                                    old=None,
                                    new=DirtyState()
                                )
                            }
                        )
                    }
                ),
                script=None
            ))

    def invalidate_hook(self, nodes: frozenset[NodeId]) -> None:
        for node in nodes:
            self._cache.remove(node)
    
    def close(self) -> None:
        self._unsubscribe_graph()
        self._unsubscribe_provider()

    def __del__(self) -> None:
        self.close()
