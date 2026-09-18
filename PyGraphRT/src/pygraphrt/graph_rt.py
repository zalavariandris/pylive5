from collections import deque, defaultdict
from pygraphrt.script_module_rt import ScriptModuleRT
from pytools import UniqueNameGenerator
from typing import Callable, Any, Iterable
from types import MappingProxyType
from dataclasses import dataclass
import inspect
import time

from qtpy.QtCore import (
    QObject, 
    Signal
)

from .operator_rt import OperatorRT
from .abstract_module_rt import AbstractModuleRT
from .node_rt import NodeRT
from .local_module_rt import LocalModuleRT, OperatorRTRef

from myutils.profiler import Profiler
from .memory_cache import MemoryCache


class GraphRT(QObject):        
    modules_added = Signal(list)
    modules_removed = Signal(list)

    nodes_added = Signal(list)
    nodes_removed = Signal(list)
    node_operator_changed = Signal(str)
    node_inputs_changed = Signal(str)

    operators_changed = Signal(list)

    output_node_changed = Signal()
    executed = Signal(dict)

    def __init__(self)->None:
        super().__init__()
        
        self._modules: dict[str, AbstractModuleRT] = dict()

        local_module = LocalModuleRT("local")
        self.add_modules([local_module])
        
        self._nodes: set[NodeRT] = set()
        self._successors: dict[NodeRT, set[NodeRT]] = defaultdict(set)
        self._profiler:  Profiler = Profiler()
        self._connected_node_signals: dict[str, list[tuple]] = {}
        self._output_node: NodeRT | None = None

        # inverse mapping from operators to nodes
        self._operators_to_nodes: dict[OperatorRTRef, set[NodeRT]] = defaultdict(set)

        self._memory_cache = MemoryCache()

    def modules(self) -> list[AbstractModuleRT]:
        return [m for m in self._modules.values()]

    def add_modules(self, modules: Iterable[AbstractModuleRT]) -> None:
        for module in modules:
            self._modules[module.name()] = module
            module.operators_changed.connect(self.operators_changed)
        self.modules_added.emit(list(modules))

    def remove_modules(self, modules: Iterable[AbstractModuleRT]) -> None:
        for module in modules:
            if module.name() in self._modules:
                self._modules.pop(module.name())
        self.modules_removed.emit(list(modules))

    def registerNodeOperator(self, node: NodeRT, operator: OperatorRTRef)->None:
        self._operators_to_nodes[operator].discard(node) #register

    def unregisterNodeOperator(self, node: NodeRT, operator: OperatorRTRef)->None:
        self._operators_to_nodes.setdefault(operator, set()).add(node) #unregister

    def module(self) -> LocalModuleRT:
        return self._modules["local"]

    def cache(self) -> MemoryCache:
        """Returns the cache used during graph execution."""
        return self._memory_cache

    def node(self, *args: NodeRT | Any, **kwargs: NodeRT | Any) -> Callable[[Callable, str], NodeRT]:
        def decorator(func: Callable | OperatorRTRef, name: str|None=None) -> NodeRT:
            assert callable(func) or isinstance(func, OperatorRTRef), "func must be a callable function or an instance of OperatorRef"

            # create operator
            if isinstance(func, OperatorRTRef):
                operator = func
            else:
                operator = self.module().op()(func)

            if name is None:
                name = UniqueNameGenerator(existing_names=self.nodes())(operator.name())
                
            node = NodeRT(self, operator, name)
            node.set_inputs(*args, **kwargs)
            self._nodes.add(node)
            self.nodes_added.emit([node.get_name()])

            # forward operator signals
            self._connected_node_signals[node.get_name()] = [
                (node.inputs_changed,   lambda: self.node_inputs_changed.emit(node.get_name())),
                (node.operator_changed, lambda: self.node_operator_changed.emit(node.get_name()))
            ]
            for signal, slot in self._connected_node_signals[node.get_name()]:
                signal.connect(slot)

            return node
        return decorator

    def get_node(self, name: str) -> NodeRT | None:
        for node in self._nodes:
            if node.get_name() == name:
                return node
        return None

    def nodes(self) -> dict[str, NodeRT]:
        return {node.get_name(): node for node in self._nodes}

    def remove_node(self, node: NodeRT):
        assert node in self._nodes, f"Node {node} does not exist in the engine."

        for successor_node in list(self._successors[node]):
            args = tuple(arg for arg in successor_node._args if arg != node)
            kwargs = {key: value for key, value in successor_node._kwargs.items() if value != node}
            successor_node.set_inputs(*args, **kwargs)
        
        node.set_inputs()
        self._successors.pop(node, None)
        self._nodes.remove(node)
        self._profiler.clear(node)
        self._memory_cache.remove(node)
        
        self.nodes_removed.emit([node.get_name()])

        # disconnect signals
        for signal, slot in self._connected_node_signals[node.get_name()]:
            signal.disconnect(slot)
        self._connected_node_signals.pop(node.get_name(), None)

        if self._output_node == node:
            self.output = None

    def ancestors(self, root: NodeRT) -> set[NodeRT]:
        visited: set[NodeRT] = {root}
        stack = [root]
        while stack:
            node = stack.pop()
            args, kwargs = node.get_inputs()
            for v in args + tuple(kwargs.values()):
                if isinstance(v, NodeRT) and v not in visited:
                    visited.add(v)
                    stack.append(v)
        return visited

    def topological_sort(self, nodes: set[NodeRT] | None = None) -> list[NodeRT]:
        """Returns nodes in topological execution order (dependencies before dependents)."""
        if nodes is None:
            nodes = self._nodes

        in_degree: dict[NodeRT, int] = {node: 0 for node in nodes}
        successors: dict[NodeRT, set[NodeRT]] = defaultdict(set)

        for node in nodes:
            args, kwargs = node.get_inputs()
            # Use a set so each unique predecessor is counted only once
            preds = {
                v for v in args + tuple(kwargs.values())
                if isinstance(v, NodeRT) and v in nodes
            }
            for v in preds:
                in_degree[node] += 1
                successors[v].add(node)

        queue: deque = deque(node for node, deg in in_degree.items() if deg == 0)
        sorted_nodes: list[NodeRT] = []

        while queue:
            node = queue.popleft()
            sorted_nodes.append(node)
            for succ in successors[node]:
                in_degree[succ] -= 1
                if in_degree[succ] == 0:
                    queue.append(succ)

        if len(sorted_nodes) != len(nodes):
            raise ValueError("Cycle detected in the graph.")

        return sorted_nodes

    def execute(self, root:NodeRT | None = None, profile: bool = True) -> Any:
        if root is None:
            root = self._output_node

        if root is None:
            raise ValueError("No output node specified.")

        if root not in self._nodes:
            raise ValueError(f"Node {root} does not exist in the engine.")
        
        if profile:
            self._profiler.clear()

        entries: dict[NodeRT, CacheEntry] = {}

        def input_fingerprint(value: Any) -> tuple:
            if isinstance(value, NodeRT):
                return ("node", value, entries[value].revision)
            return ("literal", type(value), value)

        def resolve(value: Any) -> Any:
            return entries[value].value if isinstance(value, NodeRT) else value

        ancestors = self.ancestors(root)
        sorted_ancestors = self.topological_sort(ancestors)
        
        for node in sorted_ancestors:
            args, kwargs = node.get_inputs()
            operator = node.get_operator()
            fingerprint = (
                operator.fingerprint() if operator is not None else None,
                tuple(input_fingerprint(value) for value in args),
                tuple(
                    (key, input_fingerprint(value))
                    for key, value in kwargs.items()
                ),
            )

            entry = self._memory_cache.lookup(node, fingerprint)
            if entry is None:
                resolved_args = [resolve(value) for value in args]
                resolved_kwargs = {
                    key: resolve(value) for key, value in kwargs.items()
                }

                with self._profiler.profile(node):
                    value = node(*resolved_args, **resolved_kwargs)

                entry = self._memory_cache.save(node, fingerprint, value)

            entries[node] = entry

        self.executed.emit({node.get_name(): entries[node].value for node in ancestors})
        return entries[root].value

    def to_dict(self, explicit:bool=False) -> dict:
        """Returns a dictionary representation of the graph."""
        operators:dict[str, OperatorRT] = {}
        for op in self._local_module.operators():
            operators[op.get_name()] = op.get_source()

        nodes = {}
        for node in self._nodes:
            node_name = node.get_name()
            nodes[node_name] = {
                "operator": node.get_operator().name() if node.get_operator() else None,
            }
            
            if explicit or len(node._args) > 0:
                nodes[node_name]["args"] = [arg.get_name() if isinstance(arg, NodeRT) else arg for arg in node._args]

            if explicit or len(node._kwargs) > 0:
                nodes[node_name]["kwargs"] = {k: v.get_name() if isinstance(v, NodeRT) else v for k, v in node._kwargs.items()}

        return {
            "operators": operators,
            "nodes": nodes,
            "output": self._output_node.get_name() if self._output_node else None
        }

    @property
    def output(self) -> NodeRT|None:
        return self._output_node
      
    @output.setter
    def output(self, node: NodeRT|None) -> None:
        """Sets the output node of the graph."""
        if node is None:
            self._output_node = None
            self.output_node_changed.emit()
            return
        
        if node not in self._nodes:
            raise ValueError(f"The node must be part of the graph, got: {node}")
        
        self._output_node = node
        self.output_node_changed.emit()
