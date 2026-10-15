
from qtpy.QtCore import (
    Qt,
    QModelIndex,
    QPersistentModelIndex,
    QAbstractTableModel,
)
from qtpy.QtWidgets import (
    QApplication,
    QLabel,
    QVBoxLayout,
    QWidget,
    QFormLayout,
    QDataWidgetMapper,
    QStyledItemDelegate,
    QLineEdit,
    QStyleOptionViewItem,
)

from enum import IntEnum


class FormViewRole(IntEnum):
    LabelRole = Qt.ItemDataRole.UserRole + 1
    FieldRole = Qt.ItemDataRole.UserRole + 2

class _FormFieldDelegate(QStyledItemDelegate):
    """Create editors whose size is controlled by the form layout.
    note: Use a plain QLineEdit for strings to avoid Qt's default string editor
          resizing itself when its text changes. 
    """
    def createEditor(
        self,
        parent: QWidget | None,
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> QWidget | None:
        if isinstance(index.data(Qt.ItemDataRole.EditRole), str):
            return QLineEdit(parent)

        return super().createEditor(parent, option, index)

class FormView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._model = None
        self._root_index = QPersistentModelIndex()
        self._root_removed = False
        self._editors = []

        self._layout = QFormLayout(self)
        self._layout.setLabelAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )

        self._field_delegate = _FormFieldDelegate(self)
        self._label_delegate = None
        self._mapper = QDataWidgetMapper(self)
        self._mapper.setOrientation(Qt.Orientation.Vertical)
        self._mapper.setItemDelegate(self._field_delegate)
        self._mapper.setSubmitPolicy(
            QDataWidgetMapper.SubmitPolicy.AutoSubmit
        )

    def model(self):
        return self._model

    def setModel(self, model: QAbstractTableModel | None):
        if model is self._model:
            return

        self._disconnect_model()
        self._clear()

        self._model = model
        self._root_index = QPersistentModelIndex()
        self._root_removed = False

        self._mapper.setModel(model)
        self._mapper.setRootIndex(QModelIndex())

        if model is not None:
            self._connect_model()

        self._rebuild()

    def rootIndex(self):
        return QModelIndex(self._root_index)

    def setRootIndex(self, index: QModelIndex):
        if index.isValid() and index.model() is not self._model:
            raise ValueError("Index belongs to another model")

        if index == self.rootIndex() and not self._root_removed:
            return

        self._root_removed = False
        self._root_index = QPersistentModelIndex(index)
        self._mapper.setRootIndex(index)

        self._rebuild()

    def itemDelegate(self):
        return self._field_delegate

    def setFieldDelegate(self, delegate: QStyledItemDelegate):
        if delegate is None:
            raise ValueError("Delegate cannot be None")

        if delegate is self._field_delegate:
            return

        self._field_delegate = delegate
        self._mapper.setItemDelegate(delegate)
        
        self._rebuild()

    def setLabelDelegate(self, delegate: QStyledItemDelegate|None):
        if delegate is self._label_delegate:
            return

        self._label_delegate = delegate
        self._rebuild()

    def _connect_model(self):
        model = self._model
        assert model is not None
        model.dataChanged.connect(self._on_data_changed)
        model.rowsInserted.connect(self._on_rows_inserted)
        model.rowsAboutToBeRemoved.connect(self._on_rows_about_to_be_removed)
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
            (
                self._model.rowsAboutToBeRemoved,
                self._on_rows_about_to_be_removed,
            ),
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

        if self._model is None or self._root_removed:
            return

        root = self.rootIndex()

        for row in range(self._model.rowCount(root)):
            self._insert_row(row)

        self._update_mappings()

    def _insert_row(self, row):
        model = self._model
        assert model is not None
        root = self.rootIndex()

        # todo: setup style option for each item
        labelstyle_option = QStyleOptionViewItem()
        labelstyle_option.initFrom(self)

        label_index = model.index(row, 0, root)
        value_index = model.index(row, 1, root)

        label_text = label_index.data(Qt.ItemDataRole.DisplayRole)
        if self._label_delegate is not None:
            label_widget = self._label_delegate.createEditor(
                self,
                labelstyle_option,
                label_index
            )
        else:
            label_widget = QLabel("" if label_text is None else str(label_text), self)
            
        editor_style_option = QStyleOptionViewItem()
        editor_style_option.initFrom(self)

        editor = self._field_delegate.createEditor(
            self,
            editor_style_option,
            value_index
        )

        if editor is None:
            editor = QLineEdit(self)

        self._layout.insertRow(
            row,
            label_widget, # "" if label_text is None else str(label_text),
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

    def _on_data_changed(self, top_left:QModelIndex, bottom_right:QModelIndex, roles: list[int] | None):
        if not self._shows(top_left.parent()):
            return

        if roles and not any(
            role in roles
            for role in (
                Qt.ItemDataRole.DisplayRole,
                Qt.ItemDataRole.EditRole,
            )
        ):
            return

        for col in range(top_left.column(), bottom_right.column() + 1):
            for row in range(top_left.row(), bottom_right.row() + 1):
                match col:
                    case 0:
                        # update label
                        label_text = self._model.index(row, 0, self.rootIndex()).data(
                            Qt.ItemDataRole.DisplayRole
                        )

                        label_widget = self._layout.labelForField(
                            self._editors[row]
                        )

                        if label_widget is not None:
                            prop = label_widget.metaObject().userProperty()
                            prop.write(label_widget, label_text)
                    case 1:
                        pass

                    case _:
                        # ignore other columns
                        pass

    def _shows(self, parent: QModelIndex) -> bool:
        # An invalid root is ambiguous: top level, or a root that was deleted.
        return not self._root_removed and parent == self.rootIndex()

    def _on_rows_inserted(self, parent, first, last):
        if not self._shows(parent):
            return

        for row in range(first, last + 1):
            self._insert_row(row)

        self._update_mappings()

    def _on_rows_about_to_be_removed(
        self, parent: QModelIndex, first: int, last: int
    ) -> None:
        if self._root_removed or not self._root_index.isValid():
            return

        # The root dies if it, or any ancestor, is in the removed range.
        index = self.rootIndex()
        while index.isValid():
            if index.parent() == parent and first <= index.row() <= last:
                self._root_removed = True
                self._clear()
                return
            index = index.parent()

    def _on_rows_removed(self, parent, first, last):
        if not self._shows(parent):
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
        self._root_removed = False

    def _on_model_reset(self):
        self._mapper.setRootIndex(QModelIndex())
        self._rebuild()



if __name__ == "__main__":
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

    app = QApplication([])

    model = ExampleModel()

    form1 = FormView()
    form1.setModel(model)
    form2 = FormView()
    form2.setModel(model)

    window = QWidget()
    layout = QVBoxLayout(window)
    layout.addWidget(form1)
    layout.addWidget(form2)
    window.setWindowTitle("Model Form")
    window.resize(360, 480)
    window.show()

    app.exec()
