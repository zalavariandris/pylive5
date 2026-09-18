from collections import deque, defaultdict
from collections.abc import Mapping

from pytools import UniqueNameGenerator
from typing import Callable, Any, Iterable, Hashable
from types import MappingProxyType
from dataclasses import dataclass
import inspect
import time

from qtpy.QtCore import (
    QObject, 
    Signal
)

class MissingNodeError(Exception):
    pass

class MissingOperatorError(Exception):
    pass


from typing import Any
from dataclasses import dataclass

@dataclass(frozen=True)
class CacheEntry:
    fingerprint: Hashable
    value: Any
    revision: int

class MemoryCache:
    """Stores the latest result for each node."""

    def __init__(self):
        self._entries: dict[NodeRef, CacheEntry] = {}
        self._revision = 0

    def lookup(self, node: NodeRef, fingerprint: Hashable) -> CacheEntry | None:
        entry = self._entries.get(node)
        if entry is not None and entry.fingerprint == fingerprint:
            return entry
        return None

    def save(self, node: NodeRef, fingerprint: Hashable, value: Any) -> CacheEntry:
        self._revision += 1
        entry = CacheEntry(fingerprint, value, self._revision)
        self._entries[node] = entry
        return entry

    def remove(self, node: NodeRef) -> None:
        self._entries.pop(node, None)

    def clear(self) -> None:
        self._entries.clear()


class DummyCache():
    def lookup(self, node: NodeRef, fingerprint: Hashable) -> CacheEntry | None:
        return None

    def save(self, node: NodeRef, fingerprint: Hashable, value: Any) -> CacheEntry:
        return CacheEntry(fingerprint, value, 0)

    def remove(self, node: NodeRef) -> None:
        pass

    def clear(self) -> None:
        pass


import abc
class AbstractOperator(abc.ABC):
    def __init__(self):
        super().__init__()

    @abc.abstractmethod
    def get_parameters(self) -> Mapping[str, ParameterData]:
        pass

    @abc.abstractmethod
    def get_return_type(self) -> type:
        pass

    @abc.abstractmethod
    def __call__(self, *args, **kwargs) -> Any:
        pass


class FunctionOperator(AbstractOperator):
    def __init__(self, func:callable):
        super().__init__()
        self._func = func

    def get_parameters(self) -> Mapping[str, ParameterData]:
        sig = inspect.signature(self._func)
        params = {}
        for name, param in sig.parameters.items():
            annotation = param.annotation if param.annotation is not inspect.Parameter.empty else Any
            param_data = ParameterData(name, annotation)
            if param.default is not inspect.Parameter.empty:
                param_data.default = param.default
            params[name] = param_data
        return MappingProxyType(params)

    def get_return_type(self) -> type:
        sig = inspect.signature(self._func)
        return sig.return_annotation if sig.return_annotation is not inspect.Signature.empty else Any

    def __call__(self, *args, **kwargs) -> Any:
        return self._func(*args, **kwargs)


@dataclass
class OperatorRef:
    graph: 'GraphRT'
    name: str

    def __eq__(self, other):
        if not isinstance(other, OperatorRef):
            return False
        return self.graph == other.graph and self.name == other.name

    def __hash__(self):
        return hash((self.graph, self.name))


@dataclass
class NodeRef:
    _graph: 'GraphRT'
    _name: str

    def __repr__(self):
        return f"NodeRef('{self._name}')"

    def __call__(self, *args, **kwargs) -> Any:
        # simply call the underlying operator
        node_data = self._graph._nodes[self]
        operator_ref = node_data.get_operator()
        if operator_ref not in self._graph._operators:
            raise MissingOperatorError(f"Operator {operator_ref} is missing from the graph")
        operator_data = self._graph._operators[operator_ref]
        return operator_data(*args, **kwargs)

    def __hash__(self):
        return hash((self._graph, self._name))

    def __eq__(self, other):
        if not isinstance(other, NodeRef):
            return False
        return self._graph == other._graph and self._name == other._name

    def get_name(self) -> str:
        return self._name

    def get_operator(self) -> OperatorRef:
        node_data = self._graph._nodes[self]
        return node_data.get_operator()

    def set_inputs(self, *args, **kwargs) -> None:
        prev_data = self._graph._nodes[self]
        next_data = NodeData(prev_data.get_operator(), list(args), dict(kwargs))
        self._graph._nodes[self] = next_data


@dataclass(frozen=True) # i think data could be frozen. anything here changes would meka the graph downsteam dirty.
class NodeData(QObject):
    operator: OperatorRef
    args: tuple
    kwargs: dict

    def get_inputs(self):
        return tuple(self.args), {k: v for k, v in self.kwargs.items()} # todo: create a view

    def get_operator(self) -> OperatorRef:
        return self.operator

    def __call__(self, *args, **kwargs) -> Any:
        raise NotImplementedError("__call__ is not implemented for NodeRef")


class ParameterData:
    _empty = object()
    def __init__(self, name: str, type_: type):
        self.name = name
        self.annotation = type_
        self.default = self._empty


from myutils.profiler import Profiler
class GraphRT(QObject):
    nodes_added = Signal(list) # list[NodeRef]
    nodes_changed = Signal(list) # list[NodeRef]
    nodes_removed = Signal(list) # list[NodeRef]
    executed = Signal(dict) # dict[NodeRef, Any]
    operators_added = Signal(list) # list[OperatorRef]
    operators_changed = Signal(list) # list[OperatorRef]
    operators_removed = Signal(list) # list[OperatorRef]

    def __init__(self):
        super().__init__()
        self._nodes: dict[NodeRef, NodeData] = dict()
        self._operators: dict[OperatorRef, AbstractOperator] = dict()
        self._connected_node_signals: dict[NodeRef, list[tuple[Signal, Callable]]] = dict()

        self._profiler = Profiler()
        self.cache = DummyCache()

    def op(self) -> Callable[[Callable, str|None], OperatorRef]:
        def decorator(func: Callable) -> OperatorRef:
            ref = OperatorRef(self, func.__name__)
            data = FunctionOperator(func)
            self._operators[ref] = data
            return ref
        return decorator

    def operators(self) -> list[OperatorRef]:
        return list(self._operators.keys())

    def remove_operator(self, op_ref: OperatorRef) -> None:
        if op_ref in self._operators:
            del self._operators[op_ref]
            # emit a signal or perform additional cleanup if necessary
            self.operators_removed.emit([op_ref])

    def update_operator(self, op_ref: OperatorRef, op_data: AbstractOperator) -> None:
        # todo: consider renaming to set_op
        if op_ref not in self._operators:
            raise MissingOperatorError(f"Operator {op_ref} does not exist in the graph.")
        self._operators[op_ref] = op_data
        self.operators_changed.emit([op_ref])

    def node(self, *args: NodeRef | Any, **kwargs: NodeRef | Any) -> Callable[[Callable, str], NodeRef]:
        def decorator(func: Callable | OperatorRef, name: str|None=None) -> NodeRef:
            assert callable(func) or isinstance(func, OperatorRef), "func must be a callable function or an instance of OperatorRef"

            # create operator
            if isinstance(func, OperatorRef):
                operator = func
            else:
                operator = self.op()(func)

            assert isinstance(operator, OperatorRef), f"operator must be an instance of OperatorRef, got: {operator}"

            node_data = NodeData(operator, args, kwargs)

            if name is None:
                name = UniqueNameGenerator(
                    existing_names=[ref._name for ref in self._nodes.keys()]
                )(operator.name)

            node_ref = NodeRef(self, name)
            self._nodes[node_ref] = node_data
            self.nodes_added.emit([node_ref])

            return node_ref
        return decorator

    def remove_node(self, node_ref: NodeRef) -> None:
        if node_ref not in self._nodes:
            raise MissingNodeError(f"Node {node_ref} does not exist in the graph.")
        del self._nodes[node_ref]
        self.nodes_removed.emit([node_ref])

    def nodes(self) -> list[NodeRef]:
        return list(self._nodes.keys())

    def ancestors(self, root: NodeRef) -> set[NodeRef]:
        visited: set[NodeRef] = {root}
        stack = [root]
        while stack:
            node_ref = stack.pop()
            node_data = self._nodes[node_ref]
            args, kwargs = node_data.get_inputs()
            for v in args + tuple(kwargs.values()):
                if isinstance(v, NodeRef) and v not in visited:
                    visited.add(v)
                    stack.append(v)
        return visited

    def topological_sort(self, nodes: set[NodeRef] | None = None) -> list[NodeRef]:
        """Returns nodes in topological execution order (dependencies before dependents)."""
        if nodes is None:
            nodes = self._nodes

        in_degree: dict[NodeRef, int] = {node: 0 for node in nodes}
        successors: dict[NodeRef, set[NodeRef]] = defaultdict(set)

        for node in nodes:
            args, kwargs = self._nodes[node].get_inputs()
            # Use a set so each unique predecessor is counted only once
            preds = {
                v for v in args + tuple(kwargs.values())
                if isinstance(v, NodeRef) and v in nodes
            }
            for v in preds:
                in_degree[node] += 1
                successors[v].add(node)

        queue: deque = deque(node for node, deg in in_degree.items() if deg == 0)
        sorted_nodes: list[NodeRef] = []

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

    def execute(self, root:NodeRef, profile: bool = True, ):
        if root is None:
            raise ValueError("No output node specified.")

        if root not in self._nodes:
            raise ValueError(f"Node {root} does not exist in the engine.")
        
        if profile:
            self._profiler.clear()

        entries: dict[NodeRef, CacheEntry] = {}
        fingerprints: dict[NodeRef, tuple] = {}

        def resolve_cache(value: Any) -> Any:
            return entries[value].value if isinstance(value, NodeRef) else value

        ancestors = self.ancestors(root)
        print("Ancestors of the root node:", ancestors)
        sorted_ancestors = self.topological_sort(ancestors)
        print("Topologically sorted ancestors:", sorted_ancestors)
        for node_ref in sorted_ancestors:
            node_data = self._nodes[node_ref]
            args, kwargs = node_data.get_inputs()
            fingerprint = (
                node_data,
                node_data.get_operator(), 
                tuple(
                    fingerprints[value] if isinstance(value, NodeRef) else value
                    for value in args
                ), 
                tuple(
                    (key, fingerprints[value] if isinstance(value, NodeRef) else value) 
                    for key, value in kwargs.items()
                )
            ) # review if node data is suitable. It should be. cause if nod data changes, than either the operator either its inputs have changed.
            fingerprints[node_ref] = fingerprint

            entry = self.cache.lookup(node_ref, fingerprint)

            if entry is None:
                resolved_args = [
                    resolve_cache(value) 
                    for value in args
                ]
                resolved_kwargs = {
                    key: resolve_cache(value) 
                    for key, value in kwargs.items()
                }

                with self._profiler.profile(node_ref):
                    value = node_ref(*resolved_args, **resolved_kwargs)

                entry = self.cache.save(node_ref, fingerprint, value)

            entries[node_ref] = entry

        self.executed.emit({node_ref: entries[node_ref].value for node_ref in ancestors})
        return entries[root].value

if __name__ == "__main__":
    G = GraphRT()

    @G.node()
    def A():
        print("Executing node A")
        return 15

    @G.node()
    def B():
        print("Executing node B")
        return 20

    @G.node(A, B)
    def mult(x, y):
        print("Executing node mult")
        return x*y

    result = G.execute(mult)
    print(result)