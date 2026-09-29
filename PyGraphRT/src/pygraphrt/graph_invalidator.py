from qtpy.QtCore import QObject, Signal

from .graph_definition_rt import GraphDefinitionRT, NodeRef
from .module_registry import ModuleRegistry


class GraphInvalidator(QObject):
    nodes_invalidated: Signal = Signal(list) # list[NodeRef]

    def __init__(self, graph: GraphDefinitionRT, module_registry: ModuleRegistry|None=None):
        super().__init__()
        self._graph = graph
        self._registry: ModuleRegistry|None= module_registry

        self._graph.nodes_added.connect(self._invalidate_nodes_descendants)
        self._graph.nodes_removed.connect(self._invalidate_nodes_descendants)
        self._graph.nodes_changed.connect(self._invalidate_nodes_descendants)
            
        if self._registry is not None:
            self._registry.operators_added.connect(self._invalidate_operator_nodes_descendants)          
            self._registry.operators_removed.connect(self._invalidate_operator_nodes_descendants)
            self._registry.operators_changed.connect(self._invalidate_operator_nodes_descendants)

    def _invalidate_nodes_descendants(self, nodes):
        invalidate_nodes = []
        for node in nodes:
            descendants = self._graph.descendants(node)
            invalidate_nodes.extend(descendants)
        self.nodes_invalidated.emit(invalidate_nodes)

    def _invalidate_operator_nodes_descendants(self, operators):
        invalidate_nodes = []
        for op in operators:
            for node in self._graph.nodes_of_operator(op):
                descendants = self._graph.descendants(node)
                invalidate_nodes.extend(descendants)

        self.nodes_invalidated.emit(invalidate_nodes)
