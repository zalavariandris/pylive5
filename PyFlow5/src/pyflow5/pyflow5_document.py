import json
import math
from pathlib import Path
import traceback

from pygraphrt.script_module import ScriptModuleRT
from qdageditor5.models.abstract_dag_model import NodeName
from qtpy.QtCore import QItemSelectionModel, QModelIndex, QObject, QPointF, Signal, Slot

import pygraphrt as rt
from qdageditor5.models.graph_selection_model import GraphSelectionModel

from .modules_operator_tree_model import ModulesOperatorsTreeModel
from .pygraphrt_details_model import GraphDetailsModel
from .pygraphrt_model import PyFlowRTModel



class PyFlowDocument(QObject):
    output_value_changed = Signal()
    output_lock_changed = Signal(bool)

    def __init__(self, parent:QObject|None=None):
        super().__init__(parent=parent)
        self._G = rt.GraphRT()

        self.graphmodel = PyFlowRTModel(self._G)

        self.modulesmodel = ModulesOperatorsTreeModel(parent=self)
        self.modulesmodel.setGraph(self._G)

        self.operatorselectionmodel = QItemSelectionModel(self.modulesmodel)
        self.graphselectionmodel = GraphSelectionModel(self.graphmodel)
        self.graphdetailsmodel = GraphDetailsModel(self.graphmodel, self)
        self.graphselectionmodel.currentNodeChanged.connect(
            lambda current, previous: self.graphdetailsmodel.setNode(current)
        )
        self.graphselectionmodel.nodesSelectionChanged.connect(self._sync_output_to_selection)
        self.graphselectionmodel.currentNodeChanged.connect(self._sync_output_to_selection)

        self._watcher:rt.Watcher|None = None
        self._output_node: NodeName|None = None
        self._output_value:object|None = None
        self._output_locked = False

        self.graphmodel.nodesRemoved.connect(self._on_nodes_removed)

    def addNode(self, operator_index:QModelIndex, scene_pos:QPointF|None=None):
        assert operator_index.isValid(), "Operator index must be valid."
        assert operator_index.model() is self.modulesmodel, "Operator index must belong to the modules model."
        selected_op_ref = operator_index.data(ModulesOperatorsTreeModel.OperatorRole)
        if selected_op_ref:
            self.graphmodel.addNode(selected_op_ref, scene_pos or QPointF(0, 0))

    def deleteSelectedNodes(self):
        selected_nodes = self.graphselectionmodel().selectedNodes()
        self.graphmodel.removeNodes(selected_nodes)

    def isOutputLocked(self) -> bool:
        return self._output_locked

    def setOutputLocked(self, locked: bool) -> None:
        if self._output_locked == locked:
            return
        self._output_locked = locked
        self.output_lock_changed.emit(locked)
        if not locked:
            self._sync_output_to_selection()

    @Slot()
    def _on_nodes_removed(self, nodes: list[NodeName]):
        if self._output_node in nodes:
            self.setOutputNode(None)
            self.setOutputLocked(False)

    def getOutputNode(self) -> NodeName|None:
        return self._output_node

    def setOutputNode(self, node_name: NodeName|None) -> None:
        # assert isinstance(node_name, (NodeName, type(None))), f"Expected NodeName or None, got {type(node_name)}"
        if self._output_node == node_name:
            return
        self._output_node = node_name

        if self._watcher:
            self._watcher.stop()
            self._watcher = None

        if self._output_node is not None:
            output_node_ref = self.graphmodel.getNode(self._output_node)
            self._watcher = rt.watch(self._G, output_node_ref, self._on_watcher_triggered)

        self._on_watcher_triggered()

    def _execute(self):
        if self._output_node is None:
            self._output_value = None
            self.output_value_changed.emit()
            return

        try:
            node_ref = self.graphmodel.getNode(self._output_node)
            result = self._G.execute(node_ref)
            self._output_value = result
            self.output_value_changed.emit()

        except Exception as e:
            traceback.print_exc()
            self._output_value = None
            self.output_value_changed.emit()

    @Slot()
    def _on_watcher_triggered(self):
        self._execute()

    def output_value(self):
        return self._output_value

    def reset_graph(self):
        """Recover the model/view while preserving the current runtime and script."""
        self.setOutputNode(None)
        self.graphmodel.reset()
        self.setOutputLocked(False)

    def _sync_output_to_selection(self, *args):
        if self._output_locked:
            return
        selection = self.graphselectionmodel()
        selected = selection.selectedNodes()
        current = selection.currentNode()
        if current in selected:
            node = current
        elif len(selected) == 1:
            node = selected[0]
        elif self._output_node is not None and self._output_node in selected:
            node = self._output_node
        else:
            node = None
        self.setOutputNode(node)

    def save(self, file_path: str | Path) -> None:
        """Save the runtime and node positions as UTF-8 JSON."""
        data = self._G.todict()
        for name, record in data.get("graph", {}).get("nodes", {}).items():
            position = self.graphmodel.nodePosition(name)
            record["position"] = [position.x(), position.y()]

        text = json.dumps(data, indent=4)
        Path(file_path).write_text(text, encoding="utf-8")

    def open(self, file_path: str | Path) -> None:
        """Load a JSON file, retaining the document and its models."""
        data = json.loads(Path(file_path).read_text(encoding="utf-8"))
        new_graph_rt = rt.GraphRT.fromdict(data)
        positions: dict[str, tuple[float, float]] = {}
        for name, record in data.get("graph", {}).get("nodes", {}).items():
            position = record.get("position", [0, 0])
            if (not isinstance(position, (list, tuple)) or len(position) != 2
                    or any(type(v) not in (int, float) or not math.isfinite(v) for v in position)):
                raise ValueError(f"Invalid position for node {name!r}")
            positions[name] = tuple(position)

        try:
            self.setOutputNode(None)
            self.setOutputLocked(False)
            self._G = new_graph_rt
            self.modulesmodel.setGraph(new_graph_rt)
            self.graphmodel.setRT(new_graph_rt, positions)
            if self.modules_proxy_model.rowCount():
                self.operatorselectionmodel.setCurrentIndex(
                    self.modules_proxy_model.index(0, 0), QItemSelectionModel.SelectionFlag.ClearAndSelect
                )
        except Exception as e:
            raise e

        self.output_value_changed.emit()

    def importModule(self, file_path: str) -> None:
        self.modulesmodel.importModule(file_path)
