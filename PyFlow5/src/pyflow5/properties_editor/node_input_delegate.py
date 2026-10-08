from typing import Any

from qtpy.QtCore import (
    QAbstractItemModel, QModelIndex, QObject, QPersistentModelIndex, Qt, Signal,
)
from qtpy.QtGui import QPalette
from qtpy.QtWidgets import (
    QHBoxLayout, QPushButton, QStyledItemDelegate, QStyleOptionViewItem, QWidget,
)

from myqtx.editorregistry import EditorRegistry
from myqtx.editors import Editor, EditorFactory, label_editor, read_only_editor
from pygraphrt.abstract_operator import ParameterData

from ..nodert_input_roles import NodeRTInputRole


class NodeInputWidget(QWidget):
    clearRequested = Signal()
    valueChanged = Signal()

    def __init__(
        self, datatype: type, factory: EditorFactory, parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setAutoFillBackground(True)
        self.setStyleSheet("""
            QWidget[usingDefault="true"], QWidget[usingDefault="true"] QWidget {
                color: palette(PlaceholderText);
                font-style: italic;
            }
        """)
        self.datatype = datatype
        self.factory = factory
        self.modified = False
        self._updating = False
        self.binding = self._create_binding(datatype, factory)
        self.editor = self.binding.widget
        if self.binding.changed is not None:
            self.binding.changed.connect(self._on_value_changed)

        self.clear_button = QPushButton("✖", self)
        self.clear_button.setToolTip("Clear input")
        self.clear_button.setStyleSheet("""
            QPushButton {
                background: transparent; border: none; padding: 0; margin: 0;
            }
            QPushButton:hover {
                color: palette(Highlight);
            }
        """)
        self.clear_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.clear_button.clicked.connect(self.clearRequested.emit)

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._layout.addWidget(self.editor, 1)
        self._layout.addWidget(self.clear_button)
        self.setFocusProxy(self.editor)

    def _create_binding(self, datatype: type, factory: EditorFactory) -> Editor[Any]:
        binding = factory(datatype, self)
        if not isinstance(binding, Editor) or not isinstance(binding.widget, QWidget):
            raise TypeError("Editor factories must return an Editor containing a QWidget")
        return binding

    def replace_editor(self, datatype: type, factory: EditorFactory) -> None:
        binding = self._create_binding(datatype, factory)
        if self.binding.changed is not None:
            self.binding.changed.disconnect(self._on_value_changed)
        previous = self.editor
        self._layout.replaceWidget(previous, binding.widget)
        previous.hide()
        previous.deleteLater()
        self.datatype = datatype
        self.factory = factory
        self.binding = binding
        self.editor = binding.widget
        if self.binding.changed is not None:
            self.binding.changed.connect(self._on_value_changed)
        self.setFocusProxy(self.editor)
        self.editor.show()

    def set_value(self, value: object, *, using_default: bool = False) -> None:
        self._updating = True
        try:
            if using_default and self.binding.set_default is not None:
                self.binding.set_default(value)
            else:
                self.binding.set_value(value)
            if self.editor.property("usingDefault") != using_default:
                self.editor.setProperty("usingDefault", using_default)
                for widget in [self.editor, *self.editor.findChildren(QWidget)]:
                    widget.style().unpolish(widget)
                    widget.style().polish(widget)
                    widget.update()
                self.editor.updateGeometry()
            self.modified = False
        finally:
            self._updating = False

    def _on_value_changed(self, *args: object) -> None:
        if not self._updating:
            self.modified = True
            self.valueChanged.emit()


class NodeInputDelegate(QStyledItemDelegate):
    def __init__(
        self, parent: QObject | None = None, *,
        editor_registry: EditorRegistry | None = None,
    ) -> None:
        super().__init__(parent)
        self.editor_registry = (
            editor_registry if editor_registry is not None else EditorRegistry()
        )

    def register_editor(self, datatype: type, factory: EditorFactory) -> None:
        """Register an editor in this delegate's registry."""
        self.editor_registry.register_editor(datatype, factory)

    def _editor_factory(self, index: QModelIndex) -> tuple[type, EditorFactory]:
        annotation = index.data(NodeRTInputRole.AnnotationRole)
        datatype = (
            annotation if isinstance(annotation, type)
            else type(index.data(Qt.ItemDataRole.EditRole))
        )
        if index.data(NodeRTInputRole.ConnectionRole) is not None:
            return datatype, label_editor
        factory = None
        if index.flags() & Qt.ItemFlag.ItemIsEditable:
            factory = self.editor_registry.factory_for(datatype)
        return datatype, factory if factory is not None else read_only_editor

    def createEditor(
        self,
        parent: QWidget | None,
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> QWidget:
        datatype, factory = self._editor_factory(index)
        wrapper = NodeInputWidget(datatype, factory, parent)
        wrapper.valueChanged.connect(lambda: self.commitData.emit(wrapper))
        persistent_index = QPersistentModelIndex(index)
        wrapper.clearRequested.connect(
            lambda: self._clear_input(wrapper, persistent_index)
        )
        return wrapper

    def setEditorData(self, editor: QWidget | None, index: QModelIndex) -> None:
        if editor is None:
            return
        if not isinstance(editor, NodeInputWidget):
            super().setEditorData(editor, index)
            return

        datatype, factory = self._editor_factory(index)
        if editor.datatype is not datatype or editor.factory is not factory:
            editor.replace_editor(datatype, factory)
        role = (
            Qt.ItemDataRole.DisplayRole
            if factory in (read_only_editor, label_editor) else Qt.ItemDataRole.EditRole
        )
        editor.set_value(
            index.data(role),
            using_default=bool(index.data(NodeRTInputRole.IsUsingDefaultRole)),
        )

    def setModelData(
        self, editor: QWidget, model: QAbstractItemModel, index: QModelIndex
    ) -> None:
        if not isinstance(editor, NodeInputWidget):
            super().setModelData(editor, model, index)
            return
        # Focus changes must not turn an untouched default into a stored input.
        if (
            not editor.modified
            or editor.factory in (read_only_editor, label_editor)
            or not index.flags() & Qt.ItemFlag.ItemIsEditable
        ):
            return
        editor.modified = False
        model.setData(index, editor.binding.get_value(), Qt.ItemDataRole.EditRole)

    def _clear_input(
        self, editor: NodeInputWidget, index: QPersistentModelIndex
    ) -> None:
        editor.modified = False
        self.closeEditor.emit(editor, QStyledItemDelegate.EndEditHint.NoHint)
        if index.isValid():
            index.model().setData(
                QModelIndex(index), ParameterData.EMPTY, Qt.ItemDataRole.EditRole
            )

    def initStyleOption(
        self, option: QStyleOptionViewItem | None, index: QModelIndex
    ) -> None:
        if option is None:
            return
        super().initStyleOption(option, index)

        if index.data(NodeRTInputRole.IsUsingDefaultRole):
            color = option.palette.color(
                QPalette.ColorGroup.Disabled,
                QPalette.ColorRole.Text,
            )
            option.font.setItalic(True)
            for group in (
                QPalette.ColorGroup.Active,
                QPalette.ColorGroup.Inactive,
            ):
                option.palette.setColor(group, QPalette.ColorRole.Text, color)
                option.palette.setColor(
                    group, QPalette.ColorRole.HighlightedText, color
                )
