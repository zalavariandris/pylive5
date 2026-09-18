from collections import deque, defaultdict
from collections.abc import Mapping

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

class MissingNodeError(Exception):
    pass

class MissingOperatorError(Exception):
    pass


from typing import Any
from dataclasses import dataclass

@dataclass(frozen=True)
class CacheEntry:
    signature: tuple
    value: Any
    node_data: NodeData  # Retain immutable inputs used by identity in the signature.


class MemoryCache:
    """Keep cached input states separately for each node until removed or cleared."""

    def __init__(self):
        self._entries: dict[NodeRef, dict[tuple, CacheEntry]] = {}

    def lookup(self, node: NodeRef, signature: tuple) -> CacheEntry | None:
        return self._entries.get(node, {}).get(signature)

    def save(self, node: NodeRef, signature: tuple, value: Any, node_data: NodeData) -> CacheEntry:
        entry = CacheEntry(signature, value, node_data)
        self._entries.setdefault(node, {})[signature] = entry
        return entry

    def remove(self, node: NodeRef) -> None:
        self._entries.pop(node, None)

    def clear(self) -> None:
        self._entries.clear()


class DummyCache:
    def lookup(self, node: NodeRef, signature: tuple) -> CacheEntry | None:
        return None

    def save(self, node: NodeRef, signature: tuple, value: Any, node_data: NodeData) -> CacheEntry:
        return CacheEntry(signature, value, node_data)

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
        next_data = NodeData(prev_data.get_operator(), args, dict(kwargs))
        self._graph._update_node(self, next_data)
        



type LiteralValue = None | bool | int | float | str
type Value = NodeRef | LiteralValue

@dataclass(frozen=True) # i think data could be frozen. anything here changes would meka the graph downsteam dirty.
class NodeData(QObject):
    operator: OperatorRef
    args: tuple[Value]
    kwargs: dict[str, Value]

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

def freeze(value, active=None) -> tuple:
    """Preserve built-in types and values; identify opaque objects by identity.

    The cache retains NodeData so objects identified by id() stay alive.
    """
    kind = type(value)
    if kind in (type(None), bool, int, str, bytes):
        return kind, value
    
    if kind is float:
        return kind, value.hex()  # Includes the sign of zero.
    
    if kind is complex:
        return kind, value.real.hex(), value.imag.hex()
    
    if kind is bytearray:
        return kind, bytes(value)

    if active is None:
        active = set()

    if kind in (tuple, list, dict, set, frozenset) and id(value) not in active:
        active.add(id(value))
        try:
            if kind is dict:
                items = tuple((freeze(k, active), freeze(v, active)) for k, v in value.items())
            else:
                items = tuple(freeze(item, active) for item in value)
            return kind, items
        finally:
            active.remove(id(value))
            
    return kind, id(value)


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
            self.operators_added.emit([ref])
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

    def node(self, *args: Value, **kwargs: Value) -> Callable[[Callable, str], NodeRef]:
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

    def _update_node(self, node_ref: NodeRef, node_data: NodeData) -> None:
        if node_ref not in self._nodes:
            raise MissingNodeError(f"Node {node_ref} does not exist in the graph.")
        self._nodes[node_ref] = node_data
        self.nodes_changed.emit([node_ref])

    def remove_node(self, node_ref: NodeRef) -> None:
        if node_ref not in self._nodes:
            raise MissingNodeError(f"Node {node_ref} does not exist in the graph.")
        del self._nodes[node_ref]
        self.cache.remove(node_ref)
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
        """Evaluate pure operators with immutable inputs and operator data.

        Upstream signatures are reduced to Python hashes, so dependency hash
        collisions are possible. Cache lookups compare full local signatures.
        """
        if root is None:
            raise ValueError("No output node specified.")

        if root not in self._nodes:
            raise ValueError(f"Node {root} does not exist in the engine.")
        
        if profile:
            self._profiler.clear()

        entries: dict[NodeRef, CacheEntry] = {}

        def resolve_cache(value: Any) -> Any:
            return entries[value].value if isinstance(value, NodeRef) else value

        ancestors = self.ancestors(root)
        sorted_ancestors = self.topological_sort(ancestors)

        fingerprints: dict[NodeRef, int] = {}

        # def input_fingerprint(value: Any) -> tuple:
        #     if isinstance(value, NodeRef):
        #         return ("node", value, fingerprints[value])
        #     return ("literal", freeze(value))

        for node_ref in sorted_ancestors:
            node_data = self._nodes[node_ref]
            args, kwargs = node_data.get_inputs()
            operator_ref = node_data.get_operator()
            if operator_ref not in self._operators:
                raise MissingOperatorError(f"Operator {operator_ref} is missing from the graph")
            operator_data = self._operators[operator_ref]
            signature = (
                operator_data,
                tuple(
                    (
                        "node", value, fingerprints[value]) if isinstance(value, NodeRef) else ("literal", freeze(value)
                    )
                    for value in args
                ),
                tuple(
                    (
                        key, 
                        ("node", value, fingerprints[value]) if isinstance(value, NodeRef) else ("literal", freeze(value))
                    ) 
                    for key, value in kwargs.items()
                ),
            )
            # Dependencies already have hashes because this is topological order.
            fingerprints[node_ref] = hash(signature)
            entry = self.cache.lookup(node_ref, signature)

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
                    value = operator_data(*resolved_args, **resolved_kwargs)

                entry = self.cache.save(node_ref, signature, value, node_data)

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