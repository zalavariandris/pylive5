from pygraphrt.graph_rt import GraphRT, NodeRT
from typing import Callable
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
            (graph.node_inputs_changed, self._on_node_changed),
            (graph.node_operator_changed, self._on_node_changed),
            (graph.operators_changed, self._on_operators_changed),
        ]
        self._running = False
        self.start()

    def start(self):
        if self._running:
            return
        for signal, slot in self._connections:
            signal.connect(slot)
        self._running = True

    def _on_node_changed(self, node_name: str):
        if node_name in self._ancestor_names:
            self._ancestor_names = [
                node.get_name()
                for node in self._graph().ancestors(self._node())
            ]
            self._callback()

    def _on_operators_changed(self, changed_names: list[str]):
        ancestor_operator_names = set()

        for node in self._graph().ancestors(self._node()):
            operator = node.get_operator()
            if operator is not None:
                ancestor_operator_names.add(operator.name())

        if ancestor_operator_names.intersection(changed_names):
            self._callback()

    def stop(self):
        if not self._running:
            return
        for signal, slot in self._connections:
            signal.disconnect(slot)
        self._running = False

    def __del__(self):
        self.stop()


def watch(graph:GraphRT, node:NodeRT|None, callback: Callable):
    """Watches the given graph for changes and calls the callback with the change details."""
    assert isinstance(graph, GraphRT)
    assert isinstance(node, NodeRT), f"node must be an instance of NodeRT got {node}"
    return Watcher(graph, node, callback)
