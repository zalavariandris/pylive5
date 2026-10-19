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
from .pygraphrt_graphmodel import PyGraphRTGraphModel
from .pygraphrt_node_inlet_tree_model_adapter import PyGraphRTNodeInletTreeModelAdapter


from qdageditor5.adapters.node_inlet_tree_selection_model_adapter import NodeInletTreeSelectionModelAdapter


class PyFlowDocument(QObject):
    def __init__(self, 
        engine: rt.GraphEvaluatorEngine|None=None,
        parent:QObject|None=None
    ):
        super().__init__(parent=parent)
        # RT
        self._engine = engine or rt.GraphEvaluatorEngine(backend=rt.InlineExecutionBackend())

        # Models
        ## Graph Model
        self.graph_model = PyGraphRTGraphModel(self._engine)
        
        self.graphselection_model = GraphSelectionModel(self.graph_model)
        self._engine._invalidator.nodes_invalidated.connect(self._on_nodes_invalidated)
        self.graphselection_model.currentNodeChanged.connect(
            self._on_current_node_changed
        )

        ## Modules Model
        self.modules_model = ModulesOperatorsTreeModel()
        self.modules_model.setSourceRegistry(self._engine._registry)
        self.modulesselection_model = QItemSelectionModel(self.modules_model)

        # Adapters
        ## Node inlet tree adapter
        self.node_inlet_tree_adapter = PyGraphRTNodeInletTreeModelAdapter(self.graph_model)
        self.node_inlet_tree_selection_adapter = NodeInletTreeSelectionModelAdapter(self.node_inlet_tree_adapter)
        self.node_inlet_tree_selection_adapter.setSourceSelection(self.graphselection_model)
        
        # Initial evaluation
        self._engine.request(*self._engine._graph.nodes())

    @Slot(list)
    def _on_nodes_invalidated(self, nodes: list[rt.NodeRef]) -> None:
        current_name = self.graphselection_model.currentNode()
        if current_name is None:
            return

        current = self.graph_model.mapToSource(current_name)
        if current is not None and current in nodes:
            self._engine.request(current)

    @Slot(object, object)
    def _on_current_node_changed(
        self,
        current: NodeName | None,
        previous: NodeName | None,
    ) -> None:
        if current is None:
            return

        node = self.graph_model.mapToSource(current)
        if node is not None:
            self._engine.request(node)

    def close(self) -> None:
        """Stop evaluation and disconnect requests from the graph model."""
        self.graph_model.close()
        self._engine.close()

    def getNodeOperator(self, node_name: NodeName) -> QModelIndex:
        node_ref = self.graph_model.mapToSource(node_name)
        if node_ref is None:
            return QModelIndex()
        
        operator = node_ref.get_operator()
        if operator is None:
            return QModelIndex()

        operator_index = self.modules_model.mapFromSource(operator)
        return operator_index

    # Serialization
    @classmethod
    def fromfile(cls, file_path: str | Path) -> "PyFlowDocument":
        path = Path(file_path).resolve()
        data = json.loads(path.read_text(encoding="utf-8"))
        deserializer = rt.GraphDeserializer(base_dir=path.parent)
        registry, graph = deserializer.fromdict(data)
        doc = cls(engine=rt.GraphEvaluatorEngine(graph=graph, registry=registry))
        return doc

    def save(self, file_path: str | Path) -> None:
        """Save the runtime and node positions as UTF-8 JSON."""
        serializer = rt.GraphSerializer(self._engine._graph, self._engine._registry)
        data = serializer.todict()

        # inject position
        for name, record in data.get("graph", {}).get("nodes", {}).items():
            position = self.graph_model.nodePosition(name)
            record["position"] = [position.x(), position.y()]

        text = json.dumps(data, indent=4)
        Path(file_path).write_text(text, encoding="utf-8")

    # Editing
    def addNode(self, operator_index:QModelIndex, scene_pos:QPointF|None=None):
        assert operator_index.isValid(), "Operator index must be valid."
        assert operator_index.model() is self.modules_model, "Operator index must belong to the modules model."
        selected_op_ref = operator_index.data(ModulesOperatorsTreeModel.OperatorRole)
        if selected_op_ref:
            self.graph_model.addNode(selected_op_ref, scene_pos or QPointF(0, 0))

    def deleteSelectedNodes(self):
        selected_nodes = self.graphselection_model.selectedNodes()
        self.graph_model.removeNodes(selected_nodes)

    def restart_graph(self):
        """Recover the model/view while preserving the current runtime and script."""
        # todo: this needs to be reimplemented
        self.graph_model.reset_graph_from_scratch()

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
