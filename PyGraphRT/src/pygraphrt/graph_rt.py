from collections import deque, defaultdict
from typing import TYPE_CHECKING, Any, Callable, Hashable, Callable, Any, Hashable, Iterable
from dataclasses import dataclass

from qtpy.QtCore import (
    QObject, 
    Signal
)

from pytools import UniqueNameGenerator

from myutils.profiler import Profiler

if TYPE_CHECKING:
    from .abstract_module_rt import AbstractOperator, OperatorRef

from .inline_module import InlineModuleRT
from .import_module import ImportModuleRT
from .script_module import ScriptModuleRT
from .abstract_module_rt import OperatorRef
from .abstract_module_rt import AbstractOperator
from .abstract_module_rt import MissingOperatorError


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


@dataclass
class NodeRef:
    _graph: 'GraphRT'
    _name: str

    def __repr__(self):
        return f"NodeRef('{self._name}')"

    def __call__(self, *args, **kwargs) -> Any:
        if operator_data:=self.get_operator().get_value():
            return operator_data(*args, **kwargs)
        else:
            raise MissingOperatorError(f"Operator {self.get_operator()} is missing from the graph")
        
    def __hash__(self):
        return hash((self._graph, self._name))

    def __eq__(self, other):
        if not isinstance(other, NodeRef):
            return False
        return self._graph == other._graph and self._name == other._name

    def get_name(self) -> str:
        return self._name

    def get_value(self) -> NodeData|None:
        node_data = self._graph._nodes[self]
        return node_data

    def get_operator(self) -> OperatorRef:
        node_data = self.get_value()
        return node_data.get_operator()

    def set_inputs(self, *args, **kwargs) -> None:
        prev_data = self.get_value()
        self._graph._validate_inputs(*args, **kwargs)
        next_data = NodeData(prev_data.get_operator(), args, dict(kwargs))
        self._graph._update_node(self, next_data)

    def get_inputs(self) -> tuple[tuple[Value], dict[str, Value]]:
        node_data = self.get_value()
        return node_data.get_inputs()
        

type LiteralValue = None | bool | int | float | str
type Value = 'NodeRef' | LiteralValue
@dataclass(frozen=True) # i think data could be frozen. anything here changes would meka the graph downsteam dirty.
class NodeData:
    operator: OperatorRef
    args: tuple[Value]
    kwargs: dict[str, Value]

    def get_inputs(self)->Iterable[Value]:
        return tuple(self.args), {
            k: v for k, v in self.kwargs.items()
        } # todo: create a view

    def get_operator(self) -> OperatorRef:
        return self.operator

    def __call__(self, *args, **kwargs) -> Any:
        raise NotImplementedError("__call__ is not implemented for NodeRef")
    


class MissingNodeError(Exception):
    pass


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

"""JSON helpers for GraphRT. The runtime owns the graph format."""

import math
from pathlib import Path




def _encode_value(value, nodes):
    from .graph_rt import NodeRef

    if type(value) in (type(None), bool, int, str):
        return value
    if type(value) is float:
        return value if math.isfinite(value) else {"type": "float", "value": value.hex()}
    if isinstance(value, NodeRef):
        if value not in nodes:
            raise ValueError(f"Input references a node outside this graph: {value}")
        return {"type": "node", "name": value.get_name()}
    if type(value) is list:
        return [_encode_value(item, nodes) for item in value]
    if type(value) is tuple:
        return {"type": "tuple", "items": [_encode_value(item, nodes) for item in value]}
    if type(value) is dict:
        return {"type": "dict", "items": [
            [_encode_value(key, nodes), _encode_value(item, nodes)]
            for key, item in value.items()
        ]}
    if isinstance(value, Path):
        return {"type": "path", "value": str(value)}
    raise TypeError(f"Cannot save input of type {type(value).__name__}")


def _decode_value(value, nodes):
    if type(value) in (type(None), bool, int, float, str):
        return value
    if isinstance(value, list):
        return [_decode_value(item, nodes) for item in value]
    if not isinstance(value, dict):
        raise ValueError("Invalid input value")
    match value:
        case {"type": "node", "name": str(name)}:
            if name not in nodes:
                raise ValueError(f"Unknown node reference: {name}")
            return nodes[name]
        case {"type": "tuple", "items": list(items)}:
            return tuple(_decode_value(item, nodes) for item in items)
        case {"type": "dict", "items": list(items)}:
            return {_decode_value(key, nodes): _decode_value(item, nodes) for key, item in items}
        case {"type": "path", "value": str(path)}:
            return Path(path)
        case {"type": "float", "value": str(number)}:
            return float.fromhex(number)
    raise ValueError(f"Invalid tagged input: {value!r}")

class GraphRT(QObject):
    nodes_added = Signal(list) # list[NodeRef]
    nodes_changed = Signal(list) # list[NodeRef]
    nodes_removed = Signal(list) # list[NodeRef]
    executed = Signal(dict) # dict[NodeRef, Any]
    modules_changed = Signal()

    def __init__(self, definitions:str=""):
        super().__init__()

        self._imports: list[ImportModuleRT] = [] # List of imported modules
        self._inline_module: InlineModuleRT = InlineModuleRT(parent=self) # hold runtime functions. created with the node decorators
        self._definitions = ScriptModuleRT("local", definitions, parent=self)
        self._nodes: dict[NodeRef, NodeData] = dict()
        self._profiler = Profiler()
        self.cache = DummyCache()

    def inline(self) -> InlineModuleRT:
        """Return the inline module containing runtime functions.
        Created with the node decorators."""
        return self._inline_module

    def definitions(self) -> ScriptModuleRT:
        """Return the local script module containing user-defined functions."""
        return self._definitions

    def imports(self) -> list[ImportModuleRT]:
        return list(self._imports)

    def modules(self):
        """Modules available to the editor, including unused imports."""
        return [self._definitions, *self._imports]

    def add_import(self, path: str, *, source: str | None = None) -> ImportModuleRT:
        module = ImportModuleRT(path, source=source)
        self.add_import_module(module)
        return module

    def add_import_module(self, module: ImportModuleRT) -> None:
        if not isinstance(module, ImportModuleRT):
            raise TypeError("Only imported modules can be added; edit definitions for embedded code")
        if module not in self._imports:
            self._imports.append(module)
            self.modules_changed.emit()

    def remove_import(self, module: ImportModuleRT | str) -> None:
        if isinstance(module, str):
            module = next((item for item in self._imports if item.path() == module), None)
        if module not in self._imports:
            raise KeyError("Import module is not in this graph")
        self._imports.remove(module)
        self.modules_changed.emit()

    def op(self) -> Callable[[Callable], OperatorRef]:
        return self._inline_module.op()

    def operators(self) -> list[OperatorRef]:
        return list(self._inline_module._operators.keys())

    def get_operator(self, op_ref: OperatorRef) -> AbstractOperator:
        if op_ref not in self._inline_module._operators:
            raise MissingOperatorError(f"Operator {op_ref} does not exist in the graph.")
        return self._inline_module._operators[op_ref]

    def _validate_inputs(self, *args: Value, **kwargs: Value) -> None:
        """Validate that all NodeRef inputs exist in the graph.

        Raises:
            ValueError: If any NodeRef in args or kwargs does not exist in the graph.
        """
        for arg in args:
            if isinstance(arg, NodeRef):
                if arg not in self._nodes:
                    raise ValueError(f"Node {arg} does not exist in the graph.")
        for key, value in kwargs.items():
            if isinstance(value, NodeRef):
                if value not in self._nodes:
                    raise ValueError(f"Node {value} does not exist in the graph.")

    def node(self, *args: Value, **kwargs: Value) -> Callable[..., NodeRef]: # todo: consider using a protocol for better type checking
        def decorator(func: Callable | OperatorRef, name: str|None=None) -> NodeRef:
            assert (callable(func) and hasattr(func, "__code__")) or isinstance(func, OperatorRef), f"func must be a callable function or an instance of OperatorRef, got:{func}"

            # create operator
            if isinstance(func, OperatorRef):
                operator = func
            else:
                operator = self._inline_module.op()(func)

            assert isinstance(operator, OperatorRef), f"operator must be an instance of OperatorRef, got: {operator}"

            # validate inputs
            self._validate_inputs(*args, **kwargs)
                    
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

        changed_nodes = []
        for dependent, node_data in self._nodes.items():
            args, kwargs = node_data.get_inputs()
            remaining_args = tuple(
                value for value in args
                if not (isinstance(value, NodeRef) and value == node_ref)
            )
            remaining_kwargs = {
                key: value for key, value in kwargs.items()
                if not (isinstance(value, NodeRef) and value == node_ref)
            }
            if len(remaining_args) != len(args) or len(remaining_kwargs) != len(kwargs):
                self._nodes[dependent] = NodeData(
                    node_data.get_operator(), remaining_args, remaining_kwargs
                )
                changed_nodes.append(dependent)

        # Finish clearing all references before notifying listeners.
        if changed_nodes:
            self.nodes_changed.emit(changed_nodes)
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
            assert isinstance(operator_ref, OperatorRef), f"operator_ref must be an instance of OperatorRef, got: {operator_ref}"

            operator_data = operator_ref.get_value()
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
        resolved_kwargs = {
            key: ancestor_results[value] if isinstance(value, NodeRef) else value
            for key, value in kwargs.items()
        }
        
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
                

                resolved_args = resolved_args = [
                    ancestors_output[value] if isinstance(value, NodeRef) else value
                    for value in args
                ]

                resolved_kwargs = resolved_kwargs = {
                    key: ancestors_output[value] if isinstance(value, NodeRef) else value
                    for key, value in kwargs.items()
                }

                operator_ref = node_data.get_operator()
                with self._profiler.profile(node_ref):
                    if operator := operator_ref.get_value():
                        value = operator(*resolved_args, **resolved_kwargs)
                    else:
                        raise MissingOperatorError(f"Operator for node {node_ref} is missing.")

                ancestors_output[node_ref] = value
                entry = self.cache.save(node_ref, fingerprints[node_ref], value)

        self.executed.emit({node_ref: ancestors_output[node_ref] for node_ref in ancestors})
        return ancestors_output[root]

    def todict(self, explicit: bool = False) -> dict:
        """Save definitions, import paths, and typed node inputs, without layout."""

        module_ids = {self.definitions(): "definitions"}
        imports = {}
        for module in self._imports:
            module_id = module.get_name()
            if module_id == "definitions" or module_id in imports:
                raise ValueError(f"Import name {module_id!r} must be unique and cannot be 'definitions'")
            module_ids[module] = module_id
            imports[module_id] = module.path()
        nodes = {}
        node_refs = set(self.nodes())
        for node in self.nodes():
            name = node.get_name()
            if not isinstance(name, str):
                raise TypeError("Saved node names must be strings")
            operator = node.get_operator()
            if operator.module not in module_ids:
                raise ValueError(f"Node {name!r} must use the definitions script module or a registered import")
            args, kwargs = node.get_inputs()
            record = {"operator": {"module": module_ids[operator.module], "name": operator.name}}
            if args or explicit:
                record["args"] = [_encode_value(value, node_refs) for value in args]
            if kwargs or explicit:
                record["kwargs"] = {key: _encode_value(value, node_refs) for key, value in kwargs.items()}
            nodes[name] = record
        return {
            "version": 1,
            "imports": imports,
            "definitions": self.definitions().get_script(),
            "graph": {"nodes": nodes},
        }

    @classmethod
    def fromdict(cls, data: dict) -> "GraphRT":
        """Build a new runtime. Unknown operators and invalid scripts stay editable."""

        if not isinstance(data, dict) or type(data.get("version")) is not int or data["version"] != 1:
            raise ValueError("Unsupported graph format; expected version 1")
        if not isinstance(data.get("definitions"), str):
            raise ValueError("Graph definitions must be a source string")
        if (not isinstance(data.get("imports"), dict) or not isinstance(data.get("graph"), dict)
                or not isinstance(data["graph"].get("nodes"), dict)):
            raise ValueError("Graph imports and nodes must be objects")
        graph = cls(definitions=data["definitions"])
        modules = {"definitions": graph.definitions()}
        for module_id, path in data["imports"].items():
            if not isinstance(module_id, str) or module_id == "definitions" or not isinstance(path, str):
                raise ValueError("Imports must map module names to paths; 'definitions' is reserved")
            module = graph.add_import(path)
            module.set_name(module_id)
            modules[module_id] = module

        nodes = {}
        for name, record in data["graph"]["nodes"].items():
            if not isinstance(name, str) or not isinstance(record, dict):
                raise ValueError("Invalid node record")
            operator = record.get("operator")
            if (not isinstance(operator, dict) or not isinstance(operator.get("module"), str)
                    or operator["module"] not in modules or not isinstance(operator.get("name"), str)):
                raise ValueError(f"Invalid operator reference for node {name!r}")
            ref = OperatorRef(modules[operator["module"]], operator["name"])
            nodes[name] = graph.node()(ref, name=name)

        # Create every node before restoring inputs, allowing forward references.
        for name, record in data["graph"]["nodes"].items():
            args, kwargs = record.get("args", []), record.get("kwargs", {})
            if not isinstance(args, list) or not isinstance(kwargs, dict) or any(not isinstance(k, str) for k in kwargs):
                raise ValueError(f"Invalid inputs for node {name!r}")
            nodes[name].set_inputs(
                *[_decode_value(value, nodes) for value in args],
                **{key: _decode_value(value, nodes) for key, value in kwargs.items()},
            )
        return graph

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