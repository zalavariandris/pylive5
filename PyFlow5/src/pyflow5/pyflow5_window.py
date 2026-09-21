import copy
from textwrap import dedent
from typing import Iterable, Mapping
import traceback
import warnings

from QtScriptEditorAdvanced.components.python_keywords_completer import PythonKeywordsCompleter
from pyflow5.operator_selection_dialog import OperatorSelectionDialog
from pyflow5.module_operator_tree_model import ModuleOperatorTreeModel
from pygraphrt.abstract_module_rt import OperatorRef
from pygraphrt.graph_rt import NodeRef
from qtpy.QtCore import QObject, QPoint, QPointF, Qt, Signal, Slot
from qtpy.QtWidgets import QAction, QToolBar

from pygraphrt.script_module_rt import ScriptModuleRT
from qtpy.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout, 
    QSplitter, 
    QSplitter,
    QVBoxLayout, 
    QWidget, 
    QMainWindow, 
)

from qdageditor5.models.graph_selection_model import GraphSelectionModel
from qdageditor5.views.directional_graph_view_5 import DirectionalGraphView5
from qdageditor5.models.abstract_dag_model import (
    InletName, 
    NodeName, 
    OutletName, 
    DirectionalLinkId
)

from QScriptEdit2.script_edit import ScriptEdit2
import myqtx

import pygraphrt as rt
from pyflow5.pygraphrt_model import PyFlowRTModel

from textwrap import dedent

from QtScriptEditorAdvanced.script_edit_advanced import ScriptEditAdvanced

class PyFlow5Window(QMainWindow):
    output_node_changed = Signal()
    def setupActions(self)->None:
        self._restart_kernel_action:QAction = QAction("Reset Graph View", self)
        self._restart_kernel_action.triggered.connect(self.reset_graph)
        open_operator_dialog_action = QAction("Open Operator Dialog", self)
        self.addAction(open_operator_dialog_action)
        open_operator_dialog_action.setShortcut("Ctrl+P")
        open_operator_dialog_action.triggered.connect(self.openOperatorDialog)

        delete_selected_nodes_action = QAction("Delete Selected Nodes", self)
        self.addAction(delete_selected_nodes_action)
        delete_selected_nodes_action.setShortcut("Del")
        delete_selected_nodes_action.triggered.connect(self.deleteSelectedNodes)

    def __init__(self, parent=None)->None:
        super().__init__(parent)
        self.setWindowTitle("PyFlow5")
        # setup Model
        self._G = rt.GraphRT()

        self._script_module = ScriptModuleRT("mathy", dedent("""\
        def one():
            return 1

        def two():
            return 2

        def mult(a, b):
            return a * b
        """))

        self._script_module.state_changed.connect(self._on_script_module_state_changed)

        self._imports: Iterable[ScriptModuleRT] = [
            self._script_module
        ]

        self._operator_model = ModuleOperatorTreeModel([self._G.module(), *self._imports], self)
        self._model = PyFlowRTModel(self._G)
        self._selection = GraphSelectionModel(self._model)
        self._selection.nodesSelectionChanged.connect(
            lambda selected, deselected: 
            self._on_nodes_selection_changed(selected, deselected)
        )

        self._watcher:rt.Watcher|None = None
        self._output_node: NodeRef|None = None

        # Setup UI
        splitter = QSplitter(self)

        self.setupActions()

        toolbar:QToolBar = self.addToolBar("Main Toolbar")
        toolbar.addAction(self._restart_kernel_action)
        
        # self._code_editor = ScriptEdit2(self)
        self._code_editor = ScriptEditAdvanced(
            completer=PythonKeywordsCompleter,
            parent=self
        )
        self._code_editor.setPlainText(self._script_module.get_script())
        self._code_editor.textChanged.connect(lambda: self._script_module.set_script(self._code_editor.toPlainText()))
        self._script_module.script_changed.connect(self._on_script_changed)
        
        # - Setup graphview -
        self._graph_view = DirectionalGraphView5(self)
        self._graph_view.setModel(self._model)
        self._graph_view.setSelectionModel(self._selection)
        self._graph_view.requestLink.connect(lambda src, outlet, dst, inlet: self._on_request_link(src, outlet, dst, inlet))
        self._graph_view.requestNode.connect(lambda pos, source: self._on_request_node(pos, source))
        self._graph_view.layout_nodes()
        self._graph_view.fitNodes()

        # - Setup display widget -
        self._display_widget = myqtx.DisplayWidget(self)

        # - Add widgets to splitter -
        splitter.addWidget(self._code_editor)
        splitter.addWidget(self._graph_view)
        splitter.addWidget(self._display_widget)
        splitter.setSizes([400, 400, 400])
        self.resize(3*400, 600)


        self.setCentralWidget(splitter)

        self._graph_view.setFocus()

        # - Initial results update -
        self._on_watcher_triggered()

    def _on_script_module_state_changed(self):
        # set code editor style to red border if the script module is in an error state
        match self._code_editor:
            case ScriptEditAdvanced():
                state = self._script_module.get_state()
                match state:
                    case SyntaxError() as e:
                        self._code_editor._linter.clear()
                        self._code_editor._linter.lintException(e, 'underline')
                    case Exception() as e:
                        self._code_editor._linter.clear()
                        self._code_editor._linter.lintException(e, 'label')
                    case "VALID":
                        self._code_editor._linter.clear()
                    case _:
                        print(f"Unknown script module state: {state}")
                        self._code_editor._linter.clear()

            case ScriptEdit2():
                match self._script_module.get_state():
                    case SyntaxError() as e:
                        self._code_editor.showError(e)
                    case Exception() as e:
                        self._code_editor.showError(e)
                    case "VALID":
                        self._code_editor.clearError()
                    case _:
                        pass


    def get_output_node(self) -> NodeRef|None:
        return self._output_node

    def set_output_node(self, node_ref: NodeRef|None) -> None:
        assert isinstance(node_ref, (NodeRef, type(None))), f"Expected NodeRef or None, got {type(node_ref)}"
        self._output_node = node_ref

        if self._watcher:
            self._watcher.stop()
            self._watcher = None

        if self._output_node is not None:
            self._watcher = rt.watch(self._G, self._output_node, self._on_watcher_triggered)

        self._on_watcher_triggered()

    @Slot()
    def reset_graph(self):
        """Recover the model/view while preserving the current runtime and script."""
        self.set_output_node(None)
        self._model.reset()

    @Slot()
    def _on_script_changed(self):
        # Same Value Guard
        new_text = self._script_module.get_script()
        if self._code_editor.toPlainText() == new_text:
            return  # nothing changed → do nothing

        with myqtx.blockingSignals(self._code_editor):
            # preserve cursor & scroll
            cursor = self._code_editor.textCursor()
            pos = cursor.position()
            scroll = self._code_editor.verticalScrollBar().value()

            self._code_editor.setPlainText(new_text)
            
            # restore cursor
            cursor.setPosition(min(pos, len(new_text)))
            self._code_editor.setTextCursor(cursor)
            self._code_editor.verticalScrollBar().setValue(scroll)

    @Slot()
    def _on_watcher_triggered(self):
        if self._output_node is None:
            self._display_widget.display("")
            return
        
        try:
            result = self._G.execute(self._output_node)
            self._display_widget.display(result)

        except Exception as e:
            self._display_widget.display(e)
            traceback.print_exc()

    def deleteSelectedNodes(self):
        selected_nodes = self._selection.selectedNodes()
        self._model.removeNodes(selected_nodes)

    @Slot()
    def _on_nodes_selection_changed(self, selected:set[NodeName], deselected:set[NodeName]):
        print("Selected nodes changed:", selected, "Deselected nodes:", deselected)

        first_selected_node = self._selection.selectedNodes()[0] if self._selection.selectedNodes() else None
        last_selected_node = self._selection.selectedNodes()[-1] if self._selection.selectedNodes() else None
        if last_selected_node is not None:
            node_ref = self._model.getNode(last_selected_node)
            self.set_output_node(node_ref)
            print(f"Output node changed to: {node_ref}")
        else:
            self.set_output_node(None)
            print("Output node cleared")

    def openOperatorDialog(self, *, scene_pos:QPointF|None=None, source:NodeName|None=None):
        dialog = OperatorSelectionDialog(self._operator_model, self)
        try:
            if dialog.exec() == QDialog.DialogCode.Accepted:
                if selected_op := dialog.selected_operator():
                    self._model.addNode(selected_op, scene_pos or QPointF(0, 0))
        finally:
            dialog.deleteLater()

    @Slot()
    def _on_request_node(self, scene_pos:QPointF, source:NodeName):
        print(f"Request node signal received {scene_pos} {source}")
        # show a dialog with a multiselection of operator in GraphRT
        self.openOperatorDialog(scene_pos=scene_pos, source=source)

    @Slot()
    def _on_request_link(self, source:NodeName, outlet:OutletName, target:NodeName, inlet:InletName):
        self._model.addLink(source, outlet, target, inlet)

    @Slot()
    def _on_graph_output_changed(self):
        print("Graph output changed signal received")
        output_node = self.get_output_node()
        print(f"New output node: {output_node}")
