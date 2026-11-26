"""Synchronous eager execution, without a Job abstraction."""
from __future__ import annotations

import time
from typing import Any, Callable, Hashable, Iterable, Mapping, TypedDict

import inspect
from collections import deque
from dataclasses import dataclass



from .core.changes import MappingChanges, ValueChange, SetChanges
from .core.changes import ObservableValue


from .core.cache import MemoryCache
from .core.graph import Graph, Link

from .core.graph import topological_sort
from .observable_graph import ObservableGraph, GraphChange, AttributeChanges
from .graph_index import GraphAttributeIndex


###################
# ExecutionStatus #
###################
from .core.execution_status import (
    ExecutionStatus, 
    DirtyStatus, 
    RunningStatus, 
    SucceededStatus, 
    FailedStatus
)


########
# DATA #
########
EMPTY = inspect.Parameter.empty
OPERATOR_ATTRIBUTE = "__operator__"

@dataclass(frozen=True)
class OperatorHandle:
    name: str

type ProviderStatus = ExecutionStatus[list[OperatorHandle]]
type NodeStatus = ExecutionStatus[Any]

@dataclass(frozen=True)
class NodeId:
    id: str

@dataclass(frozen=True)
class InletSignature:
    """Public inlet information."""
    annotation: Any
    default: Any = inspect.Parameter.empty

@dataclass(frozen=True)
class OperatorSignature:
    """Public operator information."""
    name: str
    inlets: dict[str, InletSignature] # todo: move this to the operator's signature
    revision: int

    @staticmethod
    def from_func(func: Callable[..., Any], revision: int) -> "OperatorSignature":
        from inspect import signature
        sig = signature(func, eval_str=True)
        inlets = {
            name: InletSignature(
                annotation=param.annotation, 
                default=param.default
            )
            for name, param in sig.parameters.items()
        }
        return OperatorSignature(name=func.__name__, inlets=inlets, revision=revision)


class EagerNodeData(TypedDict, total=False):
    """Public node information, without computed results."""
    __operator__: OperatorHandle
    

class NodeData(TypedDict):
    __operator__: OperatorHandle
    kwargs: dict[str, Any]


ExecutionResult = dict[NodeId, Any]


###########
# COMPUTE #
###########


def _execute_provider(script: str) -> dict[OperatorHandle, Callable]:
    """Execute the given script and return a mapping of operator handles to callables.
    raises any exception encountered during script execution.
    """
    namespace:dict[str, Any] = {}
    exec(script, namespace)
    new_functions = {
        k: v 
        for k, v in namespace.items()
        if callable(v)
    }
    return {OperatorHandle(name): func for name, func in new_functions.items()}

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


class NodeExecutionError(Exception):
    def __init__(self, node: NodeId, reason: Exception) -> None:
        self.node = node
        self.reason = reason
        super().__init__(f"Node {node}: {reason}")


def _execute_graph(
    resolved_graph: Graph[NodeId], 
    resolved_operators: dict[OperatorHandle, Callable],
    *,
    cache: MemoryCache[NodeId, Any],
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
        operator_handle: OperatorHandle = attributes["__operator__"]
        try:
            resolved_operator = resolved_operators[operator_handle]
        except KeyError as exc:
            callback(current, FailedStatus(reason=exc))
            raise NodeExecutionError(current, exc) from exc

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
            raise NodeExecutionError(current, exc) from exc
        else:
            memo[current] = result
            cache.save(current, result)
            callback(current, SucceededStatus(value=result, duration_seconds=duration_seconds))
    
    return {node: memo[node] for node in memo}




###########
# CHANGES #
###########
class ExecutorChange(TypedDict, total=False):
    operators: MappingChanges[OperatorHandle, Callable[..., Any], ValueChange[Callable[..., Any]]]
    nodes_status: MappingChanges[NodeId, NodeStatus, ValueChange[NodeStatus]]
    provider_status: ValueChange[ProviderStatus]


class EagerEngineChange(ExecutorChange, total=False):
    # config
    script: ValueChange[str]
    # graph: GraphChange[NodeId]
    nodes: MappingChanges[NodeId, Mapping[Hashable, object], AttributeChanges]
    links: SetChanges[Link[NodeId]]
    
    # executor
    operators: MappingChanges[OperatorHandle, Callable[..., Any], ValueChange[Callable[..., Any]]]
    nodes_status: MappingChanges[NodeId, NodeStatus, ValueChange[NodeStatus]]
    provider_status: ValueChange[ProviderStatus]
    

####################
# STATEFULL ENGINE #
####################

class _EngineExecutor:
    """Own computed state and react to changes in the engine configuration."""

    def __init__(self,
        script: ObservableValue[str],
        graph: ObservableGraph[NodeId]
    ) -> None:
        self._script = script
        self._graph = graph
        self._closed = False
        self._started = False
        self._listeners: list[Callable[[ExecutorChange], None]] = []
        self._resolved_operators: dict[OperatorHandle, Callable[..., Any]] = {}
        self._operator_signatures: dict[OperatorHandle, OperatorSignature] = {}
        self._provider_status: ProviderStatus = DirtyStatus()
        self._nodes_status: dict[NodeId, NodeStatus] = {}
        self._effects: list[NodeId] = []
        self._cache = MemoryCache[NodeId, Any]()
        self._operator_index = GraphAttributeIndex(
            graph, OPERATOR_ATTRIBUTE, OperatorHandle,
        )
        self._unsubscribe_graph = graph.listen(self._on_graph_change)
        self._unsubscribe_script = script.listen(self._on_script_change)

        # initial script
        self._execute_provider()

    def _on_script_change(self, change: ValueChange[str]) -> None:
        self._execute_provider()

    def _execute_provider(self) -> None:
        old_operators = self._resolved_operators
        old_provider_status = self._provider_status
        try:
            new_operators = _execute_provider(self._script.get())
        except BaseException as exc:
            new_operators = {}
            new_provider_state = FailedStatus(reason=exc)
        else:
            new_provider_state = SucceededStatus(value=list(new_operators))

        self._provider_status = new_provider_state
        self._resolved_operators = new_operators
        self._operator_signatures = {handle: OperatorSignature.from_func(func) for handle, func in new_operators.items()}
        operators_change = MappingChanges(
            kind="map",
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
                handle: ValueChange(kind="value", old=old_operators[handle], new=new_operators[handle])
                for handle in new_operators
                if handle in old_operators and new_operators[handle] != old_operators[handle]
            }
        )

        self._on_operator_change(operators_change)
        self._notify(ExecutorChange(
            operators=operators_change,
            provider_status=ValueChange(kind="value", old=old_provider_status, new=new_provider_state)
        ))

    def operators(self) -> Iterable[OperatorHandle]:
        return self._resolved_operators.keys()

    def operator_signature(self, handle: OperatorHandle) -> OperatorSignature | None:
        return self._operator_signatures.get(handle)

    def _on_operator_change(self, change: MappingChanges[OperatorHandle, Callable[..., Any], ValueChange[Callable[..., Any]]]) -> None:
        handles = (
            set(change.get("added", {}))
            | set(change.get("removed", {}))
            | set(change.get("updated", {}))
        )
        dirty_nodes: set[NodeId] = set()
        for handle in handles:
            dirty_nodes.update(self._operator_index.nodes_with(handle))
        self.invalidate(*dirty_nodes)

    # process
    def effect(self, source: NodeId) -> None:
        if source not in self._graph.nodes():
            raise ValueError("Effect node is not in graph")
        if source not in self._effects:
            self._effects.append(source)

    def remove_effect(self, source: NodeId) -> None:
        if source in self._effects:
            self._effects.remove(source)

    def _on_graph_change(self, change: GraphChange[NodeId]) -> None:
        self._operator_index.update(change)
        nodes = change.get("nodes", {})
        removed_nodes = nodes.get("removed", {})
        removed_statuses: dict[NodeId, NodeStatus] = {}
        for node in removed_nodes:
            self._cache.remove(node)
            if node in self._nodes_status:
                removed_statuses[node] = self._nodes_status.pop(node)
        self._effects = [node for node in self._effects if node not in removed_nodes]

        if removed_statuses:
            self._notify(ExecutorChange(
                nodes_status=MappingChanges(kind="map", removed=removed_statuses),
            ))

        dirty_nodes = set(nodes.get("added", {})) | set(nodes.get("updated", {}))
        links = change.get("links", {})
        dirty_nodes.update(link.target for link in links.get("added", set()))
        dirty_nodes.update(link.target for link in links.get("removed", set()))
        self.invalidate(*dirty_nodes)

    def invalidate(self, *nodes: NodeId) -> None:
        """Invalidate specified nodes and all descendants in the live graph."""
        queue = deque(nodes)
        existing_nodes = set(self._graph.nodes())
        affected: set[NodeId] = set()
        while queue:
            node = queue.popleft()
            if node in affected:
                continue
            affected.add(node)
            if node in existing_nodes:
                queue.extend(link.target for link in self._graph.out_links(node))

        if not affected:
            return

        # Observers must see an invalid cache when dirty statuses are published.
        for node in affected:
            self._cache.remove(node)
        live_nodes = affected & existing_nodes
        self.__set_nodes_status(live_nodes, DirtyStatus())
        effects = [node for node in self._effects if node in live_nodes]
        if effects:
            self.evaluate_node(*effects)
    
    def evaluate_node(self, *nodes: NodeId) -> ExecutionResult:
        """Publish results as events and stop on the first evaluation failure."""
        if not nodes:
            raise ValueError("At least one node must be provided")

        requested = tuple(dict.fromkeys(nodes))
        live_nodes = set(self._graph.nodes())
        for node in requested:
            if node not in live_nodes:
                raise ValueError(f"Root is not in graph: {node!r}")

        resolved_graph = _prepare_graph(self._graph, *requested)
        executed_results: ExecutionResult = _execute_graph(
            resolved_graph,
            self._resolved_operators,
            cache=self._cache,
            callback=lambda n, s: self.__set_nodes_status([n], s)
        )
        return executed_results

    def __set_nodes_status(
        self,
        nodes: Iterable[NodeId],
        status: NodeStatus,
    ) -> None:
        """Publish additions and updates to stored node statuses."""
        added: dict[NodeId, NodeStatus] = {}
        updated: dict[NodeId, ValueChange[NodeStatus]] = {}

        for node in dict.fromkeys(nodes):
            if node in self._nodes_status:
                updated[node] = ValueChange(
                    kind="value",
                    old=self._nodes_status[node],
                    new=status,
                )
            else:
                added[node] = status

            self._nodes_status[node] = status

        if not added and not updated:
            return

        self._notify(ExecutorChange(
            nodes_status=MappingChanges(
                kind="map",
                added=added,
                updated=updated,
            )
        ))

    def nodes_status(self, node: NodeId) -> NodeStatus:
        return self._nodes_status.get(node, DirtyStatus())

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._unsubscribe_graph()
        self._unsubscribe_script()

    def listen(self, callback: Callable[[ExecutorChange], None]) -> Callable[[], None]:
        self._listeners.append(callback)

        def unsubscribe() -> None:
            self._listeners.remove(callback)

        return unsubscribe

    def _notify(self, change: ExecutorChange) -> None:
        for listener in tuple(self._listeners):
            listener(change)


class EagerEngine:
    """ Eager Engine
    ...
    """

    def __init__(self, script: str) -> None:
        # private members
        self._listeners: list[Callable[[EagerEngineChange], None]] = []
        self._closed = False

        # config
        self._script_config = ObservableValue[str](script)
        self._graph_config = ObservableGraph[NodeId]()
        # executor
        self._executor = _EngineExecutor(self._script_config, self._graph_config)

        # Subscribe before starting execution so initial events can be forwarded.
        self._unsubscribe_graph = self._graph_config.listen(self._forward_graph_change)
        self._unsubscribe_script = self._script_config.listen(self._forward_script_change)
        self._unsubscribe_executor = self._executor.listen(self._forward_executor_change)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._unsubscribe_graph()
        self._unsubscribe_script()
        self._unsubscribe_executor()
        self._executor.close()

    def _notify(self, change: EagerEngineChange) -> None:
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
        return self._graph_config.attributes(node)

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
    def create_node(self, funcname: str, **kwargs: object) -> NodeId:
        # generate random_id for node
        
        # import uuid
        # node_id = NodeId(str(uuid.uuid4()))
        from unique_names_generator import get_random_name
        node_id = get_random_name()
        self._graph_config.add_node(
            node_id, 
            **{OPERATOR_ATTRIBUTE: OperatorHandle(funcname)},
            **kwargs
        )
        for inlet, src in kwargs.items():
            if isinstance(src, NodeId):
                self._graph_config.add_link(src, node_id, inlet)

        return node_id

    def delete(self, node: NodeId) -> None:
        self._graph_config.remove_node(node)

    def set(self, node: NodeId, name: str, value: object) -> None:
        """Assign one node attribute."""
        self._graph_config.set(node, name, value)

    def update(self, node: NodeId, /, **attributes: object) -> None:
        """Merge several node attributes in one graph mutation."""
        self._graph_config.update(node, **attributes)

    def unset(self, node: NodeId, name: str) -> None:
        self._graph_config.unset(node, name)

    def add_link(self, src: NodeId, dst: NodeId, inlet: str) -> None:
        """Add a link from src to dst at the specified inlet.

        Raises:
            ValueError: If either endpoint does not exist or if the link would create a cycle.
        """


        # reject cycles
        from .core.graph import descendants
        if src not in self._graph_config.nodes() or dst not in self._graph_config.nodes():
            raise ValueError("Both link endpoints must exist")

        if src == dst or src in descendants(self._graph_config, dst):
            raise ValueError("Connection would create a cycle")

        self._graph_config.add_link(src, dst, inlet)

    def remove_link(self, source: 'NodeId', target: 'NodeId', inlet: str) -> None:
        self._graph_config.remove_link(source, target, inlet)

    # provider
    def script(self) -> str:
        return self._script_config.get()

    def set_script(self, script: str) -> None:
        old = self.script()
        if old == script:
            return
        self._script_config.set(script)

    # Computed state and execution are owned by the executor.
    def operators(self) -> Iterable[OperatorHandle]:
        return self._executor.operators()

    def operator_signature(self, operator: OperatorHandle) -> OperatorSignature|None:
        return self._executor.operator_signature(operator)

    def nodes_status(self, node: NodeId) -> NodeStatus:
        return self._executor.nodes_status(node)

    def invalidate(self, *nodes: NodeId) -> None:
        self._executor.invalidate(*nodes)

    def evaluate_node(self, *nodes: NodeId) -> ExecutionResult:
        return self._executor.evaluate_node(*nodes)

    def effect(self, source: NodeId) -> None:
        self._executor.effect(source)

    def remove_effect(self, source: NodeId) -> None:
        self._executor.remove_effect(source)

    # forward changes from underlying components to the engine level
    def _forward_graph_change(self, change: GraphChange[NodeId]) -> None:
        self._notify(EagerEngineChange(**change))

    def _forward_script_change(self, change: ValueChange[str]) -> None:
        self._notify(EagerEngineChange(
            script=change
        ))

    def _forward_executor_change(self, change: ExecutorChange) -> None:
        self._notify(EagerEngineChange(**change))
