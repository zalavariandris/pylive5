"""Synchronous eager execution, without a Job abstraction."""
from __future__ import annotations
import time
from typing import Iterator
import inspect
from collections import deque
from collections.abc import Mapping
from typing import Any, Callable, Iterable, Literal, cast
from dataclasses import dataclass

from myutils.source_diff import collect_functions, FunctionsDiff, ast_functions_diff
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


@dataclass(frozen=True)
class ProviderDirtyState:
    pass


@dataclass(frozen=True)
class ProviderRunningState:
    progress: float | None = None  # 0–1; None means unknown


@dataclass(frozen=True)
class ProviderSucceededState:
    value: Any
    duration_seconds: float | None = None


@dataclass(frozen=True)
class ProviderFailedState:
    reason: Exception

type ProviderState = ProviderDirtyState | ProviderRunningState | ProviderSucceededState | ProviderFailedState

@dataclass(frozen=True)
class ProviderChange:
    added: tuple[OperatorHandle, ...] = ()
    removed: tuple[OperatorHandle, ...] = ()
    changed: tuple[OperatorHandle, ...] = ()
    state: ProviderState = ProviderDirtyState()

class EagerScriptProvider:
    def __init__(self, script: str) -> None:
        self._listeners: list[Callable[[ProviderChange], None]] = []
        self._script = script
        self._functions: dict[str, Callable[..., Any]] = dict()
        self._exec()

    def _exec(self) -> None:
        namespace = {}
        exec(self._script, namespace)
        self._functions = {
            k: v 
            for k, v in namespace.items()
            if callable(v)
        }

    def operators(self) -> Iterable[OperatorHandle]:
        return [OperatorHandle(name) for name in self._functions]

    def resolve(self, handle: OperatorHandle) -> Callable|None:
        try:
            return self._functions[handle.name]
        except KeyError:
            return None

    def get_operator_by_name(self, name: str) -> OperatorHandle:
        return OperatorHandle(name)

    def set_script(self, script: str) -> None:
        old_functions = self._functions.copy()
        self._script = script
        try:
            namespace = {}
            exec(self._script, namespace)
            self._functions = {
                k: v 
                for k, v in namespace.items()
                if callable(v)
            }
        except BaseException as error:
            self._functions = dict()
            self._notify(ProviderChange(
                state=ProviderFailedState(reason=error)
            ))
        else:
            self._notify(ProviderChange(
                added=tuple(OperatorHandle(name) for name in self._functions if name not in old_functions),
                removed=tuple(OperatorHandle(name) for name in old_functions if name not in self._functions),
                changed=tuple(OperatorHandle(name) for name in self._functions if name in old_functions and self._functions[name] != old_functions[name]),
                state=ProviderSucceededState(value=[OperatorHandle(name) for name in self._functions])
            ))

    def script(self) -> str:
        return self._script

    def _notify(self, change: ProviderChange) -> None:
        for listener in self._listeners:
            listener(change)

    def listen(self, callback: Callable[[ProviderChange], None]) -> Callable[[], None]:
        self._listeners.append(callback)
        return lambda: self._listeners.remove(callback)

@dataclass(frozen=True)
class NodeId:
    id: str


@dataclass(frozen=True)
class EagerEngineChange:
    provider: ProviderChange|None=None
    graph: GraphChange|None=None
    script: ValueChange|None=None


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
    __operator__: OperatorSignature
    __status__: object

    
from .graph_index import GraphAttributeIndex



class EagerEngine:
    def __init__(self, script: str) -> None:

        # config
        self._provider = EagerScriptProvider(script)
        self._config_graph = ObservableGraph[NodeId]()
        self._effects:list[NodeId] = []

        # state
        self._cache = MemoryCache[NodeId, Any]()
        self._node_status: dict[NodeId, NodeStatus] = {}

        # private members
        self._listeners: list[Callable[[EagerEngineChange], None]] = []

        self._operator_index = GraphAttributeIndex[NodeId, OperatorHandle](
            self._config_graph, OPERATOR_ATTRIBUTE, OperatorHandle
        )
        
        self._unsubscribe_graph = self._config_graph.listen(self._handle_graph_change)
        self._unsubscribe_provider = self._provider.listen(self._handle_provider_change)
        self._closed = False

    def _notify(self, change: EagerEngineChange) -> None:
        for listener in tuple(self._listeners):
            listener(change)

    def __set_node_status(self, node: NodeId, status: NodeStatus) -> None:
        """Publish transient execution state; the previous state is unknown."""
        self._node_status[node] = status
        self._notify(EagerEngineChange(
            graph=GraphChange(attributes={
                node: MappingChanges(changed={
                    "state": ValueChange(old=None, new=status)
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
        self.invalidate(*dirty)

    def _prepare_graph(self, *roots: NodeId) -> Graph[NodeId]:
        """Prepare a resolved static subgraph for execution based on the given root nodes."""
        nodes = topological_sort(self._config_graph, *roots)
        prepared_graph = Graph[NodeId]()
        for node in nodes:
            operator_handle = self._config_graph.attributes(node)[OPERATOR_ATTRIBUTE]
            assert isinstance(operator_handle, OperatorHandle)
            resolved_operator = self._provider.resolve(operator_handle)
            prepared_graph.add_node(
                node,
                operator = resolved_operator,
                kwargs = {
                    k: v 
                    for k, v in self._config_graph.attributes(node).items()
                    if k!=OPERATOR_ATTRIBUTE
                }
            )

        for node in nodes:
            for link in self._config_graph.in_links(node):
                prepared_graph.add_link(link.source, link.target, link.inlet)

        return prepared_graph

    def _execute_graph(self, resolved_graph: Graph[NodeId]) -> dict[NodeId, Any]:
        """execute the plan."""
        print("Execute node: resolved graph", len([node for node in resolved_graph.nodes()]))
        memo: dict[NodeId, Any] = {}
        for current in topological_sort(resolved_graph):
            if current in self._cache:
                memo[current] = self._cache[current]
                self.__set_node_status(current, SucceededStatus(value=memo[current]))
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
            # assert callable(resolved_operator)
            self.__set_node_status(current, RunningStatus())
            try:
                start_time = time.process_time()
                result = resolved_operator(**resolved_kwargs)
                duration_seconds = time.process_time() - start_time
            except Exception as exc:
                self.__set_node_status(current, FailedStatus(reason=exc))
                return []
            else:
                memo[current] = result
                self._cache.save(current, result)
                self.__set_node_status(current, SucceededStatus(value=result, duration_seconds=duration_seconds))
        
        return {node: memo[node] for node in memo}

    def evaluate(self, *nodes: NodeId) -> dict[NodeId, Any]:
        """Publish results as events and stop on the first evaluation failure."""
        if not nodes:
            raise ValueError("At least one node must be provided")

        requested = tuple(dict.fromkeys(nodes))
        live_nodes = set(self._config_graph.nodes())
        for node in requested:
            if node not in live_nodes:
                raise ValueError(f"Root is not in graph: {node!r}")

        resolved_graph = self._prepare_graph(*requested)
        executed_results = self._execute_graph(resolved_graph)
        return executed_results

    # read graph
    def nodes(self) -> tuple[NodeId, ...]:
        return self._config_graph.nodes()

    def attributes(self, node: NodeId) -> EagerNodeSignature:
        attributes = self._config_graph.attributes(node)
        operator = attributes[OPERATOR_ATTRIBUTE]
        assert isinstance(operator, OperatorHandle)
        
        inputs: dict[str, Any] = {
            key: value
            for key, value in attributes.items()
            if key != OPERATOR_ATTRIBUTE
            and not isinstance(value, NodeId)
        }

        # Declared parameters determine inlet order, independently of overrides.
        if func := self._provider.resolve(operator):
            signature = inspect.signature(func, eval_str=True)
            inlets: dict[str, InletSignature] = {
                parameter.name: InletSignature(
                    type=parameter.annotation,
                    default=parameter.default,
                )
                for parameter in signature.parameters.values()
            }
        else:
            inlets = {}

        # include inputs that are not already in the inlets
        for name, value in inputs.items():
            if name not in inlets:
                inlets[name] = InletSignature(
                    type=type(value),
                    default=inspect.Parameter.empty,
                )

        # include any link target inlet, in case it was not already in the inputs
        for link in self._config_graph.in_links(node):
            if link.inlet not in inlets:
                inlets[link.inlet] = InletSignature(
                    type=Any,
                    default=inspect.Parameter.empty
                )
            inputs[link.inlet] = link.source

        return EagerNodeSignature(
            __operator__=OperatorSignature(
                name=operator.name,
                inlets=inlets
            ),
            __status__= self._node_status.get(node, DirtyStatus()),
            **inputs
        )

    def in_links(self, node: NodeId) -> Iterable[tuple[NodeId, NodeId, str]]:
        for link in self._config_graph.in_links(node):
            yield (link.source, link.target, link.inlet)

    def out_links(self, node: NodeId) -> Iterable[tuple[NodeId, NodeId, str]]:
        for link in self._config_graph.out_links(node):
            yield (link.source, link.target, link.inlet)

    def links(self) -> Iterable[tuple[NodeId, NodeId, str]]:
        for link in self._config_graph.links():
            yield (link.source, link.target, link.inlet)

    # mutate graph
    def node(self, funcname, **kwargs)->NodeId:
        # generate random_id for node
        import uuid
        node_id = NodeId(str(uuid.uuid4()))
        self._config_graph.add_node(
            node_id, 
            **{OPERATOR_ATTRIBUTE: OperatorHandle(funcname)},
            **kwargs
        )
        self._node_status[node_id] = DirtyStatus()
        for inlet, src in kwargs.items():
            if isinstance(src, NodeId):
                self._config_graph.add_link(src, node_id, inlet)

        return node_id

    def delete(self, node: NodeId) -> None:
        self._config_graph.remove_node(node)
        self._node_status.pop(node, None)

    def set(self, node: NodeId, **attributes: object) -> None:
        self._config_graph.set(node, **attributes)

    def unset(self, node: NodeId, name: str) -> None:
        self._config_graph.unset(node, name)

    def add_link(self, src: NodeId, dst: NodeId, inlet: str) -> None:
        self._config_graph.add_link(src, dst, inlet)

    def remove_link(self, source: 'NodeId', target: 'NodeId', inlet: str) -> None:
        self._config_graph.remove_link(source, target, inlet)

    # auto evaluate
    def effect(self, source: NodeId) -> None:
        if source not in self._config_graph.nodes():
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
        self.invalidate(*self.nodes())

    def _handle_provider_change(self, change: ProviderChange) -> None:
        if change is not None:
            self._notify(EagerEngineChange(
                provider=change,
                graph=None,
                script=None
            ))
        dirty: set[NodeId] = set()
        for handle in (*change.added, *change.removed, *change.changed):
            dirty.update(self._operator_index.nodes_with(handle))
        self.invalidate(*dirty)
    
    # executor
    def invalidate(self, *nodes: NodeId) -> None:
        """Invalidate specified nodes and all descendants in the live graph."""
        queue = deque(nodes)
        live_nodes = set(self._config_graph.nodes())
        affected: set[NodeId] = set()
        while queue:
            node = queue.popleft()
            if node in affected:
                continue
            affected.add(node)
            if node in live_nodes:
                queue.extend(link.target for link in self._config_graph.out_links(node))
        if not affected:
            return

        # Subclasses discard any state they need to before observers hear about it.
        self.invalidate_hook(frozenset(affected))
        self._effects = [node for node in self._effects if node in live_nodes]
        for node in affected & live_nodes:
            self.__set_node_status(node, DirtyStatus())

        effects = tuple(node for node in self._effects if node in affected)
        if effects:
            self.evaluate(*effects)

    def invalidate_hook(self, nodes: frozenset[NodeId]) -> None:
        for node in nodes:
            self._cache.remove(node)
            self._node_status[node] = DirtyStatus()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._unsubscribe_graph()
        self._unsubscribe_provider()

    def __del__(self) -> None:
        self.close()
