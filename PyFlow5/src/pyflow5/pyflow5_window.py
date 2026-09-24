import json
import os
from textwrap import dedent
from typing import TYPE_CHECKING
from qtpy.QtCore import QAbstractItemModel, QItemSelection, QItemSelectionModel, QModelIndex

from qtpy.QtCore import (
    QObject,
    QPoint,
    QPointF,
    Qt,
    Signal,
    Slot
)

from qtpy.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QCheckBox,
    QFileDialog,
    QLabel,
    QDialog,
    QHBoxLayout,
    QListView,
    QMenu,
    QMenuBar,
    QMessageBox,
    QPlainTextEdit, 
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

from myqtx.color_editor_widget import ColorEdit
from myqtx.selection_dialog import SelectionDialog
import myqtx

from QScriptEdit2.script_edit import ScriptEdit2
from QtScriptEditorAdvanced.script_edit_advanced import ScriptEditAdvanced
from QtScriptEditorAdvanced.components.python_keywords_completer import PythonKeywordsCompleter

from .pyflow5_document import PyFlowDocument
from .modules_operator_tree_model import ModulesOperatorsTreeModel


from .inspector_view import InspectorEditor, InspectorView

def _color_editor(index:QModelIndex, parent:QWidget=None)->InspectorEditor:
    widget = ColorEdit(parent)
    color_type = type(index.data(Qt.ItemDataRole.EditRole))

    def write(color):
        nonlocal color_type
        color_type = type(color)
        widget.setColor(color.r, color.g, color.b, color.a)

    return InspectorEditor(
        widget,
        lambda: color_type(*widget.color()),
        write,
        widget.valueChanged,
    )


class ModuleDetailsView(QWidget):
    # consider refactoring this class using a QDataWidgetMapper
    def __init__(self, parent:QWidget=None):
        super().__init__(parent=parent)
        
        self._model:QAbstractItemModel = None
        self._model_connections = []

        self._selection_model: QItemSelectionModel = None
        self._selection_connections = []
        self._current: QModelIndex = QModelIndex()

        # self._code_editor = ScriptEdit2(self)
        self._title_label = QLabel(self)
        self._code_editor = ScriptEditAdvanced(
            completer=None,
            parent=self
        )
        self._code_editor.textChanged.connect(self._on_editor_text_changed)

        layout = QVBoxLayout(self)
        layout.addWidget(self._title_label)
        layout.addWidget(self._code_editor)
        self.setLayout(layout)

    def model(self):
        return self._model

    def setModel(self, model: QAbstractItemModel|None):
        if self._model:
            for signal, slot in self._model_connections:
                signal.disconnect(slot)
            self._model_connections.clear()

        if model:
            self._model_connections = [
                (model.modelReset,  self._on_model_reset),
                (model.dataChanged, self._on_data_changed),
                (model.rowsRemoved, self._on_rows_removed)
            ]
        self._model = model

    def setSelectionModel(self, selection_model: QItemSelectionModel|None):
        prev_current = QModelIndex()
        if self._selection_model:
            for signal, slot in self._selection_connections:
                signal.disconnect(slot)
            self._selection_connections.clear()
            prev_current = self._selection_model.currentIndex()

        next_current = QModelIndex()
        if selection_model:
            self._selection_connections = [
                (selection_model.currentChanged, self._on_current_changed),
                (selection_model.selectionChanged, self._on_selection_changed)
            ]
            for signal, slot in self._selection_connections:
                signal.connect(slot)
            next_current = selection_model.currentIndex()
        self._selection_model = selection_model
        self._on_current_changed(next_current, prev_current)

    def selectionModel(self):
        return self._selection_model

    def _on_editor_text_changed(self):
        current = self._selection_model.currentIndex()
        if not current.isValid():
            return

        new_text = self._code_editor.toPlainText()
        self._model.setData(current, new_text, ModulesOperatorsTreeModel.SourceRole)

    def _on_current_changed(self, current: QModelIndex, previous: QModelIndex):
        if self._model is None:
            return
        
        index = self._selection_model.currentIndex()
        self._show_index(index)

    def _on_selection_changed(self, selected: QItemSelection, deselected: QItemSelection):
        if self._model is None:
            return
        
        last_selected = selected.indexes()[-1] if selected.indexes() else QModelIndex()
        
        self._show_index(last_selected)
        return True
        
    def _show_index(self, index: QModelIndex):
        if index.isValid() and index.model() == self._model:
            self._title_label.setText(index.data(Qt.ItemDataRole.DisplayRole))
            with myqtx.blockingSignals(self._code_editor):
                text = index.data(ModulesOperatorsTreeModel.SourceRole)
                self._code_editor.setPlainText(text)
                self._code_editor.setEnabled(True)
        else:
            self._title_label.setText("<No Selection>")
            with myqtx.blockingSignals(self._code_editor):
                self._code_editor.clear()
                self._code_editor.setEnabled(False)

    @Slot()
    def _on_model_reset(self):
        if not self._current.isValid():
            return

        current = self._selection_model.currentIndex()
        if not current.isValid():
            return
        
        self._title_label.setText(current.data(Qt.ItemDataRole.DisplayRole))
        with myqtx.blockingSignals(self._code_editor):
            text = current.data(ModulesOperatorsTreeModel.SourceRole)
            self._code_editor.setPlainText(text)
            self._code_editor.setEnabled(True)

    @Slot()
    def _on_data_changed(self, topLeft: QModelIndex, bottomRight: QModelIndex, roles: list[int] = []):
        if not self._current.isValid():
            return

        current = self._selection_model.currentIndex()
        if not current.isValid():
            return
        
        if current.parent() == topLeft.parent() and topLeft.row() <= current.row() <= bottomRight.row():
            self._title_label.setText(current.data(Qt.ItemDataRole.DisplayRole))
            with myqtx.blockingSignals(self._code_editor):
                text = current.data(ModulesOperatorsTreeModel.SourceRole)
                self._code_editor.setPlainText(text)
                self._code_editor.setEnabled(True)
    
    @Slot()
    def _on_rows_removed(self, parent: QModelIndex, start: int, end: int):
        if not self._current.isValid():
            return

        current = self._selection_model.currentIndex()
        if not current.isValid():
            return
        
        if current.parent() == parent and start <= current.row() <= end:
            self._title_label.setText("<No Selection>")
            with myqtx.blockingSignals(self._code_editor):
                self._code_editor.clear()
                self._code_editor.setEnabled(False)


class PyFlow5Window(QMainWindow):
    def __init__(self, parent=None)->None:
        super().__init__(parent)
        self.setWindowTitle("PyFlow5")

        # setup Model
        self._document = PyFlowDocument()

        # Setup UI
        # self.setupActions()

        # - Setup modules view -
        self._module_list_view = QListView(self)
        self._module_list_view.setModel(self._document.modulesmodel)
        self._module_list_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        module_selection_model = QItemSelectionModel(self._document.modulesmodel)
        self._module_list_view.setSelectionModel(module_selection_model)

        # - Setup modules details view -
        self._module_details_view = ModuleDetailsView(self)
        self._module_details_view.setModel(self._document.modulesmodel)
        self._module_details_view.setSelectionModel(module_selection_model)

        # - Setup graphview -
        self._graph_view = DirectionalGraphView5(self)
        self._graph_view.setModel(self._document.graphmodel)
        self._graph_view.setSelectionModel(self._document.graphselectionmodel)
        self._graph_view.layout_nodes()
        self._graph_view.fitNodes()

        @Slot()
        def _on_request_node(scene_pos:QPointF, source:NodeName):
            # show a dialog with a multiselection of operator in GraphRT
            self.openOperatorDialog(scene_pos=scene_pos, source=source)
        self._graph_view.requestNode.connect(_on_request_node)

        @Slot()
        def _on_request_link(source:NodeName, outlet:OutletName, target:NodeName, inlet:InletName):
            self._document.graphmodel.addLink(source, outlet, target, inlet)
        self._graph_view.requestLink.connect(_on_request_link)

        # - Setup node inspector -
        self._inspector_view = InspectorView(self)
        self._inspector_view.setModel(self._document.graphdetailsmodel)
        # self._inspector_view.setSelectionModel(self._document.graphselectionmodel)

        # - Setup display widget -
        viewer = QWidget(self)
        viewer_layout = QVBoxLayout(viewer)
        viewer_layout.setContentsMargins(0, 0, 0, 0)
        viewer_header = QHBoxLayout()
        viewer_header.addWidget(QLabel("Viewer", viewer))
        viewer_header.addStretch()
        self._viewer_lock_switch = QCheckBox("Lock", viewer)
        self._viewer_lock_switch.setToolTip("Keep viewing this output when the selection changes.")
        self._viewer_lock_switch.setChecked(self._document.isOutputLocked())
        self._viewer_lock_switch.toggled.connect(self._document.setOutputLocked)
        self._document.output_lock_changed.connect(self._viewer_lock_switch.setChecked)
        viewer_header.addWidget(self._viewer_lock_switch)
        viewer_layout.addLayout(viewer_header)
        self._display_widget = myqtx.DisplayWidget(viewer)
        viewer_layout.addWidget(self._display_widget)

        @Slot()
        def _on_output_value_changed():
            # update display widget
            self._display_widget.display(self._document.output_value())
        self._document.output_value_changed.connect(_on_output_value_changed)

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
        splitter.addWidget(self._module_list_view)
        splitter.addWidget(self._module_details_view)
        splitter.addWidget(self._graph_view)
        splitter.addWidget(self._inspector_view)
        splitter.addWidget(viewer)
        splitter.setSizes([100, 350, 400, 260, 350])
        self.resize(1460, 600)


        self.setCentralWidget(splitter)

        self._graph_view.setFocus()

        # - Initial results update -
        self._document._execute()

    def setupMenubar(self):
        menubar: QMenuBar = self.menuBar()
        menubar.addAction("Restart Graph", self._document.reset_graph)

        file_menu = QMenu("File", self)
        menubar.addMenu(file_menu)
        file_menu.addAction("New",     lambda: None)
        file_menu.addAction("Open Graph",    lambda: self.openGraph())
        file_menu.addAction("Save Graph",    lambda: self.saveGraph())
        file_menu.addAction("Save Graph As", lambda: None)
        file_menu.addSeparator()
        file_menu.addAction("Import Module", lambda: self.importModule()).setShortcut("Ctrl+I")

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
        self._module_list_view.setCurrentIndex(model.index(0, 0))
        self._code_editor.setFocus()

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

        dialog = SelectionDialog(self._document.modulesmodel, self)
        try:
            if dialog.exec() == QDialog.DialogCode.Accepted:
                selected_index = dialog.selected_index()
                selected_op = selected_index.data(ModulesOperatorsTreeModel.OperatorRole)
                if selected_op:
                    self._document.graphmodel.addNode(selected_op, scene_pos)
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
                self._document.open(path)
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
