from collections import deque, defaultdict
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Callable, Callable, Any, Iterable, Mapping

import math
from pathlib import Path

from dataclasses import dataclass, field

from qtpy.QtCore import (
    QObject, 
    Signal
)

from myutils.profiler import Profiler

if TYPE_CHECKING:
    from .abstract_module_rt import AbstractOperator, OperatorRef

from .inline_module import InlineModuleRT
from .import_module import ImportModuleRT
from .script_module import ScriptModuleRT
from .graph_schema import validate_graph_data
from .abstract_module_rt import OperatorRef
from .abstract_module_rt import AbstractOperator

from .errors import (
    ModuleError,
    GraphExecutionError
)


@dataclass
class NodeRef:
    _graph: 'GraphDefinitionRT'
    _name: str

    def __repr__(self):
        return f"NodeRef('{self._name}')"

    def __call__(self) -> Any:
        if operator_ref:=self.get_operator():
            args, kwargs = self.get_inputs()
            return operator_ref(*args, **kwargs)
        else:
            raise GraphExecutionError(f"Operator {self.get_operator()} is missing from the graph")
        
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
        self._graph._validate_inputs(*args, **kwargs)
        # next_data = NodeData(, args, dict(kwargs))
        self._graph._update_node(self, prev_data.get_operator(), args, kwargs)

    def get_inputs(self) -> tuple[tuple[Value], dict[str, Value]]:
        node_data = self._graph._nodes[self]
        return node_data.get_inputs()
        

type LiteralValue = None | bool | int | float | str
type Value = NodeRef | LiteralValue

@dataclass(frozen=True) # i think data could be frozen. anything here changes would meka the graph downsteam dirty.
class _NodeState:
    operator: OperatorRef|None
    args: tuple[Value, ...] = tuple()
    kwargs: MappingProxyType[str, Value] = MappingProxyType({})

    def get_inputs(self)->Iterable[tuple[tuple[Value, ...], MappingProxyType[str, Value]]]:
        return tuple(self.args), MappingProxyType({
            k: v for k, v in self.kwargs.items()
        }) # todo: create a view

    def get_operator(self) -> OperatorRef|None:
        return self.operator

    def __call__(self, *args, **kwargs) -> Any:
        raise NotImplementedError("__call__ is not implemented for NodeRef")


def _encode_value(value, nodes):
    from .graph_definition_rt import NodeRef

    if type(value) in (type(None), bool, int, str):
        return value

    if type(value) is float:
        return value if math.isfinite(value) else {"type": "float", "value": value.hex()}

    if type(value) is list:
        return [_encode_value(item, nodes) for item in value]

    if type(value) is tuple:
        return {"type": "tuple", "items": [_encode_value(item, nodes) for item in value]}

    if type(value) is dict:
        return {"type": "dict", "items": [
            [_encode_value(key, nodes), _encode_value(item, nodes)]
            for key, item in value.items()
        ]}

    if isinstance(value, NodeRef):
        if value not in nodes:
            raise ValueError(f"Input references a node outside this graph: {value}")
        return {
            "type": "node", 
            "name": value.get_name()
        }

    if isinstance(value, Path):
        return {"type": "path", "value": str(value)}
    
    raise TypeError(f"Cannot save input of type: {type(value).__name__!r}")

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


from .script_module_registry import ScriptModuleRegistry


from .relations import OneToManyRelation

class GraphDefinitionRT(QObject):
    nodes_added = Signal(list) # list[NodeRef]
    # nodes_about_to_be_added = Signal(list) # list[NodeRef]
    nodes_removed = Signal(list) # list[NodeRef]
    # nodes_about_to_be_removed = Signal(list) # list[NodeRef]
    nodes_changed = Signal(list) # list[NodeRef]

    def __init__(self):
        super().__init__()

        # self._module_registry: ScriptModuleRegistry = module_registry # List of imported modules
        self._inline_module: InlineModuleRT = InlineModuleRT(parent=self) # hold runtime functions. created with the node decorators
        self._local = ScriptModuleRT("_local_", parent=self)
        self._nodes: dict[NodeRef, _NodeState] = dict()
        self._out_links: dict[NodeRef, dict[NodeRef, set[int | str]]] = {}

        self._node_to_operators = OneToManyRelation[NodeRef, OperatorRef]()

    def setLocalDefinitions(self, test: str) -> None:
        self._local.set_script(test)

    def inline(self) -> InlineModuleRT:
        """Return the inline module containing runtime functions.
        Created with the node decorators."""
        return self._inline_module

    def local(self) -> ScriptModuleRT:
        """Return the local script module containing user-defined functions."""
        return self._local

    # def imports(self) -> list[ImportModuleRT]:
    #     return list(self._module_registry)

    # def modules(self):
    #     """Modules available to the editor, including unused imports."""
    #     if self._module_registry is not None:
    #         return [self._local, *self._module_registry.modules()]
    #     else:
    #         return [self._local]

    # def add_import(self, module: ImportModuleRT) -> None:
    #     if not isinstance(module, ImportModuleRT):
    #         raise TypeError("Only imported modules can be added; edit local module for embedded code")
    #     if module not in self._module_registry:
    #         self._module_registry.append(module)
    #         self.modules_changed.emit()

    # def remove_import(self, module: ImportModuleRT) -> None:
    #     if module not in self._module_registry:
    #         raise KeyError("Import module is not in this graph")
    #     self._module_registry.remove(module)
    #     self.modules_changed.emit()

    def op(self) -> Callable[[Callable], OperatorRef]:
        return self._inline_module.op()

    def operators(self) -> list[OperatorRef]:
        # todo: this method is misleading; it only returns inline module operators, not all operators in the graph.
        return list(self._inline_module._operators.keys())

    def get_operator(self, op_ref: OperatorRef) -> AbstractOperator:
        if op_ref not in self._inline_module._operators:
            raise ModuleError(f"Operator {op_ref} does not exist in the graph.")
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
            assert (
                isinstance(func, OperatorRef)
                or (callable(func) and hasattr(func, "__code__"))
            ), f"Expected a Python function or an OperatorRef, got: {func}"

            self._validate_inputs(*args, **kwargs)

            # Reuse an operator reference or register the function.
            if isinstance(func, OperatorRef):
                operator = func
            else:
                operator = self._inline_module.op()(func)

            if name is None:
                name = operator.get_name()

            # Create or update the named node.
            # NOTE: for now, we want the create unique operator behaviour. See test for decorator behaviours
                    #       todo: write this down somewhere. what create and rebind behaviour means here.
            node_ref = NodeRef(self, name)
            if node_ref in self._nodes:
                # self._update_node(node_ref, operator, args, dict(kwargs))
                node_ref = self._create_node(operator, args, dict(kwargs))
            else:
                node_ref = self._create_node(operator, args, dict(kwargs))

            return node_ref

        return decorator

    @staticmethod
    def __input_links(data: _NodeState) -> dict[NodeRef, set[int | str]]:
        links: dict[NodeRef, set[int | str]] = {}
        for index, value in enumerate(data.args):
            if isinstance(value, NodeRef):
                links.setdefault(value, set()).add(index)
        for name, value in data.kwargs.items():
            if isinstance(value, NodeRef):
                links.setdefault(value, set()).add(name)
        return links

    def __store_node_data(self, node: NodeRef, data: _NodeState) -> None:
        """Store inputs and their reverse index together, without emitting signals."""
        # Own the containers so external mutations cannot bypass the index.
        data = _NodeState(
            data.operator,
            tuple(data.args),
            MappingProxyType(dict(data.kwargs)),
        )
        self._validate_inputs(*data.args, **data.kwargs)

        new_links = self.__input_links(data)
        previous = self._nodes.get(node)
        if previous is not None:
            for source in self.__input_links(previous):
                del self._out_links[source][node]

        # Preserve this node's outgoing connections to its consumers.
        self._out_links.setdefault(node, {})
        for source, inlets in new_links.items():
            self._out_links[source][node] = inlets

        self._nodes[node] = data

    def operator_nodes(self, operator: OperatorRef) -> list[NodeRef]:
        # todo: consider caching operator to node mapping for efficiency or creating a table to author operator node relationhips
        return [
            node for node, data in self._nodes.items()
            if data.operator == operator
        ]

    def in_links(self, node: NodeRef) -> dict[NodeRef, set[int | str]]:
        """Map each source node to the inputs it feeds on this node."""
        return self.__input_links(self._nodes[node])

    def out_links(self, node: NodeRef) -> dict[NodeRef, set[int | str]]:
        """Map each target node to the inputs this node feeds."""
        return {
            target: inlets.copy()
            for target, inlets in self._out_links[node].items()
        }

    def _create_node(self, operator:OperatorRef|None=None, args: Iterable=(), kwargs: Mapping={}) -> NodeRef: 
        assert isinstance(operator, OperatorRef) or operator is None, f"Expected an OperatorRef or None, got: {operator}"
        # derive name from the operator
        if isinstance(operator, OperatorRef):
            name = operator.get_name()
        else:
            name = "node"

        # ensure the node name is unique within the graph
        existing_names = {node.get_name() for node in self._nodes.keys()}
        if name in existing_names:
            from pytools import UniqueNameGenerator
            name = UniqueNameGenerator(existing_names)(name)

        # create the node and store its data
        node_ref = NodeRef(self, name)
        node_data = _NodeState(operator, tuple(args), MappingProxyType(kwargs))
        # self.nodes_about_to_be_added.emit([node_ref])
        self.__store_node_data(node_ref, node_data)
        self.nodes_added.emit([node_ref])
        return node_ref

    def _update_node(self, node_ref: NodeRef, op:OperatorRef=None, args: tuple=(), kwargs: dict={}) -> None:
        assert node_ref in self._nodes, "Node does not exist in the graph." # todo: Api misuse: raise standard python errors
        if op is None:
            op = self._nodes[node_ref].get_operator()
        node_data = _NodeState(op, tuple(args), MappingProxyType(kwargs))
        self.__store_node_data(node_ref, node_data)
        self.nodes_changed.emit([node_ref])

    # deprecated for now
    # def _set_node(self, node_ref: NodeRef, node_data: NodeData) -> None:
    #     if node_ref in self._nodes:
    #         self._update_node(node_ref, node_data.get_operator(), node_data.get_inputs()[0], node_data.get_inputs()[1])
    #     else:
    #         self._create_node(node_data.get_operator(), node_data.get_inputs()[0], node_data.get_inputs()[1])

    def _delete_node(self, node_ref: NodeRef) -> None:
        if node_ref not in self._nodes:
            raise KeyError(node_ref)

        changed_nodes: list[NodeRef] = []
        # Storing consumers changes this map, so iterate over a snapshot.
        for dependent in tuple(self._out_links[node_ref]):
            if dependent == node_ref:
                continue
            node_data = self._nodes[dependent]
            args, kwargs = node_data.get_inputs()
            remaining_args = tuple(
                value for value in args
                if not (isinstance(value, NodeRef) and value == node_ref)
            )
            remaining_kwargs = {
                key: value for key, value in kwargs.items()
                if not (isinstance(value, NodeRef) and value == node_ref)
            }
            self.__store_node_data(
                dependent,
                _NodeState(
                    node_data.get_operator(),
                    remaining_args,
                    MappingProxyType(remaining_kwargs),
                ),
            )
            changed_nodes.append(dependent)

        # Detach the deleted node from its own input sources.
        for source in self.__input_links(self._nodes[node_ref]):
            del self._out_links[source][node_ref]

        del self._out_links[node_ref]
        del self._nodes[node_ref]

        # All state is consistent; watchers of the deleted node can stop first.
        self.nodes_removed.emit([node_ref])
        if changed_nodes:
            self.nodes_changed.emit(changed_nodes)

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

    def successors(self, node: NodeRef) -> set[NodeRef]:
        """Return direct dependants as an independent set."""
        return set(self._out_links[node])

    def descendants(self, root: NodeRef) -> set[NodeRef]:
        """Return root and all downstream dependants, including in cyclic graphs."""
        if root not in self._nodes:
            raise KeyError(root)

        visited: set[NodeRef] = {root}
        stack: list[NodeRef] = [root]
        while stack:
            node = stack.pop()
            for target in self._out_links[node]:
                if target not in visited:
                    visited.add(target)
                    stack.append(target)
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

    def todict(self, explicit: bool = False) -> dict[str, Any]:
        """Save the graph, using short _local_ operator names unless explicit."""

        data: dict[str, Any] = {
            "version": 1
        }

        # add imports
        module_ids: dict[ScriptModuleRT, str] = {}

        imports_data: list[str] = []
        for module in self._module_registry:
            path = str(module.path())
            if not path or path == "_local_" or path in imports_data:
                raise ValueError(f"Import path {path!r} must be nonempty, unique, and cannot be '_local_'")
            module_ids[module] = path
            imports_data.append(path)

        if imports_data or explicit:
            data["imports"] = imports_data

        # add the local definitions
        if self.local().get_script() or explicit:
            data["_local_"] = self.local().get_script()
        module_ids[self.local()] = "_local_"

        # add graph nodes
        nodes = {}
        node_refs = set(self.nodes())
        for node in self.nodes():
            name = node.get_name()
            if not isinstance(name, str):
                raise TypeError("Saved node names must be strings")
            operator = node.get_operator()
            if operator.module not in module_ids:
                raise ValueError(f"Node {name!r} must use the local script module or a registered import")
            args, kwargs = node.get_inputs()
            record: dict[str, Any] = {
                "operator": operator.name
                if operator.module is self.local() and not explicit
                else {"module": module_ids[operator.module], "name": operator.name}
            }
            if args or explicit:
                record["args"] = [_encode_value(value, node_refs) for value in args]
            if kwargs or explicit:
                record["kwargs"] = {key: _encode_value(value, node_refs) for key, value in kwargs.items()}

            nodes[name] = record

        if nodes or explicit:
            data["graph"] = {"nodes": nodes}

        return data

    @classmethod
    def fromdict(cls, data: dict[str, Any]) -> "GraphDefinitionRT":
        """Build a new runtime. Unknown operators and invalid scripts stay editable."""

        validate_graph_data(data)

        local_definitions = data.get("_local_", "")
        imports = data.get("imports", [])
        graph_data = data.get("graph", {"nodes": {}})
        if len(imports) != len(set(imports)):
            raise ValueError("Import paths must be unique")

        module_ids = {"_local_", *imports}
        for name, record in graph_data["nodes"].items():
            operator = record["operator"]
            if isinstance(operator, dict) and operator["module"] not in module_ids:
                raise ValueError(f"Invalid operator reference for node {name!r}")

        graph = cls()
        modules_by_id: dict[str, ScriptModuleRT] = {"_local_": graph.local()}
        graph.setLocalDefinitions(local_definitions)
        for path in imports:
            import_module = ImportModuleRT(path)
            graph.add_import(import_module)
            modules_by_id[path] = import_module

        nodes: dict[str, NodeRef] = {}
        for name, record in graph_data["nodes"].items():
            operator = record["operator"]
            if isinstance(operator, str):
                operator = {"module": "_local_", "name": operator}
            op_ref = OperatorRef(modules_by_id[operator["module"]], operator["name"])
            nodes[name] = graph._create_node(op_ref)

        # Create every node before restoring inputs, allowing forward references.
        for name, record in graph_data["nodes"].items():
            args, kwargs = record.get("args", []), record.get("kwargs", {})
            nodes[name].set_inputs(
                *[_decode_value(value, nodes) for value in args],
                **{key: _decode_value(value, nodes) for key, value in kwargs.items()},
            )
        return graph


if __name__ == "__main__":
    G = GraphDefinitionRT()

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

    executor = GraphExecutorRT(G)

    result = executor.execute(mult)
    print(result)
