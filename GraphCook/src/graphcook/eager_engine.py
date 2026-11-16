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
from .core.graph import descendants, topological_sort
from .observable_graph import ObservableGraph, GraphChange

from dataclasses import dataclass

class EagerScriptProvider(OperatorProvider):
    def __init__(self, script: str) -> None:
        self._script = script
        self._functions: dict[str, Callable[..., Any]] = dict()
        self._exec()

    def _exec(self) -> None:
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
        namespace: dict[str, Any] = {}
        exec(script, namespace)
        functions = {
            name: value for name, value in namespace.items()
            if callable(value)
        }
        self._script = script
        self._functions = functions

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
    value: Any
    duration_seconds: float | None = None


@dataclass(frozen=True)
class FailedState:
    reason: Exception


type NodeState = DirtyState | RunningState | SucceededState | FailedState


from typing import TypedDict

class InletSignature(TypedDict):
    """Public inlet information."""
    type: Any
    default: Any

class OperatorSignature(TypedDict):
    """Public operator information."""
    name: str
    inlets: dict[str, InletSignature] # todo: move this to the operator's signature

class EagerNodeSignature(TypedDict):
    """Public node information, without computed results."""
    operator: OperatorSignature
    inputs: dict[str, Any]

    
from .graph_index import GraphAttributeIndex


class EagerEngine:
    def __init__(self, script: str) -> None:
        self._closed = True
        self._graph = ObservableGraph[NodeId]()
        self._provider = EagerScriptProvider(script)
        self._cache = MemoryCache[NodeId, Any]()
        self._listeners: list[Callable[[EagerEngineChange], None]] = []

        self._operator_index = GraphAttributeIndex[NodeId, OperatorHandle](
            self._graph, OPERATOR_ATTRIBUTE, OperatorHandle
        )

        self._unsubscribe_graph = self._graph.listen(self._handle_graph_change)
        self._unsubscribe_provider = self._provider.listen(self._handle_provider_change)

        self._effects:list[NodeId] = []
        self._closed = False

    def _notify(self, change: EagerEngineChange) -> None:
        for listener in tuple(self._listeners):
            listener(change)

    def _notify_state(self, node: NodeId, state: NodeState) -> None:
        """Publish transient execution state; the previous state is unknown."""
        self._notify(EagerEngineChange(
            graph=GraphChange(attributes={
                node: MappingChanges(changed={
                    "state": ValueChange(old=None, new=state)
                })
            }),
            script=None,
        ))

    def listen(self, callback: Callable[[EagerEngineChange], None]) -> Callable[[], None]:
        self._listeners.append(callback)

        def unsubscribe() -> None:
            self._listeners.remove(callback)

        return unsubscribe

    def _handle_graph_change(self, change: GraphChange) -> None:
        # forward graph changes
        self._notify(EagerEngineChange(graph=change, script=None))
        self._operator_index.update(change)
        dirty = set(change.nodes.added) | set(change.nodes.removed)
        dirty.update(change.attributes)
        dirty.update(link.target for link in change.links.added)
        dirty.update(link.target for link in change.links.removed)
        self.invalidate(dirty)

    def _resolve_graph(self, *roots: NodeId) -> Graph[NodeId]:
        nodes = topological_sort(self._graph, *roots)
        resolved_graph = Graph[NodeId]()
        for node in nodes:
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

        for node in nodes:
            for link in self._graph.in_links(node):
                resolved_graph.add_link(link.source, link.target, link.inlet)

        return resolved_graph

    def evaluate(self, *nodes: NodeId) -> None:
        """Publish results as events and stop on the first evaluation failure."""
        if not nodes:
            raise ValueError("At least one node must be provided")

        requested = tuple(dict.fromkeys(nodes))
        live_nodes = set(self._graph.nodes())
        for node in requested:
            if node not in live_nodes:
                raise ValueError(f"Root is not in graph: {node!r}")

        try:
            resolved_graph = self._resolve_graph(*requested)
        except (ValueError, UnresolvedOperatorError) as exc:
            for node in requested:
                self._notify_state(node, FailedState(reason=exc))
            return

        memo: dict[NodeId, Any] = {}
        for current in topological_sort(resolved_graph, *requested):
            if current in self._cache:
                memo[current] = self._cache[current]
                if current in requested:
                    self._notify_state(current, SucceededState(value=memo[current]))
                continue

            attributes = resolved_graph.attributes(current)
            kwargs = attributes['kwargs']
            assert isinstance(kwargs, dict)
            # Links are authoritative for connected inputs, including after
            # a connection represented by a NodeId attribute is removed.
            resolved_kwargs = {
                key: value for key, value in kwargs.items()
                if not isinstance(value, NodeId)
            }
            for link in resolved_graph.in_links(current):
                resolved_kwargs[link.inlet] = memo[link.source]

            resolved_operator = attributes['operator']
            assert callable(resolved_operator)
            self._notify_state(current, RunningState())
            try:
                result = resolved_operator(**resolved_kwargs)
            except Exception as exc:
                self._notify_state(current, FailedState(reason=exc))
                downstream = descendants(resolved_graph, current)
                for node in requested:
                    if node in downstream:
                        self._notify_state(node, FailedState(reason=exc))
                # Stop processing further nodes
                # if an exception occurs for the current node.
                return

            memo[current] = result
            self._cache.save(current, result)
            self._notify_state(current, SucceededState(value=result))

    # read graph
    def nodes(self) -> tuple[NodeId, ...]:
        return self._graph.nodes()

    def attributes(self, node: NodeId) -> EagerNodeSignature:
        attributes = self._graph.attributes(node)
        operator = attributes[OPERATOR_ATTRIBUTE]
        assert isinstance(operator, OperatorHandle)
        
        
        # inputs.update({
        #     k: v 
        #     for k, v in attributes.items() 
        #     if k != OPERATOR_ATTRIBUTE
        # })

        
        inlets:dict[str, InletSignature] = dict()
        inputs:dict[str, Any] = dict()
        for k, v in inputs.items():
            inlets[k] = InletSignature(
                type=type(v), 
                default=inspect.Parameter.empty
            )
            inputs[k] = v

        # collect inlets from the operator's signature
        if operator is not None:
            eager_provider = cast(EagerScriptProvider, self._provider)
            func = eager_provider.resolve(operator)
            import inspect
            sig = inspect.signature(func)
            for param in sig.parameters.values():
                inlets[param.name] = InletSignature(
                    type=param.annotation,
                    default=param.default
                )

        # include any link target inlet, in case it was not already in the inputs
        for link in self._graph.in_links(node):
            if link.inlet not in inlets:
                inlets[link.inlet] = InletSignature(
                    type=Any,
                    default=inspect.Parameter.empty
                )
            inputs[link.inlet] = link.source

        return EagerNodeSignature(
            operator=OperatorSignature(
                name=operator.name,
                inlets=inlets
            ),
            inputs=inputs
        )

    def in_links(self, node: NodeId) -> Iterable[tuple[NodeId, NodeId, str]]:
        for link in self._graph.in_links(node):
            yield (link.source, link.target, link.inlet)

    def out_links(self, node: NodeId) -> Iterable[tuple[NodeId, NodeId, str]]:
        for link in self._graph.out_links(node):
            yield (link.source, link.target, link.inlet)

    def links(self) -> Iterable[tuple[NodeId, NodeId, str]]:
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

    def remove_link(self, source: 'NodeId', target: 'NodeId', inlet: str) -> None:
        self._graph.remove_link(source, target, inlet)

    # auto evaluate
    def effect(self, source: NodeId) -> None:
        if source not in self._graph.nodes():
            raise ValueError("Effect node is not in graph")
        self._effects.append(source)

    def remove_effect(self, source: NodeId) -> None:
        if source in self._effects:
            self._effects.remove(source)

    # read provider
    def operators(self) -> Iterable[OperatorHandle]:
        return self._provider.operators()

    # mutate provider
    def script(self) -> str:
        return self._provider.script()

    def set_script(self, script: str) -> None:
        old = self.script()
        if old == script:
            return
        self._provider.set_script(script)
        self._notify(EagerEngineChange(
            graph=None, 
            script=ValueChange(old=old, new=script)
        ))
        self.invalidate(self.nodes())

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
        self._effects = [node for node in self._effects if node in live_nodes]
        for node in affected & live_nodes:
            self._notify_state(node, DirtyState())

        effects = tuple(node for node in self._effects if node in affected)
        if effects:
            self.evaluate(*effects)

    def invalidate_hook(self, nodes: frozenset[NodeId]) -> None:
        for node in nodes:
            self._cache.remove(node)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._unsubscribe_graph()
        self._unsubscribe_provider()

    def __del__(self) -> None:
        self.close()
