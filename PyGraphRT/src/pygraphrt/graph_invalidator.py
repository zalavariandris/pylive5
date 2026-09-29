from .graph_definition_rt import GraphDefinitionRT, NodeRef
from .module_registry import ModuleRegistry
from qtpy.QtCore import QObject, Signal


class GraphInvalidator(QObject):
    nodes_invalidated: Signal = Signal(list[NodeRef])

    def __init__(self, graph: GraphDefinitionRT, module_registry: ModuleRegistry):
        self.graph = graph
        self.registry = module_registry

        def invalidate_nodes_descendants(nodes):
            invalidate_nodes = []
            for node in nodes:
                descendants = self.graph.descendants(node)
                invalidate_nodes.extend(descendants)
            self.nodes_invalidated.emit(invalidate_nodes)

        self.graph.nodes_added.connect(invalidate_nodes_descendants)
        self.graph.nodes_removed.connect(invalidate_nodes_descendants)
        self.graph.nodes_changed.connect(invalidate_nodes_descendants)
            
        def invalidate_operator_nodes_descendants(operators):
            invalidate_nodes = []
            for op in operators:
                for node in self.graph.nodes_of_operator(op):
                    descendants = self.graph.descendants(node)
                    invalidate_nodes.extend(descendants)

            self.nodes_invalidated.emit(invalidate_nodes)

        self.registry.operators_added.connect(invalidate_operator_nodes_descendants)          
        self.registry.operators_removed.connect(invalidate_operator_nodes_descendants)
        self.registry.operators_changed.connect(invalidate_operator_nodes_descendants)
