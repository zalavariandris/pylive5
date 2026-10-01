import json
import os
from textwrap import dedent
from typing import TYPE_CHECKING
from pyflow5.viewer_view import Viewer
from pygraphrt.script_module import ScriptOperatorRef
from qtpy.QtCore import QAbstractItemModel, QModelIndex

from qtpy.QtCore import (
    QPointF,
    Qt,
    Signal,
    Slot
)

from qtpy.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFileDialog,
    QLabel,
    QDialog,
    QListView,
    QMenu,
    QMenuBar,
    QMessageBox,
    QPlainTextEdit, 
    QSplitter,
    QVBoxLayout, 
    QWidget, 
    QMainWindow
)

# widgets
from myqtx.selection_dialog import SelectionDialog
from QtScriptEditorAdvanced.script_edit_advanced import ScriptEditAdvanced

# models
from qdageditor5.models.abstract_dag_model import (
    InletName, 
    NodeName, 
    OutletName, 
    DirectionalLinkId
)
from .pyflow5_document import PyFlowDocument
from .modules_operator_tree_model import ModulesOperatorsTreeModel

# views
from qdageditor5.views.directional_graph_view_5 import DirectionalGraphView5
from .inspector_view import InspectorEditor, InspectorView
from .module_details_view import ModuleDetailsView


class PyFlow5Window(QMainWindow):
    def __init__(self, parent=None)->None:
        super().__init__(parent)
        self.setWindowTitle("PyFlow5")

        # setup Model
        self._document:PyFlowDocument = PyFlowDocument()

        # Setup UI
        # self.setupActions()

        # - Setup modules view -
        self._modules_listview = QListView(self)
        self._modules_listview.setModel(self._document.modules_model)
        self._modules_listview.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._modules_listview.setSelectionModel(self._document.modulesselection_model)

        # - Setup modules details view -
        self._module_details_view = ModuleDetailsView(self)
        self._module_details_view.setModel(self._document.modules_model)
        self._document.modulesselection_model.selectionChanged.connect(
            lambda selected, deselected: 
            self._module_details_view.setCurrentIndex(
                selected.indexes()[0] if selected.indexes() else QModelIndex())
        )
        self._module_details_view

        # - Setup graphview -
        self._graph_view = DirectionalGraphView5(self)
        self._graph_view.setModel(self._document.graph_model)
        self._graph_view.setSelectionModel(self._document.graphselection_model)
        self._graph_view.layout_nodes()
        self._graph_view.fitNodes()

        @Slot()
        def _on_request_node(scene_pos:QPointF, source:NodeName):
            # show a dialog with a multiselection of operator in GraphRT
            self.openOperatorDialog(scene_pos=scene_pos, source=source)
        self._graph_view.requestNode.connect(_on_request_node)

        @Slot()
        def _on_request_link(source:NodeName, outlet:OutletName, target:NodeName, inlet:InletName):
            self._document.graph_model.addLink(source, outlet, target, inlet)
        self._graph_view.requestLink.connect(_on_request_link)

        # - Setup node inspector -
        self._inspector_view = InspectorView(self)
        self._inspector_view.setModel(self._document.graphdetails_model)
        # self._inspector_view.setSelectionModel(self._document.graphselectionmodel)

        # - Setup display widget -

        self._document.graphselection_model.nodesSelectionChanged.connect(
            lambda selected, deselected: print(selected, deselected)
        )
        
        self._viewer = Viewer(self)
        self._viewer.setModel(self._document.graph_model)
        self._document.graphselection_model.nodesSelectionChanged.connect(
            lambda selected, deselected: 
            self._viewer.setCurrentNodeName(
                next(iter(selected)) if selected else None)
        )
        # self._document._graphselection_model.selectionChanged.connect(
        #     lambda selected, deselected: 
        #     self._viewer.setCurrentNodeName(
        #         selected.indexes()[0] if selected.indexes() else None)
        # )

        # viewer = QWidget(self)
        # viewer_layout = QVBoxLayout(viewer)
        # viewer_layout.setContentsMargins(0, 0, 0, 0)
        # viewer_header = QHBoxLayout()
        # viewer_header.addWidget(QLabel("Viewer", viewer))
        # viewer_header.addStretch()
        # self._viewer_lock_switch = QCheckBox("Lock", viewer)
        # self._viewer_lock_switch.setToolTip("Keep viewing this output when the selection changes.")
        # self._viewer_lock_switch.setChecked(self._document.isOutputLocked())
        # self._viewer_lock_switch.toggled.connect(self._document.setOutputLocked)
        # self._document.output_lock_changed.connect(self._viewer_lock_switch.setChecked)
        # viewer_header.addWidget(self._viewer_lock_switch)
        # viewer_layout.addLayout(viewer_header)
        # self._display_widget = myqtx.DisplayWidget(viewer)
        # viewer_layout.addWidget(self._display_widget)



        # - Serialization widget -
        self._serialization_window = QDialog(self)
        self._serialization_window.setWindowTitle("Serialization")
        self._serialization_window.resize(400, 600)
        serialization_layout = QVBoxLayout(self._serialization_window)
        self._serialization_widget = QPlainTextEdit(self._serialization_window)
        serialization_layout.addWidget(self._serialization_widget)

        self.setupMenubar()

        # - Add widgets to splitter -
        splitter = QSplitter(self)
        splitter.addWidget(self._modules_listview)
        splitter.addWidget(self._module_details_view)
        splitter.addWidget(self._graph_view)
        splitter.addWidget(self._inspector_view)
        splitter.addWidget(self._viewer)
        splitter.setSizes([100, 350, 400, 260, 350])
        self.resize(1460, 600)


        self.setCentralWidget(splitter)

        self._graph_view.setFocus()

        # - Initial results update -
        # self._document._execute()

    def setupMenubar(self):
        menubar: QMenuBar = self.menuBar()
        menubar.addAction("Restart Graph", self._document.reset_graph)

        file_menu = QMenu("File", self)
        menubar.addMenu(file_menu)
        file_menu.addAction("New",           lambda: None).setShortcut("Ctrl+N")
        file_menu.addAction("Open Graph",    lambda: self.openGraph()).setShortcut("Ctrl+O")
        file_menu.addAction("Save Graph",    lambda: self.saveGraph()).setShortcut("Ctrl+S")
        file_menu.addAction("Save Graph As", lambda: None).setShortcut("Ctrl+Shift+S")
        file_menu.addSeparator()
        file_menu.addAction("Import Module", lambda: self.importModule()).setShortcut("Ctrl+I")
        file_menu.addAction("Add Local Module", lambda: self.addLocalModule())

        edit_menu = QMenu("Edit", self)
        menubar.addMenu(edit_menu)
        edit_menu.addAction("Undo",  lambda: None)
        edit_menu.addAction("Redo",  lambda: None)
        edit_menu.addAction("Cut",   lambda: None)
        edit_menu.addAction("Copy",  lambda: None)
        edit_menu.addAction("Paste", lambda: None)
        edit_menu.addSeparator()

        edit_menu.addAction("Select All", lambda: None)
        edit_menu.addAction("Select None", lambda: None)
        edit_menu.addSeparator()

        edit_menu.addAction("Restart Graph", self._document.reset_graph)
        edit_menu.addSeparator()

        edit_menu.addAction("New Node", self.openOperatorDialog).setShortcut("Ctrl+P")
        edit_menu.addAction("Delete Nodes", self._document.deleteSelectedNodes).setShortcut("Del")
        edit_menu.addAction("Duplicate Nodes", lambda: None)
        edit_menu.addSeparator()

        edit_menu.addAction("Edit Local Definitions", self.editLocalDefinitions)
        edit_menu.addAction("Remove Module", lambda: None)

        view_menu = QMenu("View", self)
        view_menu.addAction("fit nodes",  lambda: None)
        view_menu.addAction("layout nodes",  lambda: None)
        view_menu.addSeparator()
        menubar.addMenu(view_menu)

        window_menu = menubar.addMenu("Window")
        serialization_action = window_menu.addAction("Serialization")
        serialization_action.setCheckable(True)
        serialization_action.toggled.connect(self._serialization_window.setVisible)
        self._serialization_window.finished.connect(
            lambda _: serialization_action.setChecked(False)
        )

    def editLocalDefinitions(self):
        model = self._document.modules_proxy_model
        # `Local` is the first editable module in every graph.
        self._modules_listview.setCurrentIndex(model.index(0, 0))
        self._code_editor.setFocus()

    def addLocalModule(self):
        self._document.addLocalModule()

    def importModule(self):
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
                self._document.importModule(file_path)

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

    def openGraph(self) -> None:
        # # open file browser dialog
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open file",
            "",
            "JSON files (*.json)",
        )
        print(path)
        if path:
            try:
                self._document = PyFlowDocument.fromfile(path)
            except Exception as error:
                QMessageBox.warning(self, "Cannot open graph", str(error))

    def saveGraph(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save file",
            "untitled.json",
            "JSON files (*.json)",
        )
        if path:
            try:
                self._document.save(path)
            except Exception as error:
                QMessageBox.warning(self, "Cannot save graph", str(error))

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
