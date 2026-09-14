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


class LocalModuleRT:
    operators_added = Signal(list)
    operators_removed = Signal(list)
    operator_function_changed = Signal(list)

    def __init__(self, graph: "GraphRT"):
        self._graph = graph
        self._script_module = ScriptModuleRT()

    def op(self) -> Callable:
        ...

    def remove_operator(self, operator: OperatorRT):
        ...

    def operators(self):
        ...

    def get_operator(self, name: str) -> OperatorRT | None:
        ...

    def set_operator_function(self, operator: OperatorRT, func: Callable):
        ...
        

class GraphRT(QObject):    
    operators_added = Signal(list)
    operators_removed = Signal(list)
    operator_function_changed = Signal(str)
    
    nodes_added = Signal(list)
    nodes_removed = Signal(list)
    
    node_operator_changed = Signal(str)
    node_inputs_changed = Signal(str)
    
    output_node_changed = Signal()

    executed = Signal(dict)

    def __init__(self):
        super().__init__()
        self._operators: set[OperatorRT] = set()
        self._operators_to_nodes: dict[OperatorRT, set[NodeRT]] = dict()

        self._nodes: set[NodeRT] = set()
        self._successors: dict[NodeRT, set[NodeRT]] = defaultdict(set)
        self._profiler:  dict[NodeRT, float] = {}
    
        self._cache: dict[tuple, Any] = {}

        self._connected_operator_signals: dict[str, list[tuple]] = {}
        self._connected_node_signals: dict[str, list[tuple]] = {}

        self._output_node: NodeRT | None = None

    def op(self) -> Callable:
        """Decorator to create and add an operator to the graph.

        Usage:
            @graph.op()
            def my_operator(...):
                ...
        """
        def decorator(func: Callable) -> OperatorRT:
            current_operator_names = [op.get_name() for op in self._operators]
            assert func.__name__ not in current_operator_names, f"Cannot add operator with duplicate name: {func.__name__}"
            operator = OperatorRT(self, func.__name__, func)
            self._operators.add(operator)
            self._operators_to_nodes[operator] = set()
            self.operators_added.emit([operator.get_name()])

            # forward operator signals
            self._connected_operator_signals[operator.get_name()] = [
                (operator.function_changed, lambda: self.operator_function_changed.emit(operator.get_name()))
            ]
            for signal, slot in self._connected_operator_signals[operator.get_name()]:
                signal.connect(slot)
                
            return operator
        return decorator

    def operators(self) -> dict[str, OperatorRT]:
        return {op.get_name(): op for op in self._operators}

    def get_operator(self, name: str) -> OperatorRT | None:
        for op in self._operators:
            if op.get_name() == name:
                return op
        return None

    def remove_operator(self, operator: OperatorRT):
        assert operator in self._operators, f"Operator {operator} does not exist in the engine."
        assert operator in self._operators_to_nodes, f"Operator {operator} is not associated with any nodes."

        nodes = list(self._operators_to_nodes[operator])
        for node in nodes:
            node.set_operator(None)

        del self._operators_to_nodes[operator]
        self._operators.remove(operator)
        self.operators_removed.emit([operator.get_name()])
        for signal, slot in self._connected_operator_signals[operator.get_name()]:
            signal.disconnect(slot)

    def node(self, *args: NodeRT | Any, **kwargs: NodeRT | Any) -> "NodeRT | Callable":
        def decorator(func: Callable | OperatorRT, name: str|None=None) -> NodeRT:
            assert callable(func) or isinstance(func, OperatorRT), "func must be a callable function or an instance of OperatorRT"

            # create operator
            if isinstance(func, OperatorRT):
                if func not in self._operators:
                    raise ValueError(f"Operator {func} must be added to the graph before creating a node.")
                operator = func
            else:
                operator = self.op()(func)

            if name is None:
                name = UniqueNameGenerator(existing_names=self.nodes())(operator.get_name())
            node = NodeRT(self, operator, name)
            node.set_inputs(*args, **kwargs)
            self._nodes.add(node)
            self._operators_to_nodes[operator].add(node)
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

        if node.get_operator():
            self._operators_to_nodes[node.get_operator()].remove(node)

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

        executed_nodes: list[NodeRT] = []
        results: dict[NodeRT, Any] = dict()
        checksums: dict[NodeRT, tuple] = {}
        new_cache: dict[tuple, Any] = dict()
        
        for node in self.topological_sort(self.ancestors(root)):
            if node in results:
                continue

            args, kwargs = node.get_inputs()
            resolved_args = [results[v] if isinstance(v, NodeRT) else v for v in args]
            resolved_kwargs = {k: results[v] if isinstance(v, NodeRT) else v for k, v in kwargs.items()}

            input_parts = []
            for idx, value in enumerate(args):
                input_parts.append((idx, checksums[value] if isinstance(value, NodeRT) else value))
            for key, value in kwargs.items():
                input_parts.append((key, checksums[value] if isinstance(value, NodeRT) else value))
            input_parts = tuple(input_parts)

            op = node.get_operator()
            checksum = (node, op._func if op else None, input_parts)
            checksums[node] = checksum

            if checksum in self._cache:
                results[node] = self._cache[checksum]
            else:
                if profile:
                    start_time = time.perf_counter()
                results[node] = node(*resolved_args, **resolved_kwargs)
                
                if profile:
                    end_time = time.perf_counter()
                    self._profiler[node] = end_time - start_time
            new_cache[checksum] = results[node]
            executed_nodes.append(node) # add to executed nodes with cache as well

        self._cache.update(new_cache)
        self.executed.emit({node.get_name(): results[node] for node in executed_nodes})
        return results[root]

    def to_dict(self, explicit:bool=False) -> dict:
        """Returns a dictionary representation of the graph."""
        operators:dict[str, OperatorRT] = {}
        for op in self._operators:
            operators[op.get_name()] = op.get_source()

        nodes = {}
        for node in self._nodes:
            node_name = node.get_name()
            nodes[node_name] = {
                "operator": node.get_operator().get_name() if node.get_operator() else None,
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
