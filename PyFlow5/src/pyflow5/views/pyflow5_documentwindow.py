import json
import os
import traceback
from textwrap import dedent
from typing import TYPE_CHECKING

from qdageditor5.adapters.node_inlet_tree_selection_model_adapter import NodeInletTreeSelectionModelAdapter

from .node_inspector_view import NodeInspectorView
from .node_input_delegate import NodeInputFieldDelegate, NodeInputLabelDelegate
from .output_viewer import OutputViewer

from pygraphrt.script_module import ScriptOperatorRef
from qtpy.QtCore import QAbstractItemModel, QItemSelectionModel, QModelIndex, QSize

from qtpy.QtCore import (
    QPoint,
    QPointF,
    Qt,
    QTimer,
    Signal,
    Slot
)

from qtpy.QtGui import QCloseEvent
from qtpy.QtGui import QAction, QActionGroup

from qtpy.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QDialog,
    QGridLayout,
    QHeaderView,
    QListView,
    QMenu,
    QMenuBar,
    QMessageBox,
    QPlainTextEdit, 
    QStyleFactory,
    QSplitter,
    QTabWidget,
    QTreeView,
    QVBoxLayout, 
    QWidget, 
    QMainWindow
)

# widgets
from myqtx.selection_dialog_view import SelectionDialog
from QtScriptEditorAdvanced.script_edit_advanced import ScriptEditAdvanced

# models
from qdageditor5.models.abstract_dag_model import (
    InletName, 
    NodeName, 
    OutletName, 
    DirectionalLinkId
)
from ..models.pyflow5_document import PyFlowDocument
from ..models.modules_operator_tree_model import ModulesOperatorsTreeModel

# views
from qdageditor5.views.directional_graph_view_5 import DirectionalGraphView5
from .module_details_view import ModuleDetailsView

from qdageditor5.models.graph_selection_model import GraphSelectionModel

class PyFlow5DocumentWindow(QWidget):
    def __init__(self, document: PyFlowDocument, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("PyFlow5")

        # Modules Panel
        ## modules list
        self._modules_listview = QListView(self)
        self._modules_listview.setMouseTracking(True)
        self._modules_listview.setFixedWidth(100)
        self._modules_listview.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._modules_listview.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._modules_listview.customContextMenuRequested.connect(self._show_modules_context_menu)
        self._modules_listview.setIconSize(QSize(14, 14))

        ## module details
        self._module_details_view = ModuleDetailsView(self)

        ## panel layout
        self._modules_panel = QWidget(self)
        module_panel_layout = QHBoxLayout()
        self._modules_panel.setLayout(module_panel_layout)
        module_panel_layout.addWidget(self._modules_listview, 0)
        module_panel_layout.addWidget(self._module_details_view, 1)
        
        # Graph View
        self._graph_view = DirectionalGraphView5(self)
        self._graph_view.requestNode.connect(lambda scene_pos, source: 
            self.openOperatorDialog(scene_pos=scene_pos, source=source)
        )
        self._graph_view.requestLink.connect(lambda source, outlet, target, inlet:
            self.document().graph_model.addLink(source, outlet, target, inlet)
        )

        # Node inlet tree panel
        self._node_inlet_tree_view = QTreeView(self)
        self._node_inlet_tree_view.setMouseTracking(True)
        node_tree_header:QHeaderView = self._node_inlet_tree_view.header()
        node_tree_header.setStretchLastSection(True)
        node_tree_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        node_tree_header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._node_input_delegate = NodeInputFieldDelegate(self._node_inlet_tree_view)
        self._node_inlet_tree_view.setItemDelegateForColumn(1, self._node_input_delegate)
        self._node_inlet_tree_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

        # Node Inspector
        self._node_inspector = NodeInspectorView(self)
        self._node_inspector.setFieldDelegate(NodeInputFieldDelegate(parent=self))
        self._node_inspector.setLabelDelegate(NodeInputLabelDelegate(parent=self))

        # Output Viewer
        self._viewer = OutputViewer(self)

        # LAYOUT
        ## Graph+Inspector panel
        self._graph_panel = QWidget(self)
        graph_panel_layout = QGridLayout(self._graph_panel)
        graph_panel_layout.setContentsMargins(0, 0, 0, 0)
        graph_panel_layout.addWidget(self._graph_view, 0, 0)
        graph_panel_layout.addWidget(
            self._node_inspector,
            0,
            0,
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight,
        )

        ## Left tabs
        self._left_tabwidget = QTabWidget(self)
        self._left_tabwidget.addTab(self._modules_panel, "Modules")
        self._left_tabwidget.addTab(self._graph_panel, "Graph")
        self._left_tabwidget.setCurrentIndex(1)

        ## Right Tabs
        self._right_tabwidget = QTabWidget(self)
        self._right_tabwidget.addTab(self._viewer, "Viewer")
        self._right_tabwidget.addTab(self._node_inlet_tree_view, "Node Inlets")

        ## Main Splitter
        splitter = QSplitter(self)
        splitter.addWidget(self._left_tabwidget)
        splitter.addWidget(self._right_tabwidget)
        splitter.setSizes([730, 730])
        self.resize(1460, 760)

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(splitter)

        # Set initial focus to the graph view
        self._graph_view.setFocus()

        # Connect the document to the views
        # private members
        self._document: PyFlowDocument | None = None
        self._connectDocument(document)

    def _connectDocument(self, document: PyFlowDocument) -> None:
        if document is self._document:
            return
        # Keep the old document alive until its views have disconnected.
        if self._document is not None:
            self._document.close()

        if document:
            self._modules_listview.setModel(document.modules_model)
            self._module_details_view.setModel(document.modules_model)

            self._graph_view.setModel(document.graph_model)
            self._node_inlet_tree_view.setModel(document.node_inlet_tree_adapter)


            self._viewer.setModel(document.node_inlet_tree_adapter)
            
            self._node_inspector.setModel(document.node_inlet_tree_adapter)
            
            self._node_inlet_tree_view.expandAll()

            # selection
            self.modulesselection_model = QItemSelectionModel(document.modules_model)
            self._modules_listview.setSelectionModel(self.modulesselection_model)
            self._module_details_view.setSelectionModel(self.modulesselection_model)
            self.graphselection_model = GraphSelectionModel(document.graph_model)
            self.graphselection_model.currentNodeChanged.connect(
                lambda current, previous: self.document().requestNodeExecution(current)
            )
            self.node_inlet_tree_selection_adapter = NodeInletTreeSelectionModelAdapter(document.node_inlet_tree_adapter)
            self.node_inlet_tree_selection_adapter.setSourceSelection(self.graphselection_model)
            self._node_inlet_tree_view.setSelectionModel(self.node_inlet_tree_selection_adapter)
            self._viewer.setSelectionModel(self.node_inlet_tree_selection_adapter)
            self._node_inspector.setSelectionModel(self.node_inlet_tree_selection_adapter)
            document.nodesInvalidated.connect(self._on_nodes_invalidated)

            self._graph_view.setSelectionModel(self.graphselection_model)

        self._document = document
        def layout_and_fit_nodes():
            self._graph_view.layout_nodes()
            self._graph_view.fitNodes()

        QTimer.singleShot(0, layout_and_fit_nodes)
        
    def _on_nodes_invalidated(self, node_names: list[NodeName]) -> None:
        current_name = self.graphselection_model.currentNode()
        if current_name is None:
            return

        if current_name not in node_names:
            return

        self.document().requestNodeExecution(current_name)

    def document(self)->PyFlowDocument:
        return self._document

    def _show_modules_context_menu(self, pos):
        index = self._modules_listview.indexAt(pos)
        global_pos = self._modules_listview.viewport().mapToGlobal(pos)
        
        # Create a fresh, local menu instance right here
        menu = QMenu(self._modules_listview)
        add_action = menu.addAction("Add Embedded Module")
        add_action.triggered.connect(self.addEmbeddedModule)

        if self.modulesselection_model.hasSelection():
            # Pass the specific index data directly into your deletion method
            item_text = index.data()
            remove_action = menu.addAction(f"Remove '{item_text}'")

            #todo remove selection with batches using the .selection()->QItemSelection
            def remove_selected_modules():
                selected_indexes = self.modulesselection_model.selectedIndexes()
                for selected_index in selected_indexes:
                    self._document.modules_model.removeRows(selected_index.row(), 1)
            remove_action.triggered.connect(remove_selected_modules)
            
        # Execute the local menu (blocks until closed, then gets garbage collected)
        menu.exec(global_pos)

    def deleteSelectedNodes(self):
        assert self._document is not None, "Document must be available to delete selected nodes."
        selected_nodes = self.graphselection_model.selectedNodes()
        self.document().deleteNodes(selected_nodes)

    def addEmbeddedModule(self, name="_local_") -> None:
        if module_idx := self.document().modules_model.addEmbeddedModule(name):
            self.modulesselection_model.setCurrentIndex(
                module_idx, 
                QItemSelectionModel.ClearAndSelect
            )

    def removeSelectedModule(self) -> None:
        current_index = self.modulesselection_model.currentIndex()
        if current_index:
            self.document().modules_model.removeModule(current_index)

    @Slot()
    def _navigate_to_current_node_operator(self):
        if self._document is None:
            return
        
        current_node = self._document.graphselection_model.currentNode()
        if not current_node:
            return

        # get the node module, and select it in the module view
        operator_index = self._document.getNodeOperator(current_node)
        if operator_index.isValid():
            self._left_tabwidget.setCurrentWidget(self._modules_panel)
            module_index = operator_index.parent()
            self.modulesselection_model.setCurrentIndex(module_index, QItemSelectionModel.ClearAndSelect)

            self._module_details_view.goToOperator(operator_index)

    def importModule(self) -> None:
        # open file browser dialog
        file_dialog = QFileDialog(self)
        file_dialog.setOption(QFileDialog.DontUseNativeDialog, True)
        file_dialog.setFileMode(QFileDialog.ExistingFile)
        relative_path_option = QCheckBox("Import with relative path", file_dialog)
        relative_path_option.setToolTip("Relative to the current working directory.")
        layout = file_dialog.layout()
        layout.addWidget(relative_path_option, layout.rowCount(), 0, 1, layout.columnCount())
        if file_dialog.exec_():
            selected_files = file_dialog.selectedFiles()
            if selected_files:
                file_path = selected_files[0]
                if relative_path_option.isChecked():
                    try:
                        file_path = os.path.relpath(file_path)
                    except ValueError:
                        QMessageBox.warning(
                            self,
                            "Cannot import with relative path",
                            "The file must be on the same drive as the current working directory.",
                        )
                        return
                module = self._document.importModule(file_path)
                if module is not None:
                    state = module.get_status()
                    if isinstance(state, Exception):
                        error = state.__cause__ or state
                        warning = QMessageBox(self)
                        warning.setIcon(QMessageBox.Icon.Warning)
                        warning.setWindowTitle("Script has issues")
                        warning.setTextFormat(Qt.TextFormat.PlainText)
                        warning.setText(f"{type(error).__name__}: {error}")
                        warning.setInformativeText(
                            f'The script "{file_path}" could not be evaluated.\n\n'
                            "The source is available to view, but its operators are unavailable.",
                        )
                        warning.setDetailedText("".join(traceback.format_exception(error)))
                        warning.exec()

    def openOperatorDialog(self, *, scene_pos:QPointF|None=None, source:NodeName|None=None) -> None:
        if scene_pos is None:
            viewport_center = QPointF(self._graph_view.contentsRect().center())
            scene_pos = self._graph_view.mapToScene(viewport_center)

        dialog = SelectionDialog(self._document.modules_model, self)
        try:
            if dialog.exec() == QDialog.DialogCode.Accepted:
                selected_index = dialog.selected_index()
                selected_op = self._document.modules_model.mapToSource(selected_index)
                
                if selected_op and isinstance(selected_op, ScriptOperatorRef):
                    self._document.graph_model.addNode(selected_op, scene_pos)
        finally:
            dialog.deleteLater()

    def closeEvent(self, event: QCloseEvent) -> None:
        # Destroy field editors while their delegates and models are still alive.
        self._node_inspector.setSelectionModel(None)
        self._node_inspector.setModel(None)
        self._viewer.setSelectionModel(None)
        self._viewer.setModel(None)
        self._node_inlet_tree_view.setModel(None)
        self._module_details_view.setModel(None)
        self._modules_listview.setModel(None)
        self._graph_view.setSelectionModel(None)
        self._graph_view.setModel(None)
        if self._document is not None:
            self._document.close()
        event.accept()

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
            case _:
                assert False, f"Unknown code editor type {self._code_editor}"
