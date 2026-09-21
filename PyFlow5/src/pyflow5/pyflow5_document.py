import copy
from textwrap import dedent
from typing import Iterable, Mapping
import traceback
import warnings

from QtScriptEditorAdvanced.components.python_keywords_completer import PythonKeywordsCompleter
from myqtx.selection_dialog import SelectionDialog
from pyflow5.module_operator_tree_model import ModuleOperatorTreeModel
from pygraphrt.abstract_module_rt import OperatorRef
from pygraphrt.graph_rt import NodeRef
from qtpy.QtCore import QAbstractTableModel, QItemSelectionModel, QObject, QPoint, QPointF, Qt, Signal, Slot
from qtpy.QtWidgets import QAction, QToolBar

from pygraphrt.script_module_rt import ScriptModuleRT

from qdageditor5.models.graph_selection_model import GraphSelectionModel

from qdageditor5.models.abstract_dag_model import (
    InletName, 
    NodeName, 
    OutletName, 
    DirectionalLinkId
)

import pygraphrt as rt
from pyflow5.pygraphrt_model import PyFlowRTModel
from pyflow5.node_inspector_model import NodeInspectorModel


from qtpy.QtCore import QAbstractTableModel, QModelIndex
class ImportsListModel(QAbstractTableModel):
    NameRole = int(Qt.ItemDataRole.UserRole) + 1
    CodeRole = NameRole + 1

    def __init__(self, imports:list[ScriptModuleRT], parent:QObject=None):
        super().__init__(parent)
        self._imports: list[ScriptModuleRT] = imports

    def columnCount(self, parent=QModelIndex()) -> int:
        return 1

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._imports)

    def data(self, index:QModelIndex, role:int=Qt.DisplayRole):
        if not index.isValid():
            return None

        match role:
            case Qt.DisplayRole | Qt.EditRole | ImportsListModel.NameRole:
                return self._imports[index.row()].get_name()
            case ImportsListModel.CodeRole:
                return self._imports[index.row()].get_script()
        return None

    def setData(self, index:QModelIndex, value, role:int=Qt.EditRole)->bool:
        if not index.isValid():
            return False

        match role:
            case Qt.EditRole | ImportsListModel.NameRole:
                self._imports[index.row()].set_name(value)
                self.dataChanged.emit(index, index, [role])
                return True
            
            case ImportsListModel.CodeRole:
                self._imports[index.row()].set_script(value)
                self.dataChanged.emit(index, index, [role])
                return True
            
        return False

    def addImport(self, script_module:ScriptModuleRT):
        self.beginInsertRows(QModelIndex(), len(self._imports), len(self._imports))
        self._imports.append(script_module)
        self.endInsertRows()

    def removeImport(self, row:int):
        if 0 <= row < len(self._imports):
            self.beginRemoveRows(QModelIndex(), row, row)
            self._imports.pop(row)
            self.endRemoveRows()


class PyFlowDocument(QObject):
    output_value_got_dirty = Signal()
    output_lock_changed = Signal(bool)
    def __init__(self, parent:QObject=None):
        super().__init__(parent=parent)
        self._mathy_module = ScriptModuleRT("mathy", dedent("""\
        def one():
            return 1

        def two():
            return 2

        def mult(a, b):
            return a * b
        """))

        self._imagi_module = ScriptModuleRT("imagi", dedent("""\
            import numpy as np
            import pathlib
            from dataclasses import dataclass

            @dataclass(frozen=True)
            class ColorData:
                r: float = 0.0
                g: float = 0.0
                b: float = 0.0
                a: float = 1.0

            @dataclass
            class ImageRGBA:
                data: np.ndarray

            def constant(width: int=512, height: int=512, color: ColorData=ColorData(0.5, 0.5, 0.5))->ImageRGBA:
                return ImageRGBA(np.full((height, width, 4), [color.r, color.g, color.b, color.a], dtype=np.float32))

            def read(path: pathlib.Path)->ImageRGBA:
                return ImageRGBA(np.zeros((1, 1, 4), dtype=np.float32))

            def cornerpin(img: ImageRGBA)->ImageRGBA:
                return img
    
            def exposure(img: ImageRGBA, factor: float)->ImageRGBA:
                return img

            def temperature(img: ImageRGBA, value: float)->ImageRGBA:
                return img

            def image_to_data(img: ImageRGBA) -> np.ndarray:
                return img.data

            __all__ = [
            "constant",
            "read",
            "cornerpin",
            "exposure",
            "temperature",
            "image_to_data"
            ]
            """))

        self._imports: Iterable[ScriptModuleRT] = [
            self._mathy_module,
            self._imagi_module
        ]

        self._imports_model = ImportsListModel(self._imports, self)
        self._import_selection_model = QItemSelectionModel(self._imports_model)

        self._G = rt.GraphRT()
        self._operator_model = ModuleOperatorTreeModel([
            self._G.module(), 
            *self._imports], 
            self
        )
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
        self._G.nodes_removed.connect(self._on_output_nodes_removed)

    # def scriptmodule(self)->ScriptModuleRT:
    #     return self._mathy_module

    def graphmodel(self)->PyFlowRTModel:
        return self._graph_model

    def graphselectionmodel(self)->GraphSelectionModel:
        return self._graph_selection_model

    def inspectormodel(self) -> NodeInspectorModel:
        return self._inspector_model

    def operatormodel(self)->ModuleOperatorTreeModel:
        return self._operator_model

    def importsmodel(self) -> ImportsListModel:
        return self._imports_model

    def importselectionmodel(self) -> QItemSelectionModel:
        return self._import_selection_model

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
        if self._output_locked:
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
