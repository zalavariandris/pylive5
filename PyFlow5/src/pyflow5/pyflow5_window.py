from typing import Iterable
import traceback
from pyflow5.operator_selection_dialog import OperatorSelectionDialog
from qtpy.QtCore import Qt
from qtpy.QtWidgets import QAction

from pygraphrt.operator_rt import OperatorRT
from qtpy.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout, 
    QSplitter, 
    QSplitter,
    QVBoxLayout, 
    QWidget, 
    QMainWindow
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

        module_script = dedent("""\
        def const1(val):
            return val

        def const2(val):
            return val

        def mult(a, b):
            return a * b
        """)
        
        self._G = rt.GraphRT()

        def functions_from_script(script)->Iterable[callable]:
            local_vars = {}
            exec(script, {}, local_vars)
            for k, v in local_vars.items():
                if callable(v):
                    yield v

            return k, v

        # add the operators from the script
        for func in functions_from_script(module_script):
            self._G.op()(func)

        def _on_results_changed():
            try:
                result = self._G.execute()
                self._display_widget.display(result)
            except Exception as e:
                self._display_widget.display(e)
                traceback.print_exc()

        open_operator_dialog_action = QAction("Open Operator Dialog", self)
        self.addAction(open_operator_dialog_action)
        open_operator_dialog_action.setShortcut("Ctrl+P")
        open_operator_dialog_action.triggered.connect(self.openOperatorDialog)

        # self._watcher = rt.watch(G, G.output, _on_results_changed)
        # def watch_graph_node(node:rt.NodeRT):
        #     self._watcher.stop()
        #     self._watcher = rt.watch(G, node, _on_results_changed)

        # G.output_node_changed.connect(lambda: watch_graph_node(G.output))
        
        self._model = PyFlowRtModel(self._G)
        self._selection = GraphSelectionModel(self._model)

        layout = QHBoxLayout(self)
        splitter = QSplitter(self)
        layout.addWidget(splitter)
        
        self._code_editor = ScriptEdit2(self)
        self._code_editor.setPlainText(module_script)
        self._code_editor.textChanged.connect(self._on_text_changed)
        self._graph_view = DirectionalGraphView5(self)
        self._graph_view.setModel(self._model)
        self._graph_view.setSelectionModel(self._selection)
        self._graph_view.requestLink.connect(self._on_request_link)
        self._graph_view.requestNode.connect(self._on_request_node)
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

    def _on_text_changed(self):
        script = self._code_editor.toPlainText()
        try:
            pass
            # G = rt.utils.graph_from_script(script, 'G')
            # rt.patch(self._model.rt, G)
            # # self._graph_view.layout_nodes()
            # result = G.execute()
            # self._display_widget.display(result)
            
        except Exception as err:
            # print(f"Error updating graph: {e}")
            self._display_widget.display(err)
            import traceback
            traceback.print_exc()

    def openOperatorDialog(self):
        operators_map:dict[str, OperatorRT] = self._G.operators()
        dialog = OperatorSelectionDialog(operators_map.keys(), self)
        if dialog.exec_() == QDialog.Accepted:
            if selected_op_name := dialog.selected_operator():
                selected_op = operators_map[selected_op_name]
                new_node = self._G.node()(selected_op)
                print("New node created:", new_node)

    def _on_request_node(self):
        print("Request node signal received")
        # show a dialog with a multiselection of operator in GraphRT
        self.openOperatorDialog()

    def _on_request_link(self, source:NodeName, outlet:OutletName, target:NodeName, inlet:InletName):
        target_rt = self._model.rt.get_node(target)
        args, kwargs = target_rt.get_inputs()
        print(f"inputs:\n  {args}\n  {kwargs}")

    def _on_graph_output_changed(self):
        print("Graph output changed signal received")
        output_node = self._model.rt.get_output_node()
        print(f"New output node: {output_node.get_name() if output_node else 'None'}")
