from pygraphrt.graph_rt import GraphRT, NodeRT, OperatorRT
from typing import Literal, Callable
import weakref


class Watcher:
    def __init__(self, graph: GraphRT, node: NodeRT, callback: Callable[[], None]):
        if node not in graph._nodes:
            raise ValueError(f"Node {node.get_name()} is not part of the graph.")
        self._graph = weakref.ref(graph)
        self._node = weakref.ref(node)
        self._callback = callback

        self._ancestor_names = [n.get_name() for n in graph.ancestors(node)]

        self._connections = [
            (graph.node_inputs_changed, lambda node: self._on_change('node', 'inputs', node)),
            (graph.node_operator_changed, lambda node: self._on_change('node', 'operator', node)),
            (graph.operator_function_changed, lambda op: self._on_change('operator', 'function', op))
        ]

        for signal, slot in self._connections:
            signal.connect(slot)

    def _on_change(self, kind:Literal['node', 'operator'], attr: str, obj: str):
        match kind:
            case 'node':
                if obj in self._ancestor_names:
                    self._ancestor_names = [n.get_name() for n in self._graph().ancestors(self._node())]
                    self._callback()
            case 'operator':
                ancestor_operator_names = [n.get_operator().get_name() for n in self._graph().ancestors(self._node())]
                if obj in ancestor_operator_names:
                    self._callback()

    def stop(self):
        for signal, slot in self._connections:
            signal.disconnect(slot)


def watch(graph:GraphRT, node:NodeRT|None, callback: Callable):
    """Watches the given graph for changes and calls the callback with the change details."""
    assert isinstance(graph, GraphRT)
    assert isinstance(node, NodeRT), f"node must be an instance of NodeRT got {node}"
    return Watcher(graph, node, callback)
