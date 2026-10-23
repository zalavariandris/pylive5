from collections import defaultdict, deque

from qtpy.QtCore import QObject, Signal
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping

type LiteralValue = None | bool | int | float | str
type Value = NodeRef | LiteralValue

@dataclass(frozen=True) # i think data could be frozen. anything here changes would meka the graph downsteam dirty.
class _NodeState:
    operator: Callable|None=None
    args: tuple[Value, ...] = tuple()
    kwargs: MappingProxyType[str, Value] = MappingProxyType({})


@dataclass
class NodeRef:
    _graph: 'Graph'
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

    def graph(self) -> 'Graph':
        return self._graph

    def name(self) -> str:
        return self._name

    def resolve(self) -> _NodeState:
        return self._graph._nodes[self]


class Graph(QObject):
    nodes_added = Signal(list) # list[NodeRef]
    # nodes_about_to_be_added = Signal(list) # list[NodeRef]
    nodes_removed = Signal(list) # list[NodeRef]
    # nodes_about_to_be_removed = Signal(list) # list[NodeRef]
    nodes_changed = Signal(list) # list[NodeRef]

    def __init__(self, parent: QObject|None = None):
        super().__init__(parent=parent)
        self._nodes: dict[NodeRef, _NodeState] = dict()
        self._out_links: dict[NodeRef, dict[NodeRef, set[int | str]]] = {}

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

            # Create or update the named node.
            # NOTE: for now, we want the create unique operator behaviour. See test for decorator behaviours
            
            if node_ref in self._nodes:
                # self._update_node(node_ref, operator, args, dict(kwargs))
                node_ref = self._create_node(func, args, dict(kwargs))
            else:
                node_ref = self._create_node(func, args, dict(kwargs))

            return node_ref

        return decorator

    @staticmethod
    def __input_links(node_state: _NodeState) -> dict[NodeRef, set[int | str]]:
        links: dict[NodeRef, set[int | str]] = {}
        for index, value in enumerate(node_state.args):
            if isinstance(value, NodeRef):
                links.setdefault(value, set()).add(index)
        for name, value in node_state.kwargs.items():
            if isinstance(value, NodeRef):
                links.setdefault(value, set()).add(name)
        return links

    def __store_node(self, node: NodeRef, state: _NodeState) -> None:
        # update node state, and realted links cache
        new_state = _NodeState(
            state.operator,
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

    def in_links(self, node: NodeRef) -> dict[NodeRef, set[int | str]]:
        """Map each source node to the inputs it feeds on this node."""
        return self.__input_links(self._nodes[node])

    def out_links(self, node: NodeRef) -> dict[NodeRef, set[int | str]]:
        """Map each target node to the inputs this node feeds."""
        return {
            target: inlets.copy()
            for target, inlets in self._out_links[node].items()
        }

    def _create_node(self, func:Callable|None=None, args: Iterable=(), kwargs: Mapping={}, *, name: str|None=None) -> NodeRef: 
        assert isinstance(func, Callable) or func is None, f"Expected a Callable or None, got: {func}"
        # derive name from the operator
        if name is None:
            if isinstance(func, Callable):
                name = func.__name__
            else:
                name = "node"

        # ensure the node name is unique within the graph
        existing_names = {node.name() for node in self._nodes.keys()}
        if name in existing_names:
            from pytools import UniqueNameGenerator
            name = UniqueNameGenerator(existing_names)(name)

        self._validate_inputs(args, kwargs)

        # create the node and store its data
        node_ref = NodeRef(self, name)
        node_state = _NodeState(func, tuple(args), MappingProxyType(kwargs))
        self.__store_node(node_ref, node_state)
        # self.nodes_about_to_be_added.emit([node_ref])
        
        self.nodes_added.emit([node_ref])
        return node_ref

    def _update_node(self, node_ref: NodeRef, func:Callable|None=None, args: tuple=(), kwargs: dict={}) -> None:
        assert node_ref in self._nodes, "Node does not exist in the graph." # todo: Api misuse: raise standard python errors
        assert isinstance(node_ref, NodeRef), f"Expected a NodeRef, got: {node_ref}"
        assert func is None or callable(func), f"Expected a Callable or None, got: {func}"
        node_data = _NodeState(func, tuple(args), MappingProxyType(kwargs))
        self.__store_node(node_ref, node_data)
        self.nodes_changed.emit([node_ref])

    def _delete_node(self, node_ref: NodeRef) -> None:
        if node_ref not in self._nodes:
            raise KeyError(node_ref)

        changed_nodes: list[NodeRef] = []
        # Storing consumers changes this map, so iterate over a snapshot.
        for dependent_node_ref in tuple(self._out_links[node_ref]):
            if dependent_node_ref == node_ref:
                continue
            dependend_node_state = self._nodes[dependent_node_ref]
            dependent_func = dependend_node_state.func
            remaining_args = tuple(
                value for value in dependend_node_state.args
                if not (isinstance(value, NodeRef) and value == node_ref)
            )
            remaining_kwargs = {
                key: value for key, value in dependend_node_state.kwargs.items()
                if not (isinstance(value, NodeRef) and value == node_ref)
            }
            self.__store_node(
                dependent_node_ref,
                _NodeState(
                    dependent_func,
                    remaining_args,
                    MappingProxyType(remaining_kwargs),
                ),
            )
            changed_nodes.append(dependent_node_ref)

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

    def ancestors(self, *root: NodeRef) -> set[NodeRef]:
        visited: set[NodeRef] = set(root)
        stack = list(root)
        while stack:
            node_ref = stack.pop()
            node_state: _NodeState = self._nodes[node_ref]
            for v in node_state.args + tuple(node_state.kwargs.values()):
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
            node_state = self._nodes[node]
            # Use a set so each unique predecessor is counted only once
            preds = {
                v for v in node_state.args + tuple(node_state.kwargs.values())
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
