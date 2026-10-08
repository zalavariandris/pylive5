
from qtpy.QtCore import (
    Qt,
    QModelIndex,
    QPersistentModelIndex,
    QAbstractTableModel,
)
from qtpy.QtWidgets import (
    QApplication,
    QWidget,
    QFormLayout,
    QDataWidgetMapper,
    QStyledItemDelegate,
    QLineEdit,
    QSpinBox,
    QDoubleSpinBox,
    QCheckBox,
    QStyleOptionViewItem,
)


class FormDelegate(QStyledItemDelegate):
    def createEditor(self, parent, option, index):
        value = index.data(Qt.ItemDataRole.EditRole)

        if isinstance(value, bool):
            return QCheckBox(parent)

        elif isinstance(value, int):
            editor = QSpinBox(parent)
            editor.setRange(-1_000_000, 1_000_000)
            return editor

        elif isinstance(value, float):
            editor = QDoubleSpinBox(parent)
            editor.setRange(-1_000_000, 1_000_000)
            return editor
        else:
            lineedit = QLineEdit(parent)
            lineedit.setText(str(value))
            lineedit.textChanged.connect(
                lambda _: self.commitData.emit(lineedit)
            )
            return lineedit


class FormView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._model = None
        self._root_index = QPersistentModelIndex()
        self._editors = []

        self._layout = QFormLayout(self)

        self._delegate = FormDelegate(self)

        self._mapper = QDataWidgetMapper(self)
        self._mapper.setOrientation(Qt.Orientation.Vertical)
        self._mapper.setItemDelegate(self._delegate)
        self._mapper.setSubmitPolicy(
            QDataWidgetMapper.SubmitPolicy.AutoSubmit
        )

    def model(self):
        return self._model

    def setModel(self, model):
        if model is self._model:
            return

        self._disconnect_model()
        self._clear()

        self._model = model
        self._root_index = QPersistentModelIndex()

        self._mapper.setModel(model)
        self._mapper.setRootIndex(QModelIndex())

        if model is not None:
            self._connect_model()

        self._rebuild()

    def rootIndex(self):
        return QModelIndex(self._root_index)

    def setRootIndex(self, index):
        if index.isValid() and index.model() is not self._model:
            raise ValueError("Index belongs to another model")

        if index == self.rootIndex():
            return

        self._root_index = QPersistentModelIndex(index)
        self._mapper.setRootIndex(index)

        self._rebuild()

    def itemDelegate(self):
        return self._delegate

    def setItemDelegate(self, delegate):
        if delegate is None:
            raise ValueError("Delegate cannot be None")

        if delegate is self._delegate:
            return

        self._delegate = delegate
        self._mapper.setItemDelegate(delegate)
        self._rebuild()

    def _connect_model(self):
        model = self._model

        model.dataChanged.connect(self._on_data_changed)
        model.rowsInserted.connect(self._on_rows_inserted)
        model.rowsRemoved.connect(self._on_rows_removed)
        model.rowsMoved.connect(self._on_rows_moved)
        model.layoutChanged.connect(self._on_layout_changed)
        model.modelAboutToBeReset.connect(self._on_model_about_to_reset)
        model.modelReset.connect(self._on_model_reset)

    def _disconnect_model(self):
        if self._model is None:
            return

        for signal, slot in (
            (self._model.dataChanged, self._on_data_changed),
            (self._model.rowsInserted, self._on_rows_inserted),
            (self._model.rowsRemoved, self._on_rows_removed),
            (self._model.rowsMoved, self._on_rows_moved),
            (self._model.layoutChanged, self._on_layout_changed),
            (self._model.modelAboutToBeReset, self._on_model_about_to_reset),
            (self._model.modelReset, self._on_model_reset),
        ):
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass

    def _clear(self):
        self._mapper.clearMapping()

        while self._layout.rowCount():
            self._layout.removeRow(0)

        self._editors.clear()

    def _rebuild(self, *args):
        self._clear()

        if self._model is None:
            return

        root = self.rootIndex()

        for row in range(self._model.rowCount(root)):
            self._insert_row(row)

        self._update_mappings()

    def _insert_row(self, row):
        model = self._model
        root = self.rootIndex()

        label_index = model.index(row, 0, root)
        value_index = model.index(row, 1, root)

        label = label_index.data(
            Qt.ItemDataRole.DisplayRole
        )

        option = QStyleOptionViewItem()

        editor = self._delegate.createEditor(
            self,
            option,
            value_index
        )

        if editor is None:
            editor = QLineEdit(self)

        self._layout.insertRow(
            row,
            "" if label is None else str(label),
            editor
        )

        self._editors.insert(row, editor)

    def _remove_row(self, row):
        self._layout.removeRow(row)
        self._editors.pop(row)

    def _update_mappings(self):
        self._mapper.clearMapping()

        if self._model is None:
            return

        root = self.rootIndex()

        if self._model.columnCount(root) < 2:
            return

        for row, editor in enumerate(self._editors):
            self._mapper.addMapping(editor, row)

        self._mapper.setCurrentIndex(1)

    def _on_data_changed(self, top_left, bottom_right, roles):
        if top_left.parent() != self.rootIndex():
            return

        if roles and not any(
            role in roles
            for role in (
                Qt.ItemDataRole.DisplayRole,
                Qt.ItemDataRole.EditRole,
            )
        ):
            return

        if top_left.column() <= 0 <= bottom_right.column():
            for row in range(
                top_left.row(),
                bottom_right.row() + 1
            ):
                index = self._model.index(
                    row, 0, self.rootIndex()
                )

                label = index.data(
                    Qt.ItemDataRole.DisplayRole
                )

                label_widget = self._layout.labelForField(
                    self._editors[row]
                )

                if label_widget is not None:
                    label_widget.setText(
                        "" if label is None else str(label)
                    )

        # QDataWidgetMapper updates the value editors.

    def _on_rows_inserted(self, parent, first, last):
        if parent != self.rootIndex():
            return

        for row in range(first, last + 1):
            self._insert_row(row)

        self._update_mappings()

    def _on_rows_removed(self, parent, first, last):
        if parent != self.rootIndex():
            return

        for row in range(last, first - 1, -1):
            self._remove_row(row)

        self._update_mappings()

    def _on_rows_moved(self, *args):
        self._rebuild()

    def _on_layout_changed(self, *args):
        self._rebuild()

    def _on_model_about_to_reset(self):
        self._clear()
        self._root_index = QPersistentModelIndex()

    def _on_model_reset(self):
        self._mapper.setRootIndex(QModelIndex())
        self._rebuild()


class ExampleModel(QAbstractTableModel):

    def __init__(self):
        super().__init__()

        self._items = [
            ["Name", "Alice"],
            ["Age", 30],
            ["Height", 1.75],
            ["Active", True],
            ["City", "Budapest"],
        ]

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._items)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else 2

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None

        if role in (
            Qt.ItemDataRole.DisplayRole,
            Qt.ItemDataRole.EditRole,
        ):
            return self._items[index.row()][index.column()]

        return None

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if not index.isValid():
            return False

        if role != Qt.ItemDataRole.EditRole:
            return False

        self._items[index.row()][index.column()] = value

        self.dataChanged.emit(
            index,
            index,
            [
                Qt.ItemDataRole.DisplayRole,
                Qt.ItemDataRole.EditRole,
            ]
        )

        return True

    def flags(self, index):
        flags = super().flags(index)

        if index.isValid() and index.column() == 1:
            flags |= Qt.ItemFlag.ItemIsEditable

        return flags


if __name__ == "__main__":
    app = QApplication([])

    model = ExampleModel()

    form = FormView()
    form.setModel(model)

    form.setWindowTitle("Model Form")
    form.resize(360, 240)
    form.show()

    app.exec()
