from typing import Sequence

from qtpy.QtCore import QEvent, QModelIndex, QPoint, QRegularExpression, Qt, QStringListModel, QSortFilterProxyModel
from qtpy.QtWidgets import QApplication, QDialog, QLabel, QLineEdit, QListView, QVBoxLayout, QWidget


DEFAULT_WIDTH = 400
DEFAULT_OFFSET = QPoint(0, 50)
DEFAULT_MAX_VISIBLE_ROWS = 8


class InputCommandDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.CustomizeWindowHint
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.setWindowTitle("Command Palette")
        self.setModal(True)

        self._editable = True
        self._max_visible_rows = DEFAULT_MAX_VISIBLE_ROWS
        self._result_index = QModelIndex()

        self.filter_edit = QLineEdit(self)
        self.filter_edit.setPlaceholderText("Filter commands...")
        self.filter_edit.textChanged.connect(self._apply_filter)
        self.filter_edit.returnPressed.connect(self._accept_current)
        self.filter_edit.installEventFilter(self)

        self.commands_list = QListView(self)
        self.commands_list.setUniformItemSizes(True)
        self.commands_list.activated.connect(self._accept_index)
        self.commands_list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self.filter_edit)
        layout.addWidget(self.commands_list)

        self._source_model = QStringListModel(self)
        self._proxy_model = QSortFilterProxyModel(self)
        self._proxy_model.setSourceModel(self._source_model)
        self._proxy_model.setFilterKeyColumn(0)
        self._proxy_model.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.commands_list.setModel(self._proxy_model)
        self._update_list_height()

    @classmethod
    def getCommand(
        cls,
        parent: QWidget,
        title: str,
        commands: Sequence[str],
        pos: QPoint | None = None,
        editable: bool = True,
    ) -> tuple[str, bool]:
        dialog = cls(parent)
        dialog.setCommands(commands)
        dialog.setEditable(editable)
        dialog.filter_edit.selectAll()
        dialog.filter_edit.setFocus(Qt.PopupFocusReason)
        dialog.setWindowTitle(title)
        dialog.setFixedWidth(DEFAULT_WIDTH)
        dialog.adjustSize()

        if pos is None:
            pos = parent.mapToGlobal(parent.rect().center())

        offset = QPoint(-(dialog.rect().width() // 2), DEFAULT_OFFSET.y())
        dialog.move(pos + offset)

        if dialog.exec() == QDialog.Accepted:
            return dialog.value(), True
        return "", False

    def setEditable(self, editable: bool) -> None:
        self._editable = editable

    def isEditable(self) -> bool:
        return self._editable

    def value(self) -> str:
        if self._result_index.isValid():
            return self._source_model.data(self._result_index, Qt.DisplayRole)
        return self.filter_edit.text()

    def setCommands(self, commands: Sequence[str]) -> None:
        self._source_model.setStringList(list(commands))
        self._result_index = QModelIndex()
        self._apply_filter(self.filter_edit.text())

    def _apply_filter(self, text: str) -> None:
        expression = QRegularExpression(QRegularExpression.escape(text), QRegularExpression.CaseInsensitiveOption)
        self._proxy_model.setFilterRegularExpression(expression)
        self._select_first()

    def _select_first(self) -> None:
        if self._proxy_model.rowCount() > 0:
            self.commands_list.setCurrentIndex(self._proxy_model.index(0, 0))
        else:
            self.commands_list.setCurrentIndex(QModelIndex())
        self._update_list_height()

    def _update_list_height(self) -> None:
        row_count = self._proxy_model.rowCount()
        has_rows = row_count > 0
        self.commands_list.setVisible(has_rows)

        frame = self.commands_list.frameWidth() * 2
        visible_rows = min(row_count, self._max_visible_rows)
        row_height = self.commands_list.sizeHintForRow(0)
        if row_height <= 0:
            row_height = self.filter_edit.sizeHint().height()
        height = frame + (visible_rows * row_height)

        if row_count > self._max_visible_rows:
            scrollbar_policy = Qt.ScrollBarAsNeeded
        else:
            scrollbar_policy = Qt.ScrollBarAlwaysOff
        self.commands_list.setVerticalScrollBarPolicy(scrollbar_policy)
        self.commands_list.setFixedHeight(height)
        self.adjustSize()

    def _accept_current(self) -> None:
        index = self.commands_list.currentIndex()
        if index.isValid():
            self._accept_index(index)
            return

        if self._editable:
            self._result_index = QModelIndex()
            self.accept()
        else:
            self.filter_edit.setFocus(Qt.OtherFocusReason)
            self.filter_edit.selectAll()

    def _accept_index(self, index: QModelIndex) -> None:
        source_index = self._proxy_model.mapToSource(index)
        self._result_index = source_index
        self.filter_edit.setText(self._source_model.data(source_index, Qt.DisplayRole))
        self.accept()

    def keyPressEvent(self, event: QEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(event)

    def eventFilter(self, obj, event) -> bool:
        if obj is self.filter_edit and event.type() == QEvent.Type.KeyPress:
            if event.key() in (
                Qt.Key.Key_Down,
                Qt.Key.Key_Up,
                Qt.Key.Key_PageDown,
                Qt.Key.Key_PageUp,
            ):
                self.moveSelection(event.key())
                return True
        return super().eventFilter(obj, event)

    def moveSelection(self, key: int) -> None:
        row_count = self._proxy_model.rowCount()
        if row_count <= 0:
            return
        current = self.commands_list.currentIndex()
        current_row = current.row() if current.isValid() else 0
        step = 1
        if key == Qt.Key.Key_PageDown:
            step = 5
        elif key == Qt.Key.Key_PageUp:
            step = -5
        elif key == Qt.Key.Key_Down:
            step = 1
        elif key == Qt.Key.Key_Up:
            step = -1

        if self._editable:
            next_row = max(-1, min(row_count - 1, current_row + step))
        else:
            next_row = max(0, min(row_count - 1, current_row + step))
        self.commands_list.setCurrentIndex(self._proxy_model.index(next_row, 0))


if __name__ == "__main__":
    import sys

    class DemoWindow(QWidget):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle("InputCommandDialog Demo")

            layout = QVBoxLayout(self)
            label = QLabel("Press Ctrl+P to open the input dialog")
            label.setAlignment(Qt.AlignCenter)
            layout.addWidget(label)
            
        def keyPressEvent(self, event) -> None:
            if event.key() == Qt.Key.Key_P and event.modifiers() & Qt.ControlModifier:
                command, ok = InputCommandDialog.getCommand(
                    parent=self,
                    title="Select Command",
                    commands=["Open File", "Save File", "Exit"],
                    editable=True,
                )
                if ok:
                    print(f"Your command is: {command}")
                return
            super().keyPressEvent(event)


    app = QApplication(sys.argv)
    window = DemoWindow()
    window.show()
    sys.exit(app.exec())
