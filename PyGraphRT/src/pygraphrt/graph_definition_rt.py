"""The runtime representation of a computation graph definition."""

from collections import deque, defaultdict
from types import MappingProxyType
from typing import Any, Callable, Callable, Any, Iterable, Mapping

import math
from pathlib import Path

from dataclasses import dataclass, field

from qtpy.QtCore import (
    QObject, 
    Signal
)

from .relations import ManyToOneRelation
from .import_module import ImportModuleRT
from .script_module import ScriptModuleRT
from .graph_schema import validate_graph_data
from .abstract_module_rt import AbstractOperator

from .errors import (
    ModuleError,
    GraphExecutionError
)

from .function_operator import FunctionOperator


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

    def get_operator(self) -> AbstractOperator|None:
        operator_ref = self._graph._operator_to_nodes.parent_of(self)
        return operator_ref

    def set_inputs(self, *args, **kwargs) -> None:
        self._graph._validate_inputs(*args, **kwargs)
        current_operator: AbstractOperator|None = self._graph._operator_to_nodes.parent_of(self)
        self._graph._update_node(self, current_operator, args, kwargs)

    def get_inputs(self) -> tuple[tuple[Value], dict[str, Value]]:
        node_data: _NodeState = self._graph._nodes[self]
        return node_data.get_inputs()
        

type LiteralValue = None | bool | int | float | str
type Value = NodeRef | LiteralValue

@dataclass(frozen=True) # i think data could be frozen. anything here changes would meka the graph downsteam dirty.
class _NodeState:
    args: tuple[Value, ...] = tuple()
    kwargs: MappingProxyType[str, Value] = MappingProxyType({})

    def get_inputs(self)->Iterable[tuple[tuple[Value, ...], MappingProxyType[str, Value]]]:
        return tuple(self.args), MappingProxyType({
            k: v for k, v in self.kwargs.items()
        }) # todo: create a view
    

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





class GraphDefinitionRT(QObject):
    nodes_added = Signal(list) # list[NodeRef]
    # nodes_about_to_be_added = Signal(list) # list[NodeRef]
    nodes_removed = Signal(list) # list[NodeRef]
    # nodes_about_to_be_removed = Signal(list) # list[NodeRef]
    nodes_changed = Signal(list) # list[NodeRef]

    def __init__(self):
        super().__init__()

        self._local = ScriptModuleRT("_local_", parent=self)
        self._nodes: dict[NodeRef, _NodeState] = dict()
        self._out_links: dict[NodeRef, dict[NodeRef, set[int | str]]] = {}
        self._operator_to_nodes = ManyToOneRelation[NodeRef, AbstractOperator]()

    def setLocalDefinitions(self, test: str) -> None:
        self._local.set_script(test)

    def local(self) -> ScriptModuleRT:
        """Return the local script module containing user-defined functions."""
        return self._local

    def operators(self) -> Iterable[AbstractOperator]:
        for node in self._nodes:
            yield from self._operator_to_nodes.parent_of(node)

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
        def decorator(func: Callable) -> NodeRef:
            is_function = lambda f: callable(f) and hasattr(f, "__code__")

            assert is_function(func), f"Expected a Python function, got: {func}"

            name = func.__name__
            node_ref = NodeRef(self, name)
            operator = FunctionOperator(func)
            # Create or update the named node.
            # NOTE: for now, we want the create unique operator behaviour. See test for decorator behaviours
            
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

    def __store_node_data(self, node: NodeRef, state: _NodeState) -> None:
        """Store inputs and their reverse index together, without emitting signals."""
        # Own the containers so external mutations cannot bypass the index.
        new_state = _NodeState(
            tuple(state.args),
            MappingProxyType(dict(state.kwargs)),
        )
        self._validate_inputs(*new_state.args, **new_state.kwargs)

        new_links = self.__input_links(new_state)
        previous_state: _NodeState | None = self._nodes.get(node)
        if previous_state is not None:
            for source in self.__input_links(previous_state):
                del self._out_links[source][node]

        # Preserve this node's outgoing connections to its consumers.
        self._out_links.setdefault(node, {})
        for source, inlets in new_links.items():
            self._out_links[source][node] = inlets

        self._nodes[node] = new_state

    def __get_node_data(self, node: NodeRef) -> _NodeState:
        return self._nodes[node]

    def nodes_of_operator(self, operator: AbstractOperator) -> frozenset[NodeRef]:
        # todo: consider caching operator to node mapping for efficiency or creating a table to author operator node relationhips
        return self._operator_to_nodes.children_of(operator)    

    def in_links(self, node: NodeRef) -> dict[NodeRef, set[int | str]]:
        """Map each source node to the inputs it feeds on this node."""
        return self.__input_links(self._nodes[node])

    def out_links(self, node: NodeRef) -> dict[NodeRef, set[int | str]]:
        """Map each target node to the inputs this node feeds."""
        return {
            target: inlets.copy()
            for target, inlets in self._out_links[node].items()
        }

    def _create_node(self, operator:AbstractOperator|None=None, args: Iterable=(), kwargs: Mapping={}) -> NodeRef: 
        assert isinstance(operator, AbstractOperator) or operator is None, f"Expected an AbstractOperator or None, got: {operator}"
        # derive name from the operator
        if isinstance(operator, AbstractOperator):
            name = operator.get_name()
        else:
            name = "node"

        self._validate_inputs(args, kwargs)

        # ensure the node name is unique within the graph
        existing_names = {node.get_name() for node in self._nodes.keys()}
        if name in existing_names:
            from pytools import UniqueNameGenerator
            name = UniqueNameGenerator(existing_names)(name)

        # create the node and store its data
        node_ref = NodeRef(self, name)
        node_state = _NodeState(tuple(args), MappingProxyType(kwargs))
        self.__store_node_data(node_ref, node_state)
        self._operator_to_nodes.set(node_ref, operator)
        # self.nodes_about_to_be_added.emit([node_ref])
        
        self.nodes_added.emit([node_ref])
        return node_ref

    def _update_node(self, node_ref: NodeRef, op:AbstractOperator=None, args: tuple=(), kwargs: dict={}) -> None:
        assert node_ref in self._nodes, "Node does not exist in the graph." # todo: Api misuse: raise standard python errors
        assert isinstance(node_ref, NodeRef), f"Expected a NodeRef, got: {node_ref}"
        assert isinstance(op, AbstractOperator) or op is None, f"Expected an AbstractOperator or None, got: {op}"
        node_data = _NodeState(tuple(args), MappingProxyType(kwargs))
        self._operator_to_nodes.set(node_ref, op)
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
                    remaining_args,
                    MappingProxyType(remaining_kwargs),
                ),
            )
            changed_nodes.append(dependent)

        if changed_nodes:
            self.nodes_changed.emit(changed_nodes)

        # Detach the deleted node from its own input sources.
        for source in self.__input_links(self._nodes[node_ref]):
            del self._out_links[source][node_ref]

        del self._out_links[node_ref]
        del self._nodes[node_ref]

        # All state is consistent; watchers of the deleted node can stop first.
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
        if self.local().get_source() or explicit:
            data["_local_"] = self.local().get_source()
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
            op_ref = AbstractOperator(modules_by_id[operator["module"]], operator["name"])
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
