from pygraphrt.script_module import ScriptOperatorRef
from qtpy.QtCore import (
    QAbstractItemModel,
    QItemSelectionModel,
    QModelIndex,
    QPersistentModelIndex,
    Qt,
    Signal,
    Slot,
)
from qtpy.QtWidgets import QLabel, QVBoxLayout, QWidget

import myqtx
from QtScriptEditorAdvanced.script_edit_advanced import ScriptEditAdvanced

from .modules_operator_tree_model import ModulesOperatorsTreeModel


class ModuleDetailsView(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model: ModulesOperatorsTreeModel | None = None
        self._model_connections: list[tuple[Signal, Slot]] = []
        self._selection_model: QItemSelectionModel | None = None
        self._selection_model_connections: list[tuple[Signal, Slot]] = []
        self._current_index = QPersistentModelIndex()

        self._title_label = QLabel(self)
        self._code_editor = ScriptEditAdvanced(completer=None, parent=self)
        self._code_editor.textChanged.connect(self._on_editor_text_changed)

        layout = QVBoxLayout(self)
        layout.addWidget(self._title_label)
        layout.addWidget(self._code_editor)
        self._update_display()

    def model(self) -> ModulesOperatorsTreeModel | None:
        return self._model

    def setModel(self, model: ModulesOperatorsTreeModel | None) -> None:
        if model is self._model:
            return
        self.setSelectionModel(None)
        for signal, slot in self._model_connections:
            signal.disconnect(slot)
        self._model_connections.clear()

        self._model = model
        if model is not None:
            self._model_connections = [
                (model.modelReset, self._on_model_reset),
                (model.dataChanged, self._on_data_changed),
                (model.rowsRemoved, self._on_rows_removed),
            ]
            for signal, slot in self._model_connections:
                signal.connect(slot)
        self.setCurrentIndex(QModelIndex())

    def selection(self) -> QItemSelectionModel | None:
        return self._selection_model

    def setSelectionModel(self, selection_model: QItemSelectionModel | None) -> None:
        if selection_model is not None and selection_model.model() is not self._model:
            raise ValueError("Selection model must belong to the details view's model.")
        for signal, slot in self._selection_model_connections:
            signal.disconnect(slot)
        self._selection_model_connections.clear()

        self._selection_model = selection_model
        if selection_model is not None:
            self._selection_model_connections = [
                (selection_model.selectionChanged, self._sync_selection),
                (selection_model.currentChanged, self._sync_selection),
            ]
            for signal, slot in self._selection_model_connections:
                signal.connect(slot)
        self._sync_selection()

    def goToOperator(self, index:QModelIndex) -> bool:
        if self._model is None:
            return False
        operator_ref = self._model.mapToSource(index)
        if isinstance(operator_ref, ScriptOperatorRef):
            lineno = operator_ref.get_line_number()
            self._code_editor.moveCursorToLine(lineno)
        else:
            return False
        
        return True

    def _sync_selection(self, *_args: object) -> None:
        selection = self._selection_model
        index = QModelIndex()
        if selection is not None:
            current = selection.currentIndex()
            selected = selection.selectedIndexes()
            if selection.isSelected(current):
                index = current
            elif selected:
                index = selected[0]
        self.setCurrentIndex(index)

    def _on_editor_text_changed(self) -> None:
        if self._model is None or not self._current_index.isValid():
            return
        if not self._code_editor.isEnabled():
            return
        self._model.setData(
            self.currentIndex(),
            self._code_editor.toPlainText(),
            ModulesOperatorsTreeModel.SourceRole,
        )

    def _on_model_reset(self) -> None:
        self.setCurrentIndex(QModelIndex())

    def _on_data_changed(
        self, top_left: QModelIndex, bottom_right: QModelIndex, roles: list[int],
    ) -> None:
        current = self.currentIndex()
        if (
            current.isValid()
            and current.parent() == top_left.parent()
            and top_left.row() <= current.row() <= bottom_right.row()
            and top_left.column() <= current.column() <= bottom_right.column()
        ):
            self._update_display()

    def _on_rows_removed(self, parent: QModelIndex, start: int, end: int) -> None:
        self._update_display()

    def setCurrentIndex(self, index: QModelIndex) -> None:
        if index.isValid() and index.model() is not self._model:
            return
        changed = index != self.currentIndex()
        self._current_index = QPersistentModelIndex(index)
        self._update_display(reset_editor=changed)

    def currentIndex(self) -> QModelIndex:
        return QModelIndex(self._current_index)

    def _update_display(self, *, reset_editor: bool = False) -> None:
        current = self.currentIndex()
        title = current.data(Qt.ItemDataRole.DisplayRole) if current.isValid() else "<No Selection>"
        source = current.data(ModulesOperatorsTreeModel.SourceRole)
        self._title_label.setText(title or "")
        with myqtx.blockingSignals(self._code_editor):
            text = source if isinstance(source, str) else ""
            # Model notifications echo edits; replacing identical text loses undo and the cursor.
            if reset_editor or self._code_editor.toPlainText() != text:
                self._code_editor.setPlainText(text)
            self._code_editor.setEnabled(isinstance(source, str))
