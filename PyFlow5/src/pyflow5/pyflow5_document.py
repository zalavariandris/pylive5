import json
import math
from pathlib import Path
import traceback

from qtpy.QtCore import QItemSelectionModel, QObject, Signal, Slot

import pygraphrt as rt
from pygraphrt.graph_rt import NodeRef
from qdageditor5.models.graph_selection_model import GraphSelectionModel

from .module_operator_tree_model import ModuleOperatorTreeModel
from .modules_list_model import ModulesListModel
from .node_inspector_model import NodeInspectorModel
from .pygraphrt_model import PyFlowRTModel


class PyFlowDocument(QObject):
    output_value_got_dirty = Signal()
    output_lock_changed = Signal(bool)
    def __init__(self, parent:QObject=None):
        super().__init__(parent=parent)
        self._G = rt.GraphRT()
        examples = Path(__file__).parent / "examples"
        self._mathy_module = self._G.add_import(str(examples / "mathy.py"))
        self._imagi_module = self._G.add_import(str(examples / "imagi.py"))
        self._operator_model = ModuleOperatorTreeModel(parent=self)
        self._operator_model.setGraph(self._G)
        self._modules_model = ModulesListModel(self._operator_model, self)
        self._module_selection_model = QItemSelectionModel(self._modules_model)
        self._graph_model = PyFlowRTModel(self._G)

        self._graph_selection_model = GraphSelectionModel(self._graph_model)
        self._inspector_model = NodeInspectorModel(self._graph_model, self)
        self._graph_selection_model.currentNodeChanged.connect(
            lambda current, previous: self._inspector_model.setNode(current)
        )
        self._graph_selection_model.nodesSelectionChanged.connect(self._sync_output_to_selection)
        self._graph_selection_model.currentNodeChanged.connect(self._sync_output_to_selection)

        self._watcher:rt.Watcher|None = None
        self._output_node: NodeRef|None = None
        self._output_locked = False
        self._loading = False
        self._G.nodes_removed.connect(self._on_output_nodes_removed)

    def graphmodel(self)->PyFlowRTModel:
        return self._graph_model

    def graphselectionmodel(self)->GraphSelectionModel:
        return self._graph_selection_model

    def inspectormodel(self) -> NodeInspectorModel:
        return self._inspector_model

    def operatormodel(self)->ModuleOperatorTreeModel:
        return self._operator_model

    def modulesmodel(self) -> ModulesListModel:
        return self._modules_model

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

    def _on_output_nodes_removed(self, nodes):
        if self._output_node in nodes:
            self.set_output_node(None)
            self.set_output_locked(False)

    def get_output_node(self) -> NodeRef|None:
        return self._output_node

    def set_output_node(self, node_ref: NodeRef|None) -> None:
        assert isinstance(node_ref, (NodeRef, type(None))), f"Expected NodeRef or None, got {type(node_ref)}"
        if self._output_node == node_ref:
            return
        self._output_node = node_ref

        if self._watcher:
            self._watcher.stop()
            self._watcher = None

        if self._output_node is not None:
            self._watcher = rt.watch(self._G, self._output_node, self._on_watcher_triggered)

        self._on_watcher_triggered()

    def execute(self):
        if self._output_node is None:
            return None

        try:
            result = self._G.execute(self._output_node)
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
        if self._loading or self._output_locked:
            return
        selection = self.graphselectionmodel()
        selected = selection.selectedNodes()
        current = selection.currentNode()
        if current in selected:
            node = current
        elif len(selected) == 1:
            node = selected[0]
        elif self._output_node is not None and self._output_node.get_name() in selected:
            node = self._output_node.get_name()
        else:
            node = None
        self.set_output_node(self._graph_model.getNode(node) if node is not None else None)

    def fromdict(self, data: dict) -> None:
        """Load a replacement runtime, retaining the document and its models."""
        graph = rt.GraphRT.fromdict(data)
        positions = {}
        for name, record in data["graph"]["nodes"].items():
            position = record.get("position", [0, 0])
            if (not isinstance(position, (list, tuple)) or len(position) != 2
                    or any(type(v) not in (int, float) or not math.isfinite(v) for v in position)):
                raise ValueError(f"Invalid position for node {name!r}")
            positions[name] = tuple(position)
        modules = graph.imports()
        self._loading = True
        try:
            self.set_output_node(None)
            self.set_output_locked(False)
            self._G.nodes_removed.disconnect(self._on_output_nodes_removed)
            self._G = graph
            graph.nodes_removed.connect(self._on_output_nodes_removed)
            self._mathy_module = next((m for m in modules if m.get_name() == "mathy"), None)
            self._imagi_module = next((m for m in modules if m.get_name() == "imagi"), None)
            self._operator_model.setGraph(graph)
            self._graph_model.setRT(graph, positions)
            if self._modules_model.rowCount():
                self._module_selection_model.setCurrentIndex(
                    self._modules_model.index(0, 0), QItemSelectionModel.SelectionFlag.ClearAndSelect
                )
        finally:
            self._loading = False
        self.output_value_got_dirty.emit()

    def todict(self) -> dict:
        data = self._G.todict()
        for name, record in data["graph"]["nodes"].items():
            position = self._graph_model.nodePosition(name)
            record["position"] = [position.x(), position.y()]
        return data

    def serialize(self)->str:
        return json.dumps(self.todict(), indent=4)

    def deserialize(self, text: str) -> None:
        data = json.loads(text)
        self.fromdict(data)

    def saveGraph(self, file_path: str) -> None:
        """Save the current graph to the specified file path."""

        text = self.serialize()
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(text)

    def openGraph(self, file_path: str) -> None:
        """Load a graph from the specified file path."""
        with open(file_path, 'r', encoding='utf-8') as f:
            data = f.read()

        self.deserialize(data)

    def importModule(self, file_path: str) -> None:
        self._G.add_import(file_path)
