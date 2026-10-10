from typing import Any, cast
from pathlib import Path

from qtpy.QtCore import (
    QAbstractItemModel, QEvent, QModelIndex, QObject, QPersistentModelIndex, Qt, Signal
)
from qtpy.QtCore import Property

from qtpy.QtGui import QPalette
from qtpy.QtWidgets import (
    QHBoxLayout, 
    QPushButton, 
    QStyledItemDelegate, 
    QStyleOptionViewItem, 
    QWidget
)

from qtpy.QtWidgets import (
    QLabel,
    QLineEdit, 
    QSpinBox, 
    QDoubleSpinBox
    )

from pyflow5.editorregistry import EditorContext, EditorProvider, EditorRegistry
from pyflow5.editors import Editor, EditorFactory, label_editor, read_only_editor
from pygraphrt.abstract_operator import ParameterData
from rich import style

from ..core.nodert_input_roles import NodeRTInputRole
from pyflow5.vfxops_editors import register_vfxops_editors

# class NodeInputWidget(QWidget):
#     clearRequested = Signal()
#     valueChanged = Signal()

#     def __init__(
#         self, datatype: object, factory: EditorFactory, parent: QWidget | None = None,
#     ) -> None:
#         super().__init__(parent)
#         self.setAutoFillBackground(True)
#         self.setStyleSheet("""
#             QWidget[usingDefault="true"], QWidget[usingDefault="true"] QWidget {
#                 color: palette(PlaceholderText);
#                 font-style: italic;
#             }
#         """)
#         self.datatype = datatype
#         self.factory = factory
#         self.modified = False
#         self._updating = False
#         self.binding = self._create_binding(datatype, factory)
#         self.editor = self.binding.widget
#         if self.binding.changed is not None:
#             self.binding.changed.connect(self._on_value_changed)

#         self.clear_button = QPushButton("✖", self)
#         self.clear_button.setToolTip("Clear input")
#         self.clear_button.setStyleSheet("""
#             QPushButton {
#                 background: transparent; border: none; padding: 0; margin: 0;
#             }
#             QPushButton:hover {
#                 color: palette(Highlight);
#             }
#         """)
#         self.clear_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
#         self.clear_button.clicked.connect(self.clearRequested.emit)

#         self._layout = QHBoxLayout(self)
#         self._layout.setContentsMargins(0, 0, 0, 0)
#         self._layout.setSpacing(0)
#         self._layout.addWidget(self.editor, 1)
#         self._layout.addWidget(self.clear_button)
#         self.setFocusProxy(self.editor)

#     def _create_binding(self, datatype: object, factory: EditorFactory) -> Editor[Any]:
#         binding = factory(datatype, self)
#         if not isinstance(binding, Editor) or not isinstance(binding.widget, QWidget):
#             raise TypeError("Editor factories must return an Editor containing a QWidget")
#         return binding

#     def replace_editor(self, datatype: object, factory: EditorFactory) -> None:
#         binding = self._create_binding(datatype, factory)
#         if self.binding.changed is not None:
#             self.binding.changed.disconnect(self._on_value_changed)
#         previous = self.editor
#         self._layout.replaceWidget(previous, binding.widget)
#         previous.hide()
#         previous.deleteLater()
#         self.datatype = datatype
#         self.factory = factory
#         self.binding = binding
#         self.editor = binding.widget
#         if self.binding.changed is not None:
#             self.binding.changed.connect(self._on_value_changed)
#         self.setFocusProxy(self.editor)
#         self.editor.show()

#     def set_value(self, value: object, *, using_default: bool = False) -> None:
#         self._updating = True
#         try:
#             if using_default and self.binding.set_default is not None:
#                 self.binding.set_default(value)
#             else:
#                 self.binding.set_value(value)
#             if self.editor.property("usingDefault") != using_default:
#                 self.editor.setProperty("usingDefault", using_default)
#                 for widget in [self.editor, *self.editor.findChildren(QWidget)]:
#                     widget.style().unpolish(widget)
#                     widget.style().polish(widget)
#                     widget.update()
#                 self.editor.updateGeometry()
#             self.modified = False
#         finally:
#             self._updating = False

#     def _on_value_changed(self, *args: object) -> None:
#         if not self._updating:
#             self.modified = True
#             self.valueChanged.emit()

# class MyLineEdit(QWidget):
#     valueChanged = Signal(str)
#     def __init__(self, parent: QWidget | None = None) -> None:
#         super().__init__(parent)
#         self._layout = QHBoxLayout(self)
#         self._line_edit = QLineEdit(self)
#         self._layout.addWidget(self._line_edit)
#         self.setLayout(self._layout)
        
#         self._line_edit.textChanged.connect(lambda text: self.setValue(text))
#         self._value: str = ""

#     def setValue(self, value: str) -> None:
#         if self._value == value:
#             return
#         self._value = value
#         self._line_edit.setText(value)
#         self.valueChanged.emit(value)

#     def getValue(self):
#         return self._value

#     value = Property(str, getValue, setValue, notify=valueChanged, user=True)



class _NodeInputWrapper(QWidget):
    valueChanged = Signal(object)
    clearRequested = Signal()

    def __init__(self, widget: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._widget = widget
        self._prop = widget.metaObject().userProperty()
        self.setStyleSheet("""
            QWidget[usingDefault="true"],
            QWidget[usingDefault="true"] QWidget {
                color: palette(mid);
                selection-color: palette(mid);
                font-style: italic;
            }
        """)

        self._clearbtn = QPushButton("Clear", self)
        self._clearbtn.clicked.connect(self.clearRequested.emit)

        self._layout = QHBoxLayout(self)
        self._layout.setSpacing(0)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.addWidget(self._clearbtn)
        self._layout.addWidget(self._widget)

        # Connect to the user property's NOTIFY signal
        if self._prop.hasNotifySignal():
            signal_name = bytes(
                self._prop.notifySignal().name()
            ).decode()

            getattr(self._widget, signal_name).connect(
                self._onValueChanged
            )

    # def setUsingDefault(self, using_default: bool) -> None:
    #     if self._widget.property("usingDefault") == using_default:
    #         return

    #     self._widget.setProperty("usingDefault", using_default)
    #     for widget in [self._widget, *self._widget.findChildren(QWidget)]:
    #         style = widget.style()
    #         style.unpolish(widget)
    #         style.polish(widget)
    #         widget.updateGeometry()
    #         widget.update()

    def _onValueChanged(self, *args: object) -> None:
        # self.setUsingDefault(False)
        self.valueChanged.emit(self.getValue())

    def setValue(self, value: object) -> None:
        self._prop.write(self._widget, value)

    def getValue(self) -> object:
        return self._prop.read(self._widget)

    value = Property(
        "QVariant",
        getValue,
        setValue,
        notify=valueChanged,
        user=True
    )


class NodeInputDelegate(QStyledItemDelegate):
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)

    def createEditor(
        self,
        parent: QWidget | None,
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> QWidget:
        connected_node = index.data(NodeRTInputRole.ConnectionRole)
        datatype = index.data(NodeRTInputRole.AnnotationRole)
        if connected_node:
            widget = QLabel(f"-> {connected_node}", parent)
            # btn.setEnabled(False)
            return widget
        elif datatype == str:
            widget = QLineEdit(parent)
            editor = _NodeInputWrapper(widget, parent)
            widget.textChanged.connect(lambda: self.commitData.emit(editor))
        elif datatype == int:
            widget = QSpinBox(parent)
            editor = _NodeInputWrapper(widget, parent)
            
        elif datatype == float:
            widget = QDoubleSpinBox(parent)
            editor = _NodeInputWrapper(widget, parent)
            
        else:
            widget = QLineEdit(parent)
            editor = _NodeInputWrapper(widget, parent)
        
        editor.clearRequested.connect(lambda: 
            index.model().setData(index,ParameterData.EMPTY)
        )
        return editor

    def setEditorData(self, editor: QWidget | None, index: QModelIndex) -> None:
        if editor is None:
            return

        super().setEditorData(editor, index)
        default_value = index.data(NodeRTInputRole.DefaultRole)
        if default_value is not ParameterData.EMPTY:
            if isinstance(editor, QLineEdit):
                editor.setPlaceholderText(default_value)
            elif isinstance(editor, _NodeInputWrapper):
                widget = editor._widget
                if isinstance(widget, QLineEdit):
                    if default_value is not None:
                        widget.setPlaceholderText(f"{default_value}")
        is_using_default = bool(index.data(NodeRTInputRole.IsUsingDefaultRole))
        
        # if isinstance(editor, _NodeInputWrapper):
        #     editor.setProperty("usingDefault", is_using_default)
        #     editor._widget.setProperty("usingDefault", is_using_default)
        #     widget = editor._widget
        #     style = widget.style()
        #     style.unpolish(widget)
        #     style.polish(widget)
        #     widget.updateGeometry()
        #     widget.update()
        # else:
        #     editor.setProperty("usingDefault", is_using_default)
        #     style = editor.style()
        #     style.unpolish(editor)
        #     style.polish(editor)
        #     editor.updateGeometry()
        #     editor.update()
            

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
