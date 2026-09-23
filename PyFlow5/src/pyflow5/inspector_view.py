"""A flat inspector using real widgets, with one editor per property."""
from dataclasses import dataclass
from typing import Any, Callable

from qtpy.QtCore import QAbstractItemModel, QModelIndex, QPersistentModelIndex, Qt
from qtpy.QtWidgets import (
    QCheckBox, QLabel, QLineEdit, QScrollArea, QVBoxLayout, QWidget,
)

from .inspector_roles import InspectorRole, UNSET


@dataclass
class InspectorEditor:
    """Adapter returned by an editor factory(index, parent).

    Complex editors read/write one complete value. committed should fire when
    the user finishes an edit; it may carry arguments, which the view ignores.
    """
    widget: QWidget
    read: Callable[[], Any]
    write: Callable[[Any], None]
    committed: Any = None

def _text_editor(value_type):
    def create(index, parent):
        widget = QLineEdit(parent)
        return InspectorEditor(
            widget, lambda: value_type(widget.text()),
            lambda value: widget.setText(str(value)), widget.editingFinished,
        )
    return create

def _bool_editor(index, parent):
    widget = QCheckBox(parent)
    return InspectorEditor(widget, widget.isChecked, widget.setChecked, widget.clicked)

def _display_editor(index, parent):
    widget = QLabel(parent)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(True)
    widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return InspectorEditor(widget, lambda: None, lambda value: widget.setText(str(value)))


class _PropertyRow(QWidget):
    def __init__(self, view, index):
        super().__init__(view._contents)
        self.view = view
        self.index = QPersistentModelIndex(index)
        self.editor = None
        self.factory = None
        self._refreshing = False
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(3)
        self.label = QLabel(self)
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.message = QLabel(self)
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.message.setWordWrap(True)
        self._layout.addWidget(self.label)
        self._layout.addWidget(self.message)
        self.refresh()

    def refresh(self):
        if not self.index.isValid():
            return
        index = QModelIndex(self.index)
        value = index.data(Qt.ItemDataRole.EditRole)
        binding = index.data(InspectorRole.BindingRole)
        annotation = index.data(InspectorRole.TypeRole)
        type_name = getattr(annotation, "__name__", str(annotation)) if annotation is not None else ""
        name = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        self.label.setText(f"{name} ({type_name})" if type_name else name)
        self.label.setToolTip(index.data(Qt.ItemDataRole.ToolTipRole) or "")

        factory = self.view._factory(index, value)
        if binding == "connection":
            connection = index.data(InspectorRole.ConnectionRole)
            value = ".".join(map(str, connection)) if connection else "Unavailable connection"
            factory = _display_editor
        elif value is UNSET:
            value, factory = "Not set", _display_editor
        elif factory is _display_editor:
            value = repr(value)

        self._refreshing = True
        try:
            if self.editor is None or self.factory is not factory:
                if self.editor is not None:
                    if self.editor.committed is not None:
                        self.editor.committed.disconnect(self.commit)
                    self._layout.removeWidget(self.editor.widget)
                    self.editor.widget.hide()
                    self.editor.widget.deleteLater()
                self.factory = factory
                self.editor = factory(index, self)
                self._layout.insertWidget(1, self.editor.widget)
                if self.editor.committed is not None:
                    self.editor.committed.connect(self.commit)
            self.editor.write(value)
            editable = bool(index.flags() & Qt.ItemFlag.ItemIsEditable)
            editable = editable and binding != "connection" and self.editor.committed is not None
            if isinstance(self.editor.widget, QLineEdit):
                self.editor.widget.setReadOnly(not editable)
            else:
                self.editor.widget.setEnabled(editable or self.editor.committed is None)
            error = index.data(InspectorRole.ErrorRole)
            self.message.setText(error or {
                "default": "Default", "connection": "Connected", "missing": "Required",
            }.get(binding, ""))
            self.message.setVisible(bool(self.message.text()))
        finally:
            self._refreshing = False

    def commit(self, *args):
        if self._refreshing or not self.index.isValid():
            return
        index = QModelIndex(self.index)
        model = self.view.model()
        if index.model() is not model or not index.flags() & Qt.ItemFlag.ItemIsEditable:
            return
        if index.data(InspectorRole.BindingRole) == "connection":
            return
        try:
            value = self.editor.read()
            accepted = model.setData(index, value, Qt.ItemDataRole.EditRole)
        except (ValueError, TypeError) as error:
            self.message.setText(str(error))
            self.message.show()
            return
        if not accepted:
            self.message.setText(index.data(InspectorRole.ErrorRole) or "Value was not accepted.")
            self.message.show()
        else:
            self.refresh()


class InspectorView(QScrollArea):
    """Render a flat item model with registered editor widgets.

    registerEditor(type_or_hint, factory) also accepts an explicit editor hint
    supplied by EditorHintsRole["editor"]. Unknown types use a read-only preview.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self._model: QAbstractItemModel | None = None
        self._connections = []
        self._seleciton_model = None
        self._selection_connections = []


        self._rows = []
        self._editors = {
            str: _text_editor(str), int: _text_editor(int),
            float: _text_editor(float), bool: _bool_editor,
        }
        self._contents = QWidget(self)
        self._layout = QVBoxLayout(self._contents)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._title = QLabel(self._contents)
        self._title.setTextFormat(Qt.TextFormat.PlainText)
        font = self._title.font()
        font.setBold(True)
        self._title.setFont(font)
        self._description = QLabel(self._contents)
        self._description.setTextFormat(Qt.TextFormat.PlainText)
        self._description.setWordWrap(True)
        self._empty = QLabel("No inputs to inspect.", self._contents)
        self._layout.addWidget(self._title)
        self._layout.addWidget(self._description)
        self._layout.addWidget(self._empty)
        self.setWidget(self._contents)
        self.setWidgetResizable(True)
        self.setMinimumWidth(230)
        self._update_header()

    def model(self):
        return self._model

    def setModel(self, model: QAbstractItemModel):
        if model is self._model:
            return
        for signal, slot in self._connections:
            signal.disconnect(slot)
        self._connections = []
        self._model = model
        if model is not None:
            self._connections = [
                (model.modelReset, self._rebuild),
                (model.rowsInserted, self._rebuild),
                (model.rowsRemoved, self._rebuild),
                (model.rowsMoved, self._rebuild),
                (model.layoutChanged, self._rebuild),
                (model.dataChanged, self._data_changed),
                (model.headerDataChanged, self._update_header),
                (model.destroyed, self._model_destroyed),
            ]
            for signal, slot in self._connections:
                signal.connect(slot)
        self._rebuild()

    def registerEditor(self, value_type, factory:Callable):
        self._editors[value_type] = factory
        for row in self._rows:
            row.refresh()

    def _factory(self, index, value):
        hints = index.data(InspectorRole.EditorHintsRole) or {}
        annotation = index.data(InspectorRole.TypeRole)
        # Builtin annotations may be strings when postponed annotations are used.
        if isinstance(annotation, str):
            annotation = {"str": str, "int": int, "float": float, "bool": bool}.get(annotation, annotation)
        # Existing literals may no longer match an edited function annotation.
        # Show the actual value rather than coercing it (e.g. None into False).
        if value is None:
            return self._editors.get(type(None), _display_editor)
        if isinstance(annotation, type) and not isinstance(value, annotation):
            annotation = type(value)
        for key in (hints.get("editor"), annotation, type(value)):
            try:
                if key in self._editors:
                    return self._editors[key]
            except TypeError:
                continue
        return _display_editor

    def _model_destroyed(self, *args):
        self._model = None
        self._connections = []
        self._rebuild()

    def _update_header(self, *args):
        title, description = "Inspector", ""
        if self._model is not None:
            title = self._model.headerData(0, Qt.Orientation.Horizontal) or title
            description = self._model.headerData(
                0, Qt.Orientation.Horizontal, Qt.ItemDataRole.ToolTipRole,
            ) or ""
        self._title.setText(str(title))
        self._description.setText(str(description))
        self._description.setVisible(bool(description))

    def _rebuild(self, *args):
        for row in self._rows:
            row.index = QPersistentModelIndex()
            self._layout.removeWidget(row)
            row.hide()
            row.deleteLater()
        self._rows = []
        if self._model is not None:
            for number in range(self._model.rowCount()):
                row = _PropertyRow(self, self._model.index(number, 0))
                self._rows.append(row)
                self._layout.addWidget(row)
        self._empty.setVisible(not self._rows)
        self._update_header()

    def _data_changed(self, top_left, bottom_right, roles=None):
        for number in range(top_left.row(), min(bottom_right.row() + 1, len(self._rows))):
            self._rows[number].refresh()
