from qtpy.QtCore import QObject, Signal

from .graph import Graph, NodeRef
from .inline_scriptmodule import InlineScriptModule, ScriptOperatorRef
from .relations import ManyToOneRelation
from .inline_executor import InlineExecutor, ExecutionFailure


class Engine(QObject):
    nodes_invalidated = Signal(list)
    nodes_executed = Signal(dict)
    execution_failed = Signal(Exception)
    registry_invalidated = Signal()
    registry_evaluated = Signal()
    registry_failed = Signal(Exception)

    def __init__(
        self, graph: Graph | None = None, registry: InlineScriptModule | None = None,
    ) -> None:
        super().__init__()
        self.graph = graph if graph is not None else Graph()
        self.registry = registry if registry is not None else InlineScriptModule()
        self._executor = InlineExecutor(self.graph)
        self._closed = False
        self._operator_to_nodes = ManyToOneRelation[NodeRef, ScriptOperatorRef]()
        self._sync_node_operator_mappings(self.graph.nodes())
        self._connections = [
            (self.graph.nodes_added, self._on_nodes_changed),
            (self.graph.nodes_changed, self._on_nodes_changed),
            (self.graph.nodes_removed, self._remove_node_operator_mappings),
            (self.registry.registry_invalidated, self.registry_invalidated.emit),
        ]
        for signal, slot in self._connections:
            signal.connect(slot)

    def evaluate_registry(self) -> None:
        if self._closed:
            return
        try:
            self.registry.evaluate()
        except Exception as error:
            self.registry_failed.emit(error)
        else:
            self.registry_evaluated.emit()
        # Operator references stay on nodes even if their functions disappear.
        # All bindings and presentation notifications are committed before execution.
        self._invalidate_descendants(self.graph.nodes())

    def execute(self, *targets: NodeRef) -> None:
        if self._closed:
            return
        try:
            outputs = self._executor.execute(*targets)
        except ExecutionFailure as error:
            self.execution_failed.emit(error)
        else:
            self.nodes_executed.emit(outputs)

    def node_operator(self, node_ref: NodeRef) -> ScriptOperatorRef | None:
        """Return the node's script binding, including unavailable references."""
        return self._operator_to_nodes.parent_of(node_ref)

    def _on_nodes_changed(self, nodes: list[NodeRef]) -> None:
        self._sync_node_operator_mappings(nodes)
        self._invalidate_descendants(nodes)

    def _invalidate_descendants(self, nodes: list[NodeRef]) -> None:
        affected: set[NodeRef] = set()
        for node in nodes:
            affected.update(self.graph.descendants(node))
        if affected:
            self.nodes_invalidated.emit([node for node in self.graph.nodes() if node in affected])

    def _sync_node_operator_mappings(self, nodes: list[NodeRef]) -> None:
        # This is an index of the bindings stored on nodes, not separate state.
        # An unavailable reference remains bound; None or a plain callable does not.
        for node in nodes:
            operator = node.resolve().operator
            previous = self._operator_to_nodes.parent_of(node)
            if isinstance(operator, ScriptOperatorRef):
                self._operator_to_nodes.set(node, operator)
            elif previous is not None:
                self._operator_to_nodes.delete(node, previous)

    def _remove_node_operator_mappings(self, nodes: list[NodeRef]) -> None:
        # Graph emits nodes_changed for surviving consumers after removing links.
        for node in nodes:
            operator = self._operator_to_nodes.parent_of(node)
            if operator is not None:
                self._operator_to_nodes.delete(node, operator)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for signal, slot in self._connections:
            signal.disconnect(slot)
        self._connections.clear()
