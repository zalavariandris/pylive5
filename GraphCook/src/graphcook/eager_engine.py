"""Synchronous eager execution, without a Job abstraction."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Callable, Iterable
from .changes import GraphChange, ValueChange, SetChange, 

from .base_engine import (
    BaseEngine, 
    EngineChange, 
    OPERATOR_ATTRIBUTE,
    OperatorHandle, 
    OperatorProvider, 
)
from .provider import UnresolvedOperatorError
from .cache import CacheProtocol, MemoryCache
from .graph import Graph, GraphProtocol, NodeT
from .graph import topological_sort
from .observable_graph import ObservableGraph, GraphChange


class EagerScriptProvider(OperatorProvider):
    def __init__(self, script: str):
        self.script = script
        self._functions: dict[str, Callable[..., Any]] = dict()
        self._exec()

    def _exec(self):
        namespace = {}
        exec(self.script, namespace)
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

from dataclasses import dataclass

@dataclass(frozen=True)
class NodeId:
    id: str


from dataclasses import dataclass

@dataclass(frozen=True)
class EngineChange:
    graph: GraphChange|None
    script: ValueChange|None


class EagerEngine(BaseEngine[NodeId]):
    def __init__(self, script:str):
        super().__init__(
            ObservableGraph[NodeId](), 
            EagerScriptProvider(script)
        )
        self._script = script
        self.cache = MemoryCache[NodeId, Any]()

        self.graph.listen(self._handle_graph_change)
        self._listeners: list[Callable[[EngineChange], None]] = []

    def _notify(self, change: EngineChange) -> None:
        for listener in self._listeners:
            listener(change)

    def listen(self, callback: Callable[[EngineChange], None]) -> Callable[[], None]:
        self._listeners.append(callback)
        return lambda: self._listeners.remove(callback)

    def invalidate_hook(self, nodes: frozenset[NodeId]) -> None:
        for node in nodes:
            self.cache.remove(node)

    def _handle_graph_change(self, change: GraphChange) -> None:
        self._notify(EngineChange(graph=change, script=None))

    def script(self) -> str:
        return self._script

    def set_script(self, script: str) -> None:
        self._script = script
        self._notify(EngineChange(graph=None, script=ValueChange(old=None, new=script)))

    def _resolve_graph(self) -> Graph[NodeId]:
        resolved_graph = Graph[NodeId]()
        for node in self.graph.nodes():
            operator_handle = self.graph.attributes(node)[OPERATOR_ATTRIBUTE]
            assert isinstance(operator_handle, OperatorHandle)
            resolved_operator = self.provider.resolve(operator_handle)
            resolved_graph.add_node(
                node,
                operator = resolved_operator,
                kwargs = {
                    k: v 
                    for k, v in self.graph.attributes(node).items()
                    if k!=OPERATOR_ATTRIBUTE
                }
            )

        for src, dst, inlet in self.graph.links():
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
            if current in self.cache:
                memo[current] = self.cache[current]

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

            self._notify(EngineChange("started", current))
            try:
                result = resolved_operator(**resolved_kwargs)
                self._notify(EngineChange("executed", current, result=result))
                memo[current] = result
                self.cache.save(current, result)
            except Exception as exc:
                self._notify(EngineChange("failed", current, error=exc))
                raise exc

    def node(self, funcname, **kwargs)->NodeId:
        # generate random_id for node
        import uuid
        node_id = NodeId(str(uuid.uuid4()))
        self.graph.add_node(
            node_id, 
            **{OPERATOR_ATTRIBUTE: OperatorHandle(funcname)},
            **kwargs
        )
        for inlet, src in kwargs.items():
            if isinstance(src, NodeId):
                self.graph.add_link(src, node_id, inlet)

        return node_id

    def delete(self, node: NodeId) -> None:
        incoming_links = set(self.graph.in_links(node))
        outgoing_links = set(self.graph.out_links(node))
        dependent_nodes = set(self.graph.successors(node))
        #
        self.graph.delete_node(node)
        self._notify(
            EngineChange(
                graph=GraphChange(
                    nodes=SetChange(
                        removed=set([node])
                    ),
                    links=SetChange(
                        removed=incoming_links.union(outgoing_links)
                    )
                )
            )
        )

    def set(self, node: NodeId, **attributes: object) -> None:
        ...

    def unset(self, node: NodeId, name: str) -> None:
        ...

    