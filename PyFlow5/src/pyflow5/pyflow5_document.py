import json
import math
from pathlib import Path
import traceback

from qdageditor5.models.abstract_dag_model import NodeName
from qtpy.QtCore import QItemSelectionModel, QObject, Signal, Slot

import pygraphrt as rt
from qdageditor5.models.graph_selection_model import GraphSelectionModel

from .modules_operator_tree_model import ModulesOperatorsTreeModel
from .modules_list_proxy_model import ModulesListModel
from .pygraphrt_details_model import GraphDetailsModel
from .pygraphrt_model import PyFlowRTModel


class PyFlowDocument(QObject):
    output_value_got_dirty = Signal()
    output_lock_changed = Signal(bool)

    def __init__(self, parent:QObject|None=None):
        super().__init__(parent=parent)
        self._G = rt.GraphRT()
        self._modules_operators_tree_model = ModulesOperatorsTreeModel(parent=self)
        self._modules_operators_tree_model.setGraph(self._G)

        self._modules_list_model = ModulesListModel(self._modules_operators_tree_model, self)
        self._module_selection_model = QItemSelectionModel(self._modules_list_model)

        self._graph_model = PyFlowRTModel(self._G)

        self._graph_selection_model = GraphSelectionModel(self._graph_model)
        self._graph_details_model = GraphDetailsModel(self._graph_model, self)
        self._graph_selection_model.currentNodeChanged.connect(
            lambda current, previous: self._graph_details_model.setNode(current)
        )
        self._graph_selection_model.nodesSelectionChanged.connect(self._sync_output_to_selection)
        self._graph_selection_model.currentNodeChanged.connect(self._sync_output_to_selection)

        self._watcher:rt.Watcher|None = None
        self._output_node: NodeName|None = None
        self._output_locked = False
        self._loading = False

        self._graph_model.nodesRemoved.connect(self._on_output_nodes_removed)
        # self._G.nodes_removed.connect(self._on_output_nodes_removed)

    def graphmodel(self)->PyFlowRTModel:
        return self._graph_model

    def graphselectionmodel(self)->GraphSelectionModel:
        return self._graph_selection_model

    def graphdetailsmodel(self) -> GraphDetailsModel:
        return self._graph_details_model

    def operatormodel(self)->ModulesOperatorsTreeModel:
        return self._modules_operators_tree_model

    def modulesmodel(self) -> ModulesListModel:
        return self._modules_list_model

    def moduleselectionmodel(self) -> QItemSelectionModel:
        return self._module_selection_model

    def deleteSelectedNodes(self):
        selected_nodes = self.graphselectionmodel().selectedNodes()
        self._graph_model.removeNodes(selected_nodes)

    def is_output_locked(self) -> bool:
        return self._output_locked

    def set_output_locked(self, locked: bool) -> None:
        if self._output_locked == locked:
            return
        self._output_locked = locked
        self.output_lock_changed.emit(locked)
        if not locked:
            self._sync_output_to_selection()

    def _on_output_nodes_removed(self, nodes: list[NodeName]):
        if self._output_node in nodes:
            self.set_output_node(None)
            self.set_output_locked(False)

    def get_output_node(self) -> NodeName|None:
        return self._output_node

    def set_output_node(self, node_name: NodeName|None) -> None:
        # assert isinstance(node_name, (NodeName, type(None))), f"Expected NodeName or None, got {type(node_name)}"
        if self._output_node == node_name:
            return
        self._output_node = node_name

        if self._watcher:
            self._watcher.stop()
            self._watcher = None

        if self._output_node is not None:
            output_node_ref = self._graph_model.getNode(self._output_node)
            self._watcher = rt.watch(self._G, output_node_ref, self._on_watcher_triggered)

        self._on_watcher_triggered()

    def execute(self):
        if self._output_node is None:
            return None

        try:
            node_ref = self._graph_model.getNode(self._output_node)
            result = self._G.execute(node_ref)
            return result

        except Exception as e:
            traceback.print_exc()
            return e

    @Slot()
    def _on_watcher_triggered(self):
        if self._output_node is None:
            self.output_value_got_dirty.emit()
            return
        self.output_value_got_dirty.emit()

    @Slot()
    def reset_graph(self):
        """Recover the model/view while preserving the current runtime and script."""
        self.set_output_node(None)
        self._graph_model.reset()
        self.set_output_locked(False)

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
        self.set_output_node(node)

    def save(self, file_path: str | Path) -> None:
        """Save the runtime and node positions as UTF-8 JSON."""
        data = self._G.todict()
        for name, record in data.get("graph", {}).get("nodes", {}).items():
            position = self._graph_model.nodePosition(name)
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
            self.set_output_node(None)
            self.set_output_locked(False)
            self._G = new_graph_rt
            self._modules_operators_tree_model.setGraph(new_graph_rt)
            self._graph_model.setRT(new_graph_rt, positions)
            if self._modules_list_model.rowCount():
                self._module_selection_model.setCurrentIndex(
                    self._modules_list_model.index(0, 0), QItemSelectionModel.SelectionFlag.ClearAndSelect
                )
        except Exception as e:
            raise e

        self.output_value_got_dirty.emit()

    def importModule(self, file_path: str) -> None:
        self._modules_operators_tree_model.importModule(file_path)
        

