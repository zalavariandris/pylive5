

from qtpy.QtCore import QAbstractItemModel, QModelIndex

from qtpy.QtCore import (
    Qt,
    Signal,
    Slot
)

from qtpy.QtWidgets import (
    QLabel,
    QVBoxLayout, 
    QWidget
)

import myqtx
from QtScriptEditorAdvanced.script_edit_advanced import ScriptEditAdvanced

from .modules_operator_tree_model import ModulesOperatorsTreeModel


class ModuleDetailsView(QWidget):
    # todo: consider refactoring this class using a QDataWidgetMapper, 
    # or we could also create an AbstractDetailsView base class
    def __init__(self, parent:QWidget|None=None):
        super().__init__(parent=parent)
        
        self._model:QAbstractItemModel|None = None
        self._model_connections: list[tuple[Signal, Slot]] = []

        self._current_index: QModelIndex = QModelIndex()

        # self._code_editor = ScriptEdit2(self)
        self._title_label = QLabel(self)
        self._code_editor = ScriptEditAdvanced(
            completer=None,
            parent=self
        )
        @self._code_editor.textChanged.connect
        def _on_editor_text_changed():
            if not self._current_index.isValid():
                return
    
            assert self._current_index.model() is self._model
    
            new_text = self._code_editor.toPlainText()
            self._model.setData(self._current_index, new_text, ModulesOperatorsTreeModel.SourceRole)

        layout = QVBoxLayout(self)
        layout.addWidget(self._title_label)
        layout.addWidget(self._code_editor)
        self.setLayout(layout)

        self._update_display()

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
        self.setCurrentIndex(QModelIndex())

    @Slot()
    def _on_model_reset(self):
        if not self._current_index.isValid():
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
        if not self._current_index.isValid():
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
        if not self._current_index.isValid():
            return

        current = self._selection_model.currentIndex()
        if not current.isValid():
            return
        
        if current.parent() == parent and start <= current.row() <= end:
            self._title_label.setText("<No Selection>")
            with myqtx.blockingSignals(self._code_editor):
                self._code_editor.clear()
                self._code_editor.setEnabled(False)

    
    def setCurrentIndex(self, index: QModelIndex):
        if index == self._current_index:
            return
        
        if index.model() != self._model:
            return
        
        self._current_index = index
        self._update_display()

    def _update_display(self):
        if not self._current_index.isValid():
            self._title_label.setText("<No Selection>")
            with myqtx.blockingSignals(self._code_editor):
                self._code_editor.clear()
                self._code_editor.setEnabled(False)
            return

        self._title_label.setText(self._current_index.data(Qt.ItemDataRole.DisplayRole))
        with myqtx.blockingSignals(self._code_editor):
            text = self._current_index.data(ModulesOperatorsTreeModel.SourceRole)
            self._code_editor.setPlainText(text)
            self._code_editor.setEnabled(True)

    def currentIndex(self) -> QModelIndex:
        return self._current_index

