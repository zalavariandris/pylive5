from pygraphrt.graph_invalidator import GraphInvalidator

from .graph_definition_rt import GraphDefinitionRT
from .module_registry import ModuleRegistry
from .graph_evaluator import GraphEvaluator
from .graph_evaluator import QtThreadPoolExecutionBackend
from .graph_evaluator import GraphCache
from .graph_invalidator import GraphInvalidator
from qtpy.QtCore import QObject

class PyGraphEngine(QObject):
    def __init__(self, 
        graph: GraphDefinitionRT|None = None,
        registry: ModuleRegistry|None = None,
        parent: QObject|None = None
    ):
        super().__init__(parent=parent)

        self.graph = graph or GraphDefinitionRT(parent=self)
        self.registry = registry or ModuleRegistry(parent=self)
        
        backend = QtThreadPoolExecutionBackend()
        
        invalidator = GraphInvalidator(
            self.graph, 
            self.registry, 
            parent=self
        )

        self.cache = GraphCache()

        self.evaluator = GraphEvaluator(
            self.graph, 
            backend,
            invalidator = invalidator,
            cache = self.cache
        )

    def close(self) -> None:
        self.evaluator._backend.close()