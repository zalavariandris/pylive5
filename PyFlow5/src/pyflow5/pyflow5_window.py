import copy
from textwrap import dedent
from typing import Iterable, Mapping
import traceback
import warnings
from pyflow5.operator_selection_dialog import OperatorSelectionDialog
from qtpy.QtCore import QObject, QPoint, QPointF, Qt, Signal
from qtpy.QtWidgets import QAction

from pygraphrt.operator_rt import OperatorRT
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
from myqtx.displaywidget import DisplayWidget

import pygraphrt as rt
from pyflow5.pygraphrt_model import PyFlowRtModel


class PyFlow5Window(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("PyFlow5")

        toolbar = self.addToolBar("Main Toolbar")
        action  =toolbar.addAction("Restart Kernel")

        def reset_graph():
            G = rt.utils.graph_from_script(self._code_editor.toPlainText(), 'G')
            self._model.setRT(G)
        action.triggered.connect(reset_graph)

        from textwrap import dedent

        self._G = rt.GraphRT()

        self._script_rt = ScriptModuleRT(dedent("""\
        def one():
            return 1

        def two():
            return 2

        def mult(a, b):
            return a * b
        """)) 

        # add the operators from the script
        for name, func in self._script_rt._get_all_functions_from_script().items():
            self._G.module().op()(func)

        def _on_results_changed():
            try:
                result = self._G.execute()
                self._display_widget.display(result)
            except Exception as e:
                self._display_widget.display(e)
                traceback.print_exc()

        self._watcher:rt.Watcher|None = None
        def _on_output_node_changed(node:rt.NodeRT):
            if self._watcher:
                self._watcher.stop()
            if node is not None:
                self._watcher = rt.watch(self._G, node, _on_results_changed)
            _on_results_changed()

        self._G.output_node_changed.connect(lambda: _on_output_node_changed(self._G.output))
        
        self._model = PyFlowRtModel(self._G)
        self._selection = GraphSelectionModel(self._model)
        self._selection.nodesSelectionChanged.connect(lambda selected, deselected: self._on_nodes_selection_changed(selected, deselected))

        layout = QHBoxLayout(self)
        splitter = QSplitter(self)
        layout.addWidget(splitter)
        
        self._code_editor = ScriptEdit2(self)
        self._code_editor.setPlainText(self._script_rt.get_script())
        self._code_editor.textChanged.connect(lambda: self._script_rt.set_script(self._code_editor.toPlainText()))
        def _on_script_changed():
            new_text = self._script_rt.get_script()
            if self._code_editor.toPlainText() == new_text:
                return  # nothing changed → do nothing

            # preserve cursor & scroll
            cursor = self._code_editor.textCursor()
            pos = cursor.position()
            scroll = self._code_editor.verticalScrollBar().value()

            self._code_editor.blockSignals(True)          # prevent re-entrancy
            self._code_editor.setPlainText(new_text)
            self._code_editor.blockSignals(False)

            # restore cursor
            cursor.setPosition(min(pos, len(new_text)))
            self._code_editor.setTextCursor(cursor)
            self._code_editor.verticalScrollBar().setValue(scroll)

        self._script_rt.script_changed.connect(_on_script_changed)
        
        def on_functions_removed_from_script(removed: list[str]):
            print(f"Functions removed from script: {removed}")
            for name in removed:
                if op := self._G.module().get_operator(name):
                    self._G.module().remove_operator(op)

        def on_functions_added_to_script(added: list[str]):
            functions_map = self._script_rt._get_all_functions_from_script()
            print(f"Functions added to script:")
            for name in added:
                func = functions_map[name]
                print(f"    {name}, func: {func}")

            for name in added:
                assert name not in self._G.module().operators().keys(), f"Operator {name} already exists"
                func = functions_map[name]
                self._G.module().op()(func)

        def on_functions_changed_in_script(changed: list[str]):
            print(f"Functions changed in script")
            for name in changed:
                func = self._script_rt._get_all_functions_from_script()[name]
                print(f"    {name}, func: {func}")
            for name in changed:
                if op := self._G.module().get_operator(name):
                    self._G.module().update_operator(op, func)

        self._script_rt.functions_added.connect(on_functions_added_to_script)
        self._script_rt.functions_removed.connect(on_functions_removed_from_script)
        self._script_rt.functions_changed.connect(on_functions_changed_in_script)

        self._graph_view = DirectionalGraphView5(self)
        self._graph_view.setModel(self._model)
        self._graph_view.setSelectionModel(self._selection)
        self._graph_view.requestLink.connect(self._on_request_link)
        self._graph_view.requestNode.connect(lambda pos, source: self._on_request_node(pos, source))
        self._graph_view.layout_nodes()
        self._graph_view.fitNodes()
        self._display_widget = DisplayWidget(self)

        splitter.addWidget(self._code_editor)
        splitter.addWidget(self._graph_view)
        splitter.addWidget(self._display_widget)
        splitter.setSizes([400, 400, 400])
        self.resize(3*400, 600)

        central_widget = QWidget()
        central_widget.setLayout(layout)
        self.setCentralWidget(central_widget)

        self._graph_view.setFocus()

        _on_results_changed()

        # setup actions
        open_operator_dialog_action = QAction("Open Operator Dialog", self)
        self.addAction(open_operator_dialog_action)
        open_operator_dialog_action.setShortcut("Ctrl+P")
        open_operator_dialog_action.triggered.connect(self.openOperatorDialog)

        delete_selected_nodes_action = QAction("Delete Selected Nodes", self)
        self.addAction(delete_selected_nodes_action)
        delete_selected_nodes_action.setShortcut("Del")
        delete_selected_nodes_action.triggered.connect(self.deleteSelectedNodes)

    def deleteSelectedNodes(self):
        selected_nodes = self._selection.selectedNodes()
        self._model.removeNodes(selected_nodes)
    
    def _on_nodes_selection_changed(self, selected:set[NodeName], deselected:set[NodeName]):
        print("Selected nodes changed:", selected, "Deselected nodes:", deselected)

        first_selected_node = self._selection.selectedNodes()[0] if self._selection.selectedNodes() else None
        last_selected_node = self._selection.selectedNodes()[-1] if self._selection.selectedNodes() else None
        if last_selected_node is not None:
            node_rt = self._G.get_node(last_selected_node)
            self._G.output = node_rt
            print(f"Output node changed to: {last_selected_node}")
        else:
            self._G.output = None
            print("Output node cleared")

    def openOperatorDialog(self, *, scene_pos:QPointF|None=None, source:NodeName|None=None):
        operators_map:dict[str, OperatorRT] = self._G.module().operators()
        dialog = OperatorSelectionDialog(operators_map.keys(), self)
        if dialog.exec_() == QDialog.Accepted:
            if selected_op_name := dialog.selected_operator():
                selected_op = operators_map[selected_op_name]
                new_node = self._G.node()(selected_op)
                print(f"New node created: {new_node} with operator: {selected_op}")
                self._model.setNodePosition(new_node.get_name(), scene_pos or QPointF(0, 0))

    def _on_request_node(self, scene_pos:QPointF, source:NodeName):
        print(f"Request node signal received {scene_pos} {source}")
        # show a dialog with a multiselection of operator in GraphRT
        self.openOperatorDialog(scene_pos=scene_pos, source=source)

    def _on_request_link(self, source:NodeName, outlet:OutletName, target:NodeName, inlet:InletName):
        target_rt = self._model.rt.get_node(target)
        source_rt = self._model.rt.get_node(source)
        assert target_rt is not None, f"Target node '{target}' not found"
        assert source_rt is not None, f"Source node '{source}' not found"
        args, kwargs = target_rt.get_inputs()
        op_rt = target_rt.get_operator()

        # if there are already positional arguments for this inlet, replace that otherwise add it to keyword arguments
        inlets = [name for name in op_rt.get_parameters().keys()]
        if inlet not in inlets:
            print(f"Inlet '{inlet}' not found in operator parameters")
            return
        inlet_idx = inlets.index(inlet)
        if inlet_idx < len(args):
            
            args[inlet_idx] = source_rt
        else:
            kwargs[inlet] = source_rt

        target_rt.set_inputs(*args, **kwargs)
        print(f"Updated inputs for target node '{target}': args={args}, kwargs={kwargs}")

    def _on_graph_output_changed(self):
        print("Graph output changed signal received")
        output_node = self._model.rt.get_output_node()
        print(f"New output node: {output_node.get_name() if output_node else 'None'}")
