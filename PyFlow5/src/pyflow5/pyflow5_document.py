import json
import math
from pathlib import Path
import traceback

from pygraphrt.errors import GraphExecutionError
from pygraphrt import ScriptModuleRT
from qdageditor5.models.abstract_dag_model import NodeName
from qtpy.QtCore import QItemSelectionModel, QModelIndex, QObject, QPointF, Signal, Slot

import pygraphrt as rt
from qdageditor5.models.graph_selection_model import GraphSelectionModel

from .modules_operator_tree_model import ModulesOperatorsTreeModel
from .pygraphrt_details_model import GraphDetailsModel
from .pygraphrt_model import PyFlowRTModel



class PyFlowDocument(QObject):
    def __init__(self, parent:QObject|None=None):
        super().__init__(parent=parent)
        # RT
        self._graph = rt.GraphDefinitionRT()
        self._executor = rt.GraphExecutorRT(self._graph)
        self._module_registry = rt.ScriptModuleRegistry()
        local_module = rt.ScriptModuleRT(name="<local>")
        self._module_registry.add_module(local_module)
        self._resolver = rt.GraphResolver(self._graph, self._module_registry)

        # Models
        self.graph_model = PyFlowRTModel(self._graph, self._executor)
        self._resolver = rt.GraphResolver(self._graph, self._module_registry)

        @self._resolver.resolutions_changed.connect
        def on_resolutions_changed(nodes: set[rt.NodeRef]):
            for node_ref in nodes:
                node_name = node_ref._name
                resolution = self._resolver.get_resolution(node_ref)
                self.graph_model.setNodeData(
                    node_name, 
                    self.graph_model.ResolutionRole, 
                    resolution
                )


        self.modules_model = ModulesOperatorsTreeModel(parent=self)
        self.modules_model.setRegistry(self._module_registry)
        self.modulesselection_model = QItemSelectionModel(self.modules_model)

        self.graphselection_model = GraphSelectionModel(self.graph_model)
        self.graphdetails_model = GraphDetailsModel(self.graph_model, self)
        self.graphselection_model.currentNodeChanged.connect(
            lambda current, previous: self.graphdetails_model.setNode(current)
        )
        # self.graphselection_model.nodesSelectionChanged.connect(self._sync_output_to_selection)
        # self.graphselection_model.currentNodeChanged.connect(self._sync_output_to_selection)

        # self._watcher:rt.Watcher|None = None

    def addNode(self, operator_index:QModelIndex, scene_pos:QPointF|None=None):
        assert operator_index.isValid(), "Operator index must be valid."
        assert operator_index.model() is self.modules_model, "Operator index must belong to the modules model."
        selected_op_ref = operator_index.data(ModulesOperatorsTreeModel.OperatorRole)
        if selected_op_ref:
            self.graph_model.addNode(selected_op_ref, scene_pos or QPointF(0, 0))

    def deleteSelectedNodes(self):
        selected_nodes = self.graphselection_model.selectedNodes()
        self.graph_model.removeNodes(selected_nodes)


    # def setOutputNode(self, node_name: NodeName|None) -> None:
    #     # assert isinstance(node_name, (NodeName, type(None))), f"Expected NodeName or None, got {type(node_name)}"
    #     if self._output_node == node_name:
    #         return
    #     self._output_node = node_name

    #     if self._watcher:
    #         self._watcher.stop()
    #         self._watcher = None

    #     if self._output_node is not None:
    #         output_node_ref = self.graph_model.getNode(self._output_node)
    #         self._watcher = rt.watch(self._G, output_node_ref, self._on_watcher_triggered)

    #     self._on_watcher_triggered()

    # def _execute(self):
    #     try:
    #         node_ref = self.graph_model.getNode(self._output_node)
    #         result = self._G.execute(node_ref)
    #         self.graph_model.setNodeData(self._output_node, self.graph_model.ResultsRole, result)

    #     except GraphExecutionError as err:
    #         traceback.print_exc()
    #         self.graph_model.setNodeData(self._output_node, self.graph_model.ResultsRole, err)

    # @Slot()
    # def _on_watcher_triggered(self):
    #     self._execute()

    def reset_graph(self):
        """Recover the model/view while preserving the current runtime and script."""
        # self.setOutputNode(None)
        self.graph_model.reset()
        # self.setOutputLocked(False)

    # def _sync_output_to_selection(self, *args):
    #     if self._output_locked:
    #         return
    #     selection = self.graphselection_model
    #     selected = selection.selectedNodes()
    #     current = selection.currentNode()
    #     if current in selected:
    #         node = current
    #     elif len(selected) == 1:
    #         node = selected[0]
    #     elif self._output_node is not None and self._output_node in selected:
    #         node = self._output_node
    #     else:
    #         node = None
    #     self.setOutputNode(node)

    def save(self, file_path: str | Path) -> None:
        """Save the runtime and node positions as UTF-8 JSON."""
        data = self._graph.todict()
        for name, record in data.get("graph", {}).get("nodes", {}).items():
            position = self.graph_model.nodePosition(name)
            record["position"] = [position.x(), position.y()]

        text = json.dumps(data, indent=4)
        Path(file_path).write_text(text, encoding="utf-8")

    def open(self, file_path: str | Path) -> None:
        """Load a JSON file, retaining the document and its models."""
        data = json.loads(Path(file_path).read_text(encoding="utf-8"))
        new_registry = rt.ScriptModuleRegistry()
        new_graph_rt = rt.GraphDefinitionRT.fromdict(data)
        new_executor = rt.GraphExecutorRT(new_graph_rt)
        new_resolver = rt.GraphResolver(new_graph_rt, new_registry)
        positions: dict[str, tuple[float, float]] = {}
        for name, record in data.get("graph", {}).get("nodes", {}).items():
            position = record.get("position", [0, 0])
            if (not isinstance(position, (list, tuple)) or len(position) != 2
                    or any(type(v) not in (int, float) or not math.isfinite(v) for v in position)):
                raise ValueError(f"Invalid position for node {name!r}")
            positions[name] = tuple(position)

        try:
            # self.setOutputNode(None)
            # self.setOutputLocked(False)
            self._graph = new_graph_rt
            self.modules_model.setGraph(new_graph_rt)
            self.graph_model.setRT(new_graph_rt, positions)
            if self.modules_model.rowCount():
                self.modulesselection_model.setCurrentIndex(
                    self.modules_model.index(0, 0), QItemSelectionModel.SelectionFlag.ClearAndSelect
                )
        except Exception as e:
            traceback.print_exc()
            raise e
            
    def importModule(self, file_path: str) -> None:
        self.modules_model.importModule(file_path)
