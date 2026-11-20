"""Synchronous eager execution, without a Job abstraction."""
from __future__ import annotations
import queue
import threading
import time
from typing import Annotated, Generic, Hashable, Iterator, TypeVar
import inspect
from collections import deque
from collections.abc import Mapping
from typing import Any, Callable, Iterable, Literal, cast
from dataclasses import dataclass

from myutils.source_diff import collect_functions, FunctionsDiff, ast_functions_diff


from .core.changes import MappingChanges, ValueChange
from .core.changes import ObservableValue

from .core.base_engine import (
    BaseEngine, 
    OPERATOR_ATTRIBUTE,
    OperatorHandle, 
    OperatorProvider
)
from .provider import UnresolvedOperatorError
from .core.cache import CacheProtocol, MemoryCache
from .core.graph import Graph, GraphProtocol, NodeT

from .core.graph import descendants, topological_sort
from .observable_graph import ObservableGraph, GraphChange


@dataclass(frozen=True)
class ProviderDirtyStatus:
    pass


@dataclass(frozen=True)
class ProviderRunningStatus:
    progress: float | None = None  # 0–1; None means unknown


@dataclass(frozen=True)
class ProviderSucceededStatus:
    operators: list[OperatorHandle]
    duration_seconds: float | None = None


@dataclass(frozen=True)
class ProviderFailedStatus:
    reason: BaseException

type ProviderStatus = ProviderDirtyStatus | ProviderRunningStatus | ProviderSucceededStatus | ProviderFailedStatus

@dataclass(frozen=True)
class OperatorChanges:
    """Operator membership changes and replacement of existing implementations."""
    added: frozenset[OperatorHandle] = frozenset()
    removed: frozenset[OperatorHandle] = frozenset()
    updated: frozenset[OperatorHandle] = frozenset()


@dataclass(frozen=True)
class EagerProviderChange:
    status: ProviderStatus = ProviderDirtyStatus()
    operators: OperatorChanges = OperatorChanges()

def _execute_provider(script: str) -> dict[OperatorHandle, Callable]:
    namespace:dict[str, Any] = {}
    exec(script, namespace)
    new_functions = {
        k: v 
        for k, v in namespace.items()
        if callable(v)
    }
    return {OperatorHandle(name): func for name, func in new_functions.items()}



@dataclass(frozen=True)
class NodeId:
    id: str


@dataclass(frozen=True)
class EagerEngineChange:
    # config
    graph: GraphChange|None=None
    script: ValueChange|None=None
    # computed
    operators: MappingChanges[OperatorHandle, Callable]|None=None
    graph_status: MappingChanges[NodeId, NodeStatus]|None=None
    provider_status: ValueChange[ProviderStatus]|None=None


@dataclass(frozen=True)
class DirtyStatus:
    pass


@dataclass(frozen=True)
class RunningStatus:
    progress: float | None = None  # 0–1; None means unknown


@dataclass(frozen=True)
class SucceededStatus:
    value: Any
    duration_seconds: float | None = None


@dataclass(frozen=True)
class FailedStatus:
    reason: Exception


type NodeStatus = DirtyStatus | RunningStatus | SucceededStatus | FailedStatus


from typing import TypedDict

@dataclass(frozen=True)
class InletSignature:
    """Public inlet information."""
    type: Any
    default: Any

@dataclass(frozen=True)
class OperatorSignature:
    """Public operator information."""
    name: str
    inlets: dict[str, InletSignature] # todo: move this to the operator's signature

    @staticmethod
    def from_func(func: Callable[..., Any]) -> "OperatorSignature":
        from inspect import signature
        sig = signature(func)
        inlets = {
            name: InletSignature(
                type=param.annotation, 
                default=param.default
            )
            for name, param in sig.parameters.items()
        }
        return OperatorSignature(name=func.__name__, inlets=inlets)

class EagerNodeData(TypedDict):
    """Public node information, without computed results."""
    __operator__: OperatorSignature
    __status__: object

    
from .graph_index import GraphAttributeIndex


import threading
import queue
from concurrent.futures import Future
from typing import Any, Callable

class NodeData(TypedDict):
    __operator__: OperatorHandle
    kwargs: dict[str, Any]


@dataclass
class EagerEngineConfig:
    graph: ObservableGraph[NodeId]
    script: ObservableValue[str]


ExecutionResult = dict[NodeId, Any]

def _prepare_graph(config_graph: Graph[NodeId], *roots: NodeId) -> Graph[NodeId]:
    """Prepare a resolved static subgraph for execution based on the given root nodes."""
    nodes = topological_sort(config_graph, *roots)
    prepared_graph = Graph[NodeId]()
    for node in nodes:
        operator_handle = config_graph.attributes(node)[OPERATOR_ATTRIBUTE]
        assert isinstance(operator_handle, OperatorHandle)
        
        prepared_graph.add_node(
            node,
            __operator__ = operator_handle,
            kwargs = {
                k: v 
                for k, v in config_graph.attributes(node).items()
                if k!=OPERATOR_ATTRIBUTE
            }
        )

    for node in nodes:
        for link in config_graph.in_links(node):
            prepared_graph.add_link(link.source, link.target, link.inlet)

    return prepared_graph

def _execute_graph(
    resolved_graph: Graph[NodeId], 
    resolved_operators: dict[OperatorHandle, Callable[..., Any]],
    *,
    cache: MemoryCache,
    callback: Callable[[NodeId, NodeStatus], None]
) -> ExecutionResult:
    """execute the plan.

    Args:
        resolved_graph: The resolved graph to execute.
        provider: The script provider to resolve operators.
        cache: The memory cache to use for storing intermediate results.
                This will mutate(!) the cache with the results of executed nodes.
                todo: do not mutate the cache directly; consider updating the cache wiith the returned results.
        callback: A callback function to report node status updates.

    Returns:
        A dictionary mapping node IDs to their execution results.
    """
    print("Execute node: resolved graph", len([node for node in resolved_graph.nodes()]))
    memo: dict[NodeId, Any] = {}
    for current in topological_sort(resolved_graph):
        callback(current, RunningStatus())
        
        # check cache before executing operator
        if current in cache:
            memo[current] = cache[current]
            callback(current, SucceededStatus(value=memo[current]))
            continue

        # get node attributes
        attributes = resolved_graph.attributes(current)

        # resolve operator handle
        operator_handle: OperatorHandle = attributes[OPERATOR_ATTRIBUTE]
        try:
            resolved_operator = resolved_operators[operator_handle]
        except KeyError as exc:
            callback(current, FailedStatus(reason=exc))
            return dict()

        # resolve inputs
        
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

        # execute node
        try:
            start_time = time.process_time()
            result = resolved_operator(**resolved_kwargs)
            duration_seconds = time.process_time() - start_time
        except Exception as exc:
            callback(current, FailedStatus(reason=exc))
            return dict()
        else:
            memo[current] = result
            cache.save(current, result)
            callback(current, SucceededStatus(value=result, duration_seconds=duration_seconds))
    
    return {node: memo[node] for node in memo}


@dataclass
class EngineConfigChange:
    graph: GraphChange|None = None
    script: ValueChange[str]|None = None

class EagerEngine:
    def __init__(self, script: str) -> None:
        # private members
        self._listeners: list[Callable[[EagerEngineChange], None]] = []
        self._closed = False

        # config
        self._graph_config = ObservableGraph[NodeId]()
        self._script_config = ObservableValue[str](script)

        # computed
        self._resolved_operators: dict[OperatorHandle, Callable[..., Any]] = {}
        self._operator_signatures: dict[OperatorHandle, OperatorSignature] = {}
        self._provider_status: ProviderStatus = ProviderDirtyStatus()
        self._node_status: dict[NodeId, NodeStatus] = {}
        
        # subscibe to config
        self._unsubscribe_graph = self._graph_config.listen(self._forward_graph_change)
        self._unsubscribe_script = self._script_config.listen(self._forward_script_change)

        # auto evaluate effects
        self._effects:list[NodeId] = []

        # state
        self._cache = MemoryCache[NodeId, Any]()
        self._operator_index = GraphAttributeIndex[NodeId, OperatorHandle](
            self._graph_config, OPERATOR_ATTRIBUTE, OperatorHandle
        )

        # initial execution
        self._execute_provider()

    def _notify(self, change: EagerEngineChange) -> None:
        self._engine_change_hook(change)
        for listener in tuple(self._listeners):
            listener(change)
        
    def listen(self, callback: Callable[[EagerEngineChange], None]) -> Callable[[], None]:
        self._listeners.append(callback)

        def unsubscribe() -> None:
            self._listeners.remove(callback)

        return unsubscribe

    # read graph
    def nodes(self) -> tuple[NodeId, ...]:
        return self._graph_config.nodes()

    def attributes(self, node: NodeId) -> EagerNodeData:
        attributes = self._graph_config.attributes(node)
        operator_handle = attributes[OPERATOR_ATTRIBUTE]
        assert isinstance(operator_handle, OperatorHandle)

        inputs: dict[str, Any] = {
            key: value
            for key, value in attributes.items()
            if key != OPERATOR_ATTRIBUTE
            and not isinstance(value, NodeId)
        }

        # Declared parameters determine inlet order, independently of overrides.
        inlets = dict()
        if op_signature:=self._operator_signatures.get(operator_handle):
            inlets.update(op_signature.inlets)

        # update _inlets_ with node _inputs_
        for name, value in inputs.items():
            if name not in inlets:
                inlets[name] = InletSignature(
                    type=type(value),
                    default=inspect.Parameter.empty
                )

        # include any link target inlet, in case it was not already in the inputs
        for link in self._graph_config.in_links(node):
            if link.inlet not in inlets:
                inlets[link.inlet] = InletSignature(
                    type=Any,
                    default=inspect.Parameter.empty
                )
            inputs[link.inlet] = link.source


        return EagerNodeData(
            __operator__ = OperatorSignature(
                name=operator_handle.name,
                inlets=inlets
            ),
            **inputs
        )

    def node_status(self, node: NodeId) -> NodeStatus:
        return self._node_status.get(node, DirtyStatus())

    def __set_node_status(self, node: NodeId, status: NodeStatus) -> None:
        """Publish transient execution status; the previous status is unknown."""
        old_status = self._node_status.get(node)
        self._node_status[node] = status
        self._notify(EagerEngineChange(
            graph_status=MappingChanges(updated={
                node: ValueChange(old=old_status, new=status)
            })
        ))

    def in_links(self, node: NodeId) -> Iterable[tuple[NodeId, NodeId, str]]:
        for link in self._graph_config.in_links(node):
            yield (link.source, link.target, link.inlet)

    def out_links(self, node: NodeId) -> Iterable[tuple[NodeId, NodeId, str]]:
        for link in self._graph_config.out_links(node):
            yield (link.source, link.target, link.inlet)

    def links(self) -> Iterable[tuple[NodeId, NodeId, str]]:
        for link in self._graph_config.links():
            yield (link.source, link.target, link.inlet)

    # mutate graph
    def node(self, funcname, **kwargs)->NodeId:
        # generate random_id for node
        import uuid
        node_id = NodeId(str(uuid.uuid4()))
        self._graph_config.add_node(
            node_id, 
            **{OPERATOR_ATTRIBUTE: OperatorHandle(funcname)},
            **kwargs
        )
        self._node_status[node_id] = DirtyStatus()
        for inlet, src in kwargs.items():
            if isinstance(src, NodeId):
                self._graph_config.add_link(src, node_id, inlet)

        return node_id

    def delete(self, node: NodeId) -> None:
        self._graph_config.remove_node(node)
        self._node_status.pop(node, None)

    def set(self, node: NodeId, **attributes: object) -> None:
        self._graph_config.set(node, **attributes)

    def unset(self, node: NodeId, name: str) -> None:
        self._graph_config.unset(node, name)

    def add_link(self, src: NodeId, dst: NodeId, inlet: str) -> None:
        self._graph_config.add_link(src, dst, inlet)

    def remove_link(self, source: 'NodeId', target: 'NodeId', inlet: str) -> None:
        self._graph_config.remove_link(source, target, inlet)

    def _forward_graph_change(self, change: GraphChange) -> None:
        # forward graph changes
        self._notify(EagerEngineChange(
            graph=change
        ))

    # read provider
    def operators(self) -> Iterable[OperatorHandle]:
        return self._resolved_operators.keys()

    # mutate provider
    def script(self) -> str:
        return self._script_config.get()

    def set_script(self, script: str) -> None:
        old = self.script()
        if old == script:
            return
        self._script_config.set(script)

    def _execute_provider(self):
        old_operators: dict[OperatorHandle, Callable] = self._resolved_operators
        old_provider_status = self._provider_status
        try:
           new_operators: dict[OperatorHandle, Callable] = _execute_provider(self._script_config.get())
        except BaseException as exc:
            new_operators = {}
            new_provider_state = ProviderFailedStatus(reason=exc)
        else:
            new_provider_state = ProviderSucceededStatus(operators=list(new_operators))

        self._provider_status = new_provider_state
        self._resolved_operators = new_operators
        self._operator_signatures = {handle: OperatorSignature.from_func(func) for handle, func in new_operators.items()}
        operators_change = MappingChanges(
            added={
                handle: new_operators[handle] 
                for handle in new_operators 
                if handle not in old_operators
            },
            removed={
                handle: old_operators[handle] 
                for handle in old_operators
                if handle not in new_operators
            },
            updated={
                handle: ValueChange(old=old_operators[handle], new=new_operators[handle]) 
                for handle in new_operators 
                if handle in old_operators and new_operators[handle] != old_operators[handle]
            }
        )

        self._notify(EagerEngineChange(
            operators=operators_change,
            provider_status=ValueChange(old=old_provider_status, new=new_provider_state)
        ))

    def _forward_script_change(self, change: ValueChange) -> None:
        self._notify(EagerEngineChange(
            script=change
        ))
        
    def _engine_change_hook(self, change: EagerEngineChange) -> None:
        print("Engine change hook", change)
        if change.script is not None:
            self._execute_provider()

        if change.operators or change.graph:
            dirty_nodes = set()
            if change.graph is not None:
                self._operator_index.update(change.graph)
                dirty_nodes = set(change.graph.nodes.added) | set(change.graph.nodes.removed)
                dirty_nodes.update(change.graph.attributes)
                dirty_nodes.update(link.target for link in change.graph.links.added)
                dirty_nodes.update(link.target for link in change.graph.links.removed)

            if change.operators:
                for handle, _ in change.operators.added.items():
                    self._operator_index.nodes_with(handle)
                    dirty_nodes.update(self._operator_index.nodes_with(handle))

                for handle, _ in change.operators.removed.items():

                    self._operator_index.nodes_with(handle)
                    dirty_nodes.update(self._operator_index.nodes_with(handle))

                for handle, _ in change.operators.updated.items():
                    self._operator_index.nodes_with(handle)
                    dirty_nodes.update(self._operator_index.nodes_with(handle))

            self.invalidate(*dirty_nodes)
    
    # executor
    def invalidate(self, *nodes: NodeId) -> None:
        """Invalidate specified nodes and all descendants in the live graph."""
        queue = deque(nodes)
        live_nodes = set(self._graph_config.nodes())
        affected: set[NodeId] = set()
        while queue:
            node = queue.popleft()
            if node in affected:
                continue
            affected.add(node)
            if node in live_nodes:
                queue.extend(link.target for link in self._graph_config.out_links(node))
        if not affected:
            return

        # Subclasses discard any state they need to before observers hear about it.
        self.invalidate_hook(frozenset(affected))
        self._effects = [node for node in self._effects if node in live_nodes]
        for node in affected & live_nodes:
            self.__set_node_status(node, DirtyStatus())

        effects = tuple(node for node in self._effects if node in affected)
        if effects:
            self.evaluate_node(*effects)

    def invalidate_hook(self, nodes: frozenset[NodeId]) -> None:
        for node in nodes:
            self._cache.remove(node)
            self._node_status[node] = DirtyStatus()

    def evaluate_node(self, *nodes: NodeId) -> ExecutionResult:
        """Publish results as events and stop on the first evaluation failure."""
        if not nodes:
            raise ValueError("At least one node must be provided")

        requested = tuple(dict.fromkeys(nodes))
        live_nodes = set(self._graph_config.nodes())
        for node in requested:
            if node not in live_nodes:
                raise ValueError(f"Root is not in graph: {node!r}")

        resolved_graph = _prepare_graph(self._graph_config, *requested)
        executed_results: ExecutionResult = _execute_graph(
            resolved_graph, 
            self._resolved_operators, 
            cache=self._cache, 
            callback=self.__set_node_status
        )
        return executed_results

    # auto evaluate
    def effect(self, source: NodeId) -> None:
        if source not in self._graph_config.nodes():
            raise ValueError("Effect node is not in graph")
        self._effects.append(source)

    def remove_effect(self, source: NodeId) -> None:
        if source in self._effects:
            self._effects.remove(source)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._unsubscribe_graph()
        self._unsubscribe_script()

    def __del__(self) -> None:
        self.close()
