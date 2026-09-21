from textwrap import dedent
from typing import TYPE_CHECKING

from qtpy.QtCore import (
    QObject,
    QPoint,
    QPointF,
    Qt,
    Signal,
    Slot
)

from qtpy.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QListView, 
    QSplitter,
    QTableView, 
    QVBoxLayout, 
    QWidget, 
    QMainWindow, 
    QAction,
    QToolBar
)

from qdageditor5.views.directional_graph_view_5 import DirectionalGraphView5

if TYPE_CHECKING:
    from qdageditor5.models.abstract_dag_model import (
        InletName, 
        NodeName, 
        OutletName, 
        DirectionalLinkId
    )

from myqtx.selection_dialog import SelectionDialog
import myqtx

from QScriptEdit2.script_edit import ScriptEdit2
from QtScriptEditorAdvanced.script_edit_advanced import ScriptEditAdvanced
from QtScriptEditorAdvanced.components.python_keywords_completer import PythonKeywordsCompleter

from .pyflow5_document import ImportsListModel, PyFlowDocument
from .module_operator_tree_model import ModuleOperatorTreeModel


class PyFlow5Window(QMainWindow):
    output_node_changed = Signal()

    def __init__(self, parent=None)->None:
        super().__init__(parent)
        self.setWindowTitle("PyFlow5")

        # setup Model
        self._document = PyFlowDocument()

        # Setup UI
        self.setupActions()

        toolbar:QToolBar = self.addToolBar("Main Toolbar")
        toolbar.addAction(self._restart_kernel_action)

        # - Setup imports view -
        self._imports_view = QListView(self)
        self._imports_view.setModel(self._document.importsmodel())
        self._imports_view.setSelectionModel(self._document.importselectionmodel())
        
        # self._code_editor = ScriptEdit2(self)
        self._code_editor = ScriptEditAdvanced(
            completer=None,
            parent=self
        )
        # two-way binding between code editor and script module
        def update_code_editor():
            
            selected_import_idx = self._document.importselectionmodel().currentIndex()
            if not selected_import_idx.isValid():
                return
            
            next_script = self._document.importsmodel().data(selected_import_idx, ImportsListModel.CodeRole) 
            # todo: consider moving change guard to the code editor itself
            current_script = self._code_editor.toPlainText()
            if current_script != next_script:
                self._code_editor.blockSignals(True)
                self._code_editor.setPlainText(next_script)
                self._code_editor.blockSignals(False)

        update_code_editor()
        self._document.importsmodel().modelReset.connect(update_code_editor)
        self._document.importsmodel().dataChanged.connect(update_code_editor)
        self._document.importselectionmodel().selectionChanged.connect(update_code_editor)

        def update_script_module():
            selected_import_idx = self._document.importselectionmodel().currentIndex()
            if not selected_import_idx.isValid():
                return

            new_text = self._code_editor.toPlainText()
            self._document.importsmodel().setData(selected_import_idx, new_text, ImportsListModel.CodeRole)

        self._code_editor.textChanged.connect(update_script_module)
        # self._document.scriptmodule().state_changed.connect(self._on_script_module_state_changed)
        
        # - Setup graphview -
        self._graph_view = DirectionalGraphView5(self)
        self._graph_view.setModel(self._document.graphmodel())
        self._graph_view.setSelectionModel(self._document.graphselectionmodel())
        self._graph_view.requestLink.connect(lambda src, outlet, dst, inlet: self._on_request_link(src, outlet, dst, inlet))
        self._graph_view.requestNode.connect(lambda pos, source: self._on_request_node(pos, source))
        self._graph_view.layout_nodes()
        self._graph_view.fitNodes()

        

        # - Setup display widget -
        self._display_widget = myqtx.DisplayWidget(self)

        # - Add widgets to splitter -
        splitter = QSplitter(self)
        splitter.addWidget(self._imports_view)
        splitter.addWidget(self._code_editor)
        splitter.addWidget(self._graph_view)
        splitter.addWidget(self._display_widget)
        splitter.setSizes([100, 400, 400, 400])
        self.resize(100+3*400, 600)


        self.setCentralWidget(splitter)

        self._graph_view.setFocus()

        # - Initial results update -
        self._document.execute()

        self._document.output_value_got_dirty.connect(self._on_output_value_got_dirty)

    def setupActions(self)->None:
        self._restart_kernel_action:QAction = QAction("Reset Graph View", self)
        self._restart_kernel_action.triggered.connect(self._document.reset_graph)
        open_operator_dialog_action = QAction("Open Operator Dialog", self)
        self.addAction(open_operator_dialog_action)
        open_operator_dialog_action.setShortcut("Ctrl+P")
        open_operator_dialog_action.triggered.connect(self.openOperatorDialog)

        delete_selected_nodes_action = QAction("Delete Selected Nodes", self)
        self.addAction(delete_selected_nodes_action)
        delete_selected_nodes_action.setShortcut("Del")
        delete_selected_nodes_action.triggered.connect(self._document.deleteSelectedNodes)

    def openOperatorDialog(self, *, scene_pos:QPointF|None=None, source:NodeName|None=None):
        dialog = SelectionDialog(self._document.operatormodel(), self)
        try:
            if dialog.exec() == QDialog.DialogCode.Accepted:
                selected_index = dialog.selected_index()
                selected_op = selected_index.data(ModuleOperatorTreeModel.OperatorRole)
                if selected_op:
                    self._document.graphmodel().addNode(selected_op, scene_pos or QPointF(0, 0))
        finally:
            dialog.deleteLater()

    @Slot()
    def _on_output_value_got_dirty(self):
        self._display_widget.display(self._document.execute())

    @Slot()
    def _on_script_module_state_changed(self):
        # set code editor style to red border if the script module is in an error state
        match self._code_editor:
            case ScriptEditAdvanced():
                state = self._document.scriptmodule().get_state()
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
                match self._document.scriptmodule().get_state():
                    case SyntaxError() as e:
                        self._code_editor.showError(e)
                    case Exception() as e:
                        self._code_editor.showError(e)
                    case "VALID":
                        self._code_editor.clearError()
                    case _:
                        pass

    @Slot()
    def _on_request_node(self, scene_pos:QPointF, source:NodeName):
        print(f"Request node signal received {scene_pos} {source}")
        # show a dialog with a multiselection of operator in GraphRT
        self.openOperatorDialog(scene_pos=scene_pos, source=source)

    @Slot()
    def _on_request_link(self, source:NodeName, outlet:OutletName, target:NodeName, inlet:InletName):
        self._document.graphmodel().addLink(source, outlet, target, inlet)
