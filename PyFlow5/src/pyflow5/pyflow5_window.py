import json
import os
from textwrap import dedent
from typing import TYPE_CHECKING
from PyFlow5.src.pyflow5.node_input_delegate import NodeInputDelegate
from pyflow5.viewer_view import Viewer
from pygraphrt.script_module import ScriptOperatorRef
from qtpy.QtCore import QAbstractItemModel, QModelIndex

from qtpy.QtCore import (
    QPointF,
    Qt,
    QTimer,
    Signal,
    Slot
)

from qtpy.QtGui import QCloseEvent
from qtpy.QtGui import QActionGroup

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

from qtpy.QtCore import QSettings

from pathlib import Path

class DetailsView(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._model:QAbstractItemModel|None=None
        self._model_connections: list[tuple[Signal, Slot]] = []
        self._selection_model: QAbstractItemModel|None = None
        self._selection_model_connections: list[tuple[Signal, Slot]] = []
        
    def setModel(self, model):
        if self._model:
            for signal, slot in self._model_connections:
                signal.disconnect(slot)
            self._model_connections = []
            self._model = None

        if model:
            self._model_connections = [
                (self._model, self._model.dataChanged),
                (self._model, self._model.rowsRemoved),
                (self._model, self._model.modelReset),
            ]
            for signal, slot in self._model_connections:
                signal.connect(slot)

            self._model = model

    def setSelecitonModel(self, selection_model):
        if selection_model.model() != self._model:
            raise ValueError("Selection model's model does not match the current model.")
        
        if self._selection_model:
            for signal, slot in self._selection_model_connections:
                signal.disconnect(slot)
            self._selection_model_connections = []
            self._selection_model = None

        if selection_model:
            self._selection_model_connections = [
                (selection_model, selection_model.currentChanged),
            ]
            for signal, slot in self._selection_model_connections:
                signal.connect(slot)

            self._selection_model = selection_model


class PyFlow5Window(QMainWindow):
    def __init__(self, use_session=False, parent=None)->None:
        super().__init__(parent)
        self.setWindowTitle("PyFlow5")
        self._use_session = use_session # this should be factored out into a configuration or settings manager see todos

        # - Setup modules view -
        self._modules_listview = QListView(self)
        self._modules_listview.setFixedWidth(100)
        self._modules_listview.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        
        # - Setup modules details view -
        self._module_details_view = ModuleDetailsView(self)
        
        # - Setup graphview -
        self._graph_view = DirectionalGraphView5(self)
        @self._graph_view.requestNode.connect
        def _on_request_node(scene_pos:QPointF, source:NodeName):
            # show a dialog with a multiselection of operator in GraphRT
            self.openOperatorDialog(scene_pos=scene_pos, source=source)

        @self._graph_view.requestLink.connect
        def _on_request_link(source:NodeName, outlet:OutletName, target:NodeName, inlet:InletName):
            self._document.graph_model.addLink(source, outlet, target, inlet)

        # - Setup node inspector -
        # self._inspector_view = InspectorView(self)
        self._node_tree_view = QTreeView(self)
        node_tree_header = self._node_tree_view.header()
        node_tree_header.setStretchLastSection(True)
        node_tree_header.setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        node_tree_header.setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self._node_tree_view.setItemDelegateForColumn(
            1, 
            NodeInputDelegate(self._node_tree_view)
        )
        self._node_tree_view.hide()
        
        # - Setup display widget -
        self._viewer = Viewer(self)
        
        # - Serialization widget -
        self._serialization_window = QDialog(self)
        self._serialization_window.setWindowTitle("Serialization")
        self._serialization_window.resize(400, 600)
        serialization_layout = QVBoxLayout(self._serialization_window)
        self._serialization_widget = QPlainTextEdit(self._serialization_window)
        serialization_layout.addWidget(self._serialization_widget)

        # - Settings
        self._settings = QSettings(
            QSettings.Format.IniFormat, # format
            QSettings.Scope.UserScope, # scope
            "BABLab", # organization
            "PyFlow5" # application
        )

        app = QApplication.instance()
        if app is None:
            raise RuntimeError("PyFlow5Window requires a QApplication instance")
        style_keys = {key.casefold(): key for key in QStyleFactory.keys()}
        self._system_style_key = style_keys.get(
            app.style().objectName().casefold(), "Fusion"
        )
        self._theme = self._settings.value("theme", "system", type=str)
        if self._theme not in {"system", "fusion", "dark"}:
            self._theme = "system"
        self._applyTheme(self._theme, persist=False)

        self._recent_graphs: list[str] = self._settings.value(
            "recentGraphs", [], type=list
        )

        self._session_path = (
            Path(self._settings.fileName()).parent / "session.json"
        )

        # - Overlay the selected node tree on the graph -
        self._graph_container = QWidget(self)
        graph_layout = QGridLayout(self._graph_container)
        graph_layout.setContentsMargins(0, 0, 0, 0)
        graph_layout.addWidget(self._graph_view, 0, 0)
        graph_layout.addWidget(
            self._node_tree_view,
            0,
            0,
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight,
        )

        # - Add widgets to splitter -
        splitter = QSplitter(self)
        modules_panel = QWidget(self)
        module_panel_layout = QHBoxLayout()
        modules_panel.setLayout(module_panel_layout)
        module_panel_layout.addWidget(self._modules_listview, 0)
        module_panel_layout.addWidget(self._module_details_view, 1)
        

        tabwidget = QTabWidget(self)
        tabwidget.addTab(modules_panel, "Modules")
        tabwidget.addTab(self._graph_container, "Graph")
        splitter.addWidget(tabwidget)
        splitter.addWidget(self._viewer)
        splitter.setSizes([730, 730])
        self.resize(1460, 600)

        self.setCentralWidget(splitter)

        self._graph_view.setFocus()

        # Setup Model
        self._document:PyFlowDocument|None = None

        # Create a new document and connect it to the window
        # Load the last session if it exists
        if self._use_session and self._session_path.exists():
            new_document = PyFlowDocument().fromfile(str(self._session_path))
        else:
            new_document = PyFlowDocument()

        self.setupMenubar()
        self._connectDocument(new_document)

    def _connectDocument(self, document: PyFlowDocument):
        # Keep the old document alive until its views have disconnected.
        if document:
            self._modules_listview.setModel(document.modules_model)
            self._modules_listview.setSelectionModel(document.modulesselection_model)
            self._module_details_view.setModel(document.modules_model)
            self._module_details_view.setSelectionModel(document.modulesselection_model)

            self._graph_view.setModel(document.graph_model)
            self._graph_view.setSelectionModel(document.graphselection_model)
            self._graph_view.layout_nodes()
            # Fit after the window's startup layout has been established.
            QTimer.singleShot(0, self._graph_view.fitNodes)
            self._node_tree_view.setModel(document.nodes_tree_model)
            document.nodes_tree_model.modelReset.connect(
                lambda: self._node_tree_view.expandAll())
            # self._inspector_view.setModel(document.graphdetails_model)
            self._viewer.setModel(document.graph_model)
            self._viewer.setSelectionModel(document.graphselection_model)

            # set the new document
            self._document = document

            self._document.graphselection_model.nodesSelectionChanged.connect(
                self._on_graph_selection_changed
            )
            self._on_graph_selection_changed(set(), set())

        # todo: with the inspector, reconsider setting the CurrentIndex directly, 
        # and remove setSelectionModel methods
        # (as well as using that pattern with the other detail views as well)
        # when a new document is created the signals from the document will
        # go away with the old document anyway. Meanwhile signals from the view, will
        # target the new document

    def _on_graph_selection_changed(
        self, selected: set[NodeName], deselected: set[NodeName]
    ) -> None:
        assert self._document is not None
        selection = self._document.graphselection_model.selectedNodes()
        if len(selection) == 1:
            root = self._document.nodes_tree_model.indexFromNodeName(selection[0])
        else:
            root = QModelIndex()  # show all nodes
        self._node_tree_view.setRootIndex(root)
        self._node_tree_view.setVisible(bool(selection))

    def newDocument(self) -> None:
        self._connectDocument(PyFlowDocument())

    def openDocument(self, path: str = "") -> None:
        if not path:
            # open file browser dialog
            path, _ = QFileDialog.getOpenFileName(
                self,
                "Open file",
                "",
                "JSON files (*.json)",
            )

        if path:
            try:
                document = PyFlowDocument.fromfile(path)
            except Exception as error:
                QMessageBox.warning(self, "Cannot open graph", str(error))
            else:
                self._connectDocument(document)
                self._rememberGraph(path)
        
    def _rememberGraph(self, path: str) -> None:
        path = os.path.abspath(path)
        path_key = os.path.normcase(path)

        previous = [
            existing
            for existing in self._recent_graphs
            if os.path.normcase(existing) != path_key
        ]
        self._recent_graphs = [path, *previous][:5]

        self._settings.setValue("recentGraphs", self._recent_graphs)
        self._settings.sync()

    def setupMenubar(self):
        menubar: QMenuBar = self.menuBar()
        menubar.addAction("Restart Graph", lambda: self._document.reset_graph())

        file_menu = QMenu("File", self)
        menubar.addMenu(file_menu)
        file_menu.addAction("New",           lambda: self.newDocument()).setShortcut("Ctrl+N")
        file_menu.addAction("Open Graph",    lambda: self.openDocument()).setShortcut("Ctrl+O")
        recents_menu = QMenu("Recent Graphs", self)
        for recent in self._recent_graphs:
            recents_menu.addAction(recent, lambda path=recent: self.openDocument(path))
        file_menu.addMenu(recents_menu)
        file_menu.addAction("Save Graph",    lambda: self.saveDocument()).setShortcut("Ctrl+S")
        file_menu.addAction("Save Graph As", lambda: None).setShortcut("Ctrl+Shift+S")
        file_menu.addSeparator()
        

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

        edit_menu.addAction("Restart Graph", lambda: self._document.reset_graph())
        edit_menu.addSeparator()

        edit_menu.addAction("New Node", self.openOperatorDialog).setShortcut("Ctrl+P")
        edit_menu.addAction("Delete Nodes", lambda: self._document.deleteSelectedNodes()).setShortcut("Del")
        edit_menu.addAction("Duplicate Nodes", lambda: None)
        edit_menu.addSeparator()

        edit_menu.addAction("Import Module", lambda: self.importModule()).setShortcut("Ctrl+I")
        edit_menu.addAction("Add Local Module", lambda: self.addLocalModule())
        edit_menu.addAction("Remove Selected Module", lambda: self.removeSelectedModule())

        view_menu = QMenu("View", self)
        view_menu.addAction("fit nodes",  lambda: None)
        view_menu.addAction("layout nodes",  lambda: None)
        view_menu.addSeparator()
        theme_menu = view_menu.addMenu("Theme")
        theme_group = QActionGroup(self)
        theme_group.setExclusive(True)
        for label, theme in (
            ("System", "system"),
            ("Fusion", "fusion"),
            ("Dark", "dark"),
        ):
            action = theme_menu.addAction(label)
            action.setCheckable(True)
            theme_group.addAction(action)
            action.triggered.connect(
                lambda checked=False, selected=theme: self._applyTheme(selected)
            )
            action.setChecked(theme == self._theme)
        menubar.addMenu(view_menu)

        window_menu = menubar.addMenu("Window")
        serialization_action = window_menu.addAction("Serialization")
        serialization_action.setCheckable(True)
        serialization_action.toggled.connect(self._serialization_window.setVisible)
        self._serialization_window.finished.connect(
            lambda _: serialization_action.setChecked(False)
        )

    def _applyTheme(self, theme: str, *, persist: bool = True) -> None:
        app = QApplication.instance()
        if app is None:
            raise RuntimeError("Theme changes require a QApplication instance")

        app.setStyleSheet("")
        if theme == "system":
            app.setStyle(self._system_style_key)
        elif theme == "fusion":
            app.setStyle("Fusion")
        elif theme == "dark":
            import qdarkstyle

            app.setStyle("Fusion")
            app.setStyleSheet(qdarkstyle.load_stylesheet(qt_api="pyqt6"))
        else:
            raise ValueError(f"Unknown theme: {theme}")

        self._theme = theme
        if persist:
            self._settings.setValue("theme", theme)
            self._settings.sync()

    def addLocalModule(self):
        self._document.addEmbeddedModule()

    def removeSelectedModule(self):
        self._document.removeSelectedModule()

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

    def closeEvent(self, event):
        # Save session path before closing
        if self._use_session:
            try:
                
                self._session_path.parent.mkdir(parents=True, exist_ok=True)
                self._document.save(self._session_path)
            except Exception as error:
                answer = QMessageBox.warning(
                    self,
                    "Cannot save session",
                    f"The session could not be saved:\n{error}\n\n"
                    "Close the app anyway? Unsaved changes may be lost.",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    event.ignore()
                    return

        event.accept()

    def saveDocument(self) -> None:
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
