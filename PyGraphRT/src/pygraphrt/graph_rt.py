from collections import deque, defaultdict
from collections.abc import Mapping


from pytools import UniqueNameGenerator
from typing import TYPE_CHECKING, Callable, Any, ClassVar, Hashable, Iterable
from types import MappingProxyType
from dataclasses import dataclass
import inspect
import time

if TYPE_CHECKING:
    from .abstract_module_rt import AbstractOperator, OperatorRef

from .local_module import LocalModuleRT

from qtpy.QtCore import (
    QObject, 
    Signal
)

from types import MappingProxyType
from typing import Literal, Any, Callable, Hashable, Mapping
from qtpy.QtCore import Signal, QObject


from myutils.source_diff import ast_functions_diff

from .abstract_module_rt import (
    MissingOperatorError,
)

from .abstract_module_rt import OperatorRef

from dataclasses import dataclass

class MissingNodeError(Exception):
    pass


@dataclass(frozen=True)
class CacheEntry:
    fingerprint: Hashable
    value: Any


class MemoryCache:
    """Keep only the latest saved result for each node."""

    def __init__(self) -> None:
        self._entries: dict[NodeRef, CacheEntry] = {}

    def lookup(self, node: NodeRef, fingerprint: Hashable) -> CacheEntry | None:
        entry = self._entries.get(node)
        if entry is not None and entry.fingerprint == fingerprint:
            return entry
        return None

    def hit(self, node: NodeRef, fingerprint: Hashable) -> bool:
        return self.lookup(node, fingerprint) is not None

    def save(self, node: NodeRef, fingerprint: Hashable, value: Any) -> CacheEntry:
        entry = CacheEntry(fingerprint, value)
        self._entries[node] = entry
        return entry

    def remove(self, node: NodeRef) -> None:
        self._entries.pop(node, None)

    def clear(self) -> None:
        self._entries.clear()


class HistoryMemoryCache:
    """Keep previous results per node and fingerprint until removed or cleared."""

    def __init__(self)->None:
        self._entries: dict[
            NodeRef, 
            dict[Hashable, CacheEntry]
        ] = {}

    def lookup(self, node: NodeRef, fingerprint: Hashable) -> CacheEntry | None:
        return self._entries.get(node, {}).get(fingerprint)

    def hit(self, node: NodeRef, fingerprint: Hashable) -> bool:
        return fingerprint in self._entries.get(node, {})

    def save(self, node: NodeRef, fingerprint: Hashable, value: Any) -> CacheEntry:
        entry = CacheEntry(fingerprint, value)
        self._entries.setdefault(node, {})[fingerprint] = entry
        return entry

    def remove(self, node: NodeRef) -> None:
        self._entries.pop(node, None)

    def clear(self) -> None:
        self._entries.clear()


class DummyCache:
    def lookup(self, node: NodeRef, fingerprint: Hashable) -> CacheEntry | None:
        return None

    def hit(self, node: NodeRef, fingerprint: Hashable) -> bool:
        return False

    def save(self, node: NodeRef, fingerprint: Hashable, value: Any) -> CacheEntry:
        return CacheEntry(fingerprint, value)

    def remove(self, node: NodeRef) -> None:
        pass

    def clear(self) -> None:
        pass

from .abstract_module_rt import AbstractOperator



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

    def get_inputs(self) -> tuple[tuple[Value], dict[str, Value]]:
        node_data = self._graph._nodes[self]
        return node_data.get_inputs()
        

type LiteralValue = None | bool | int | float | str
type Value = 'NodeRef' | LiteralValue
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
    

from myutils.profiler import Profiler

def freeze(value, active=None) -> tuple:
    """Preserve built-in types and values; identify opaque objects by identity.

    The cache retains NodeData so objects identified by id() stay alive.
    """
    # todo: consider moving freeze alongside with fingerprinting to the cache, 
    #       or? a utility class? 
    #       Figure out where fingerprinting and freeze belongs. 
    #       to the memory or to the graph, or a third party component.

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

    def __init__(self):
        super().__init__()
        self._nodes: dict[NodeRef, NodeData] = dict()
        self._local_module: LocalModuleRT = LocalModuleRT(parent=self)
        self._profiler = Profiler()
        self.cache = DummyCache()

    def module(self) -> LocalModuleRT:
        return self._local_module

    def op(self) -> Callable[[Callable], OperatorRef]:
        return self._local_module.op()

    def operators(self) -> list[OperatorRef]:
        return list(self._local_module._operators.keys())

    def get_operator(self, op_ref: OperatorRef) -> AbstractOperator:
        if op_ref not in self._local_module._operators:
            raise MissingOperatorError(f"Operator {op_ref} does not exist in the graph.")
        return self._local_module._operators[op_ref]

    def node(self, *args: Value, **kwargs: Value) -> Callable[..., NodeRef]: # todo: consider using a protocol for better type checking
        def decorator(func: Callable | OperatorRef, name: str|None=None) -> NodeRef:
            assert (callable(func) and hasattr(func, "__code__")) or isinstance(func, OperatorRef), f"func must be a callable function or an instance of OperatorRef, got:{func}"

            # create operator
            if isinstance(func, OperatorRef):
                operator = func
            else:
                operator = self._local_module.op()(func)

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

    def _build_fingerprints(self, sorted_nodes: list[NodeRef]) -> dict[NodeRef, int]:
        fingerprints: dict[NodeRef, int] = {}
        for node_ref in sorted_nodes:
            node_data = self._nodes[node_ref]
            args, kwargs = node_data.get_inputs()
            operator_ref = node_data.get_operator()
            if operator_ref not in self._local_module._operators:
                raise MissingOperatorError(f"Operator {operator_ref} is missing from the graph")
            operator_data = self._local_module._operators[operator_ref]
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
        return fingerprints

    def _resolve_node_inputs(self, node_ref:NodeRef, ancestor_results: dict[NodeRef, Any])->tuple[list[Any], dict[str, Any]]:
        """ build fingerprint for teh memory cache """
        node_data = self._nodes[node_ref]
        args, kwargs = node_data.get_inputs()
        resolved_args = [
            ancestor_results[value] if isinstance(value, NodeRef) else value
            for value in args
        ]
        
        return resolved_args, resolved_kwargs
        
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

        ancestors = self.ancestors(root)
        sorted_ancestors = self.topological_sort(ancestors)

        # execute nodes
        fingerprints = self._build_fingerprints(sorted_ancestors)
        ancestors_output: dict[NodeRef, Any] = {} # store node output temporary
        for node_ref in sorted_ancestors:
            node_data = self._nodes[node_ref]
            
            if entry:=self.cache.lookup(node_ref, fingerprints[node_ref]):
                ancestors_output[node_ref] = entry.value
            else:
                args, kwargs = node_data.get_inputs()
                operator_ref = node_data.get_operator()
                if operator_ref not in self._local_module._operators:
                    raise MissingOperatorError(f"Operator {operator_ref} is missing from the graph")
                operator_data = self._local_module._operators[operator_ref]
                resolved_args = resolved_args = [
                    ancestors_output[value] if isinstance(value, NodeRef) else value
                    for value in args
                ]

                resolved_kwargs = resolved_kwargs = {
                    key: ancestors_output[value] if isinstance(value, NodeRef) else value
                    for key, value in kwargs.items()
                }

                with self._profiler.profile(node_ref):
                    value = operator_data(*resolved_args, **resolved_kwargs)

                ancestors_output[node_ref] = value
                entry = self.cache.save(node_ref, fingerprints[node_ref], value)

        self.executed.emit({node_ref: ancestors_output[node_ref] for node_ref in ancestors})
        return ancestors_output[root]

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