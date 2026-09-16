from collections import deque, defaultdict
from pygraphrt.script_module_rt import ScriptModuleRT
from pytools import UniqueNameGenerator
from typing import Callable, Any
from types import MappingProxyType
from dataclasses import dataclass
import inspect
import time

from qtpy.QtCore import (
    QObject, 
    Signal
)

from .operator_rt import OperatorRT
from .node_rt import NodeRT
from .local_module_rt import LocalModuleRT, OperatorRTRef

class MemoryCache:
    def __init__(self):
        self._cache: dict[tuple, Any] = {}

    def get(self, key: tuple) -> Any | None:
        return self._cache.get(key)

    def set(self, key: tuple, value: Any):
        self._cache[key] = value

    def pop(self, key: tuple, default: Any = None) -> Any:
        return self._cache.pop(key, default)
    

class GraphRT(QObject):        
    nodes_added = Signal(list)
    nodes_removed = Signal(list)
    node_operator_changed = Signal(str)
    node_inputs_changed = Signal(str)
    operator_function_changed = Signal(list)
    output_node_changed = Signal()
    executed = Signal(dict)

    def __init__(self):
        super().__init__()
        self._local_module = LocalModuleRT(self)
        self._local_module.operator_changed.connect(self.operator_function_changed)
        self._nodes: set[NodeRT] = set()
        self._successors: dict[NodeRT, set[NodeRT]] = defaultdict(set)
        self._profiler:  dict[NodeRT, float] = {}
        self._cache: dict[tuple, Any] = {}
        self._connected_node_signals: dict[str, list[tuple]] = {}
        self._output_node: NodeRT | None = None

    def module(self) -> LocalModuleRT:
        return self._local_module

    def node(self, *args: NodeRT | Any, **kwargs: NodeRT | Any) -> "NodeRT | Callable":
        def decorator(func: Callable | OperatorRTRef, name: str|None=None) -> NodeRT:
            assert callable(func) or isinstance(func, OperatorRTRef), "func must be a callable function or an instance of OperatorRef"

            # create operator
            if isinstance(func, OperatorRTRef):
                operator = func
            else:
                operator = self.module().op()(func)

            if name is None:
                name = UniqueNameGenerator(existing_names=self.nodes())(operator.key())
                
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
        self._profiler.pop(node, None)
        
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

    def clear_cache(self):
        self._cache.clear()

    def execute(self, root:NodeRT | None = None, profile: bool = True) -> Any:
        if root is None:
            root = self._output_node

        if root is None:
            raise ValueError("No output node specified.")

        if root not in self._nodes:
            raise ValueError(f"Node {root} does not exist in the engine.")
        
        if profile:
            self._profiler.clear()

                        
        fingerprints: dict[NodeRT, tuple] = {}
        new_cache: dict[tuple, Any] = dict()

        results: dict[NodeRT, Any] = dict()
        ancestors = self.ancestors(root)
        for node in self.topological_sort(ancestors):
            if node in results:
                continue

            args, kwargs = node.get_inputs()

            resolved_args = [
                results[v] if isinstance(v, NodeRT) else v 
                for v in args
            ]

            resolved_kwargs = {
                k: results[v] if isinstance(v, NodeRT) else v 
                for k, v in kwargs.items()
            }

            inputs_fingerprint = []
            for idx, value in enumerate(args):
                inputs_fingerprint.append((idx, fingerprints[value] if isinstance(value, NodeRT) else value))
            for key, value in kwargs.items():
                inputs_fingerprint.append((key, fingerprints[value] if isinstance(value, NodeRT) else value))
            inputs_fingerprint = tuple(inputs_fingerprint)

            op = node.get_operator()
            fingerprints[node] = (
                node, 
                op.fingerprint() if op else None, 
                inputs_fingerprint
            )

            if fingerprints[node] in self._cache:
                results[node] = self._cache[fingerprints[node]]
            else:
                if profile:
                    start_time = time.perf_counter()
                results[node] = node(*resolved_args, **resolved_kwargs)
                
                if profile:
                    end_time = time.perf_counter()
                    self._profiler[node] = end_time - start_time

            new_cache[fingerprints[node]] = results[node]

        self._cache.update(new_cache)
        self.executed.emit({node.get_name(): results[node] for node in ancestors})
        return results[root]

    def to_dict(self, explicit:bool=False) -> dict:
        """Returns a dictionary representation of the graph."""
        operators:dict[str, OperatorRT] = {}
        for op in self._local_module.operators():
            operators[op.get_name()] = op.get_source()

        nodes = {}
        for node in self._nodes:
            node_name = node.get_name()
            nodes[node_name] = {
                "operator": node.get_operator().key() if node.get_operator() else None,
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
