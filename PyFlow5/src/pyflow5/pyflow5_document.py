import json
import math
from pathlib import Path
from textwrap import dedent
import traceback


from qdageditor5.models.abstract_dag_model import NodeName
from qtpy.QtCore import QItemSelectionModel, QModelIndex, QObject, QPointF, Signal, Slot

import pygraphrt as rt
from qdageditor5.models.graph_selection_model import GraphSelectionModel

from .modules_operator_tree_model import ModulesOperatorsTreeModel
from .pygraphrt_dag_model import PyFlowRTModel
from .inspector.pygraphrt_nodes_inputs_tree_model import NodesTreeAdapterModel


class PyFlowDocument(QObject):
    def __init__(self, 
        graph: rt.GraphDefinitionRT|None=None, 
        registry: rt.ModuleRegistry|None=None,
        parent:QObject|None=None
    ):
        super().__init__(parent=parent)
        # RT
        self._module_registry = registry or rt.ModuleRegistry()
        self._graph = graph or rt.GraphDefinitionRT()

        self._executor = rt.GraphExecutorRT(self._graph)
        self._invalidator = rt.GraphInvalidator(self._graph, self._module_registry)

        # Models
        self.graph_model = PyFlowRTModel(
            self._graph, 
            self._module_registry, 
            self._invalidator,
            self._executor
        )

        self.modules_model = ModulesOperatorsTreeModel(parent=self)
        self.modules_model.setSourceRegistry(self._module_registry)
        self.modulesselection_model = QItemSelectionModel(self.modules_model)

        self.graphselection_model = GraphSelectionModel(self.graph_model)
        self.nodes_tree_model = NodesTreeAdapterModel(self._graph, self._module_registry)

        # initial execution
        for node_ref in self._graph.nodes():
            self._executor.execute(node_ref)

    def getNodeOperator(self, node_name: NodeName) -> QModelIndex|None:
        node_ref = self.graph_model.mapToSource(node_name)
        if node_ref is None:
            return None
        
        operator = node_ref.get_operator()
        if operator is None:
            return None

        operator_index = self.modules_model.mapFromSource(operator)
        return operator_index

    @classmethod
    def fromfile(cls, file_path: str | Path) -> "PyFlowDocument":
        path = Path(file_path).resolve()
        data = json.loads(path.read_text(encoding="utf-8"))
        deserializer = rt.GraphDeserializer(base_dir=path.parent)
        registry, graph = deserializer.fromdict(data)
        doc = cls(graph=graph, registry=registry)
        return doc

    def save(self, file_path: str | Path) -> None:
        """Save the runtime and node positions as UTF-8 JSON."""
        serializer = rt.GraphSerializer(self._graph, self._module_registry)
        data = serializer.todict()

        # inject position
        for name, record in data.get("graph", {}).get("nodes", {}).items():
            position = self.graph_model.nodePosition(name)
            record["position"] = [position.x(), position.y()]

        text = json.dumps(data, indent=4)
        Path(file_path).write_text(text, encoding="utf-8")

    def addNode(self, operator_index:QModelIndex, scene_pos:QPointF|None=None):
        assert operator_index.isValid(), "Operator index must be valid."
        assert operator_index.model() is self.modules_model, "Operator index must belong to the modules model."
        selected_op_ref = operator_index.data(ModulesOperatorsTreeModel.OperatorRole)
        if selected_op_ref:
            self.graph_model.addNode(selected_op_ref, scene_pos or QPointF(0, 0))

    def deleteSelectedNodes(self):
        selected_nodes = self.graphselection_model.selectedNodes()
        self.graph_model.removeNodes(selected_nodes)

    def reset_graph(self):
        """Recover the model/view while preserving the current runtime and script."""
        # self.setOutputNode(None)
        self.graph_model.reset_graph_from_scratch()
        # self.setOutputLocked(False)

    def addEmbeddedModule(self, name="_local_") -> None:
        if module_idx := self.modules_model.addEmbeddedModule(name):
            self.modulesselection_model.setCurrentIndex(
                module_idx, 
                QItemSelectionModel.ClearAndSelect
            )

    def removeSelectedModule(self) -> None:
        current_index = self.modulesselection_model.currentIndex()
        if current_index:
            self.modules_model.removeModule(current_index)

    def importModule(self, file_path: str) -> None:
        if module_idx := self.modules_model.importModule(file_path):
            self.modulesselection_model.setCurrentIndex(
                module_idx, 
                QItemSelectionModel.ClearAndSelect
            )
