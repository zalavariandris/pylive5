

from qtpy.QtCore import QModelIndex, Qt, Signal
from qtpy.QtWidgets import (
    QDoubleSpinBox,
    QSpinBox,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QWidget,
    QPushButton,
)

from qtpy.QtGui import QPainter, QPalette

from .inspector_roles import InspectorRole


class NodeInputWidget(QWidget):
    clearRequested = Signal()

    def __init__(self, editor: QWidget, parent=None):
        super().__init__(parent)
        self.setAutoFillBackground(True)

        # create the editor
        self.editor = editor
        editor.setParent(self)
        self.clear_button = QPushButton("Clear", self)
        self.clear_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.clear_button.clicked.connect(self.clearRequested.emit)
        self.setFocusProxy(editor)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        rect = self.contentsRect()
        button_width = min(self.clear_button.sizeHint().width(), rect.width())
        editor_width = max(0, rect.width() - button_width)
        self.editor.setGeometry(
            rect.x(), rect.y(), editor_width, rect.height()
        )
        self.clear_button.setGeometry(
            rect.x() + editor_width,
            rect.y(),
            button_width,
            rect.height(),
        )

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.palette().color(QPalette.Window))
        super().paintEvent(event)


class NodeInputDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)

    def createEditor(self, 
        parent: QWidget|None, 
        option: QStyleOptionViewItem, 
        index: QModelIndex
    ) -> QWidget|None:
        annotation = index.data(InspectorRole.AnnotationRole)
        if annotation == "int" or annotation is int:
            editor = QSpinBox(parent)
        elif annotation == "float" or annotation is float:
            editor = QDoubleSpinBox(parent)
            editor.setDecimals(3)
            editor.setSingleStep(0.1)
        else:
            editor = super().createEditor(parent, option, index)

        if editor is None:
            return None

        wrapper = NodeInputWidget(editor, parent)

        model = index.model()
        node_ref = index.data(InspectorRole.NodeRefRole)
        location = index.data(InspectorRole.InputLocationRole)
        if node_ref is not None and location is not None:
            wrapper.clearRequested.connect(
                lambda: self._clear_input(
                    wrapper, model, node_ref, location
                )
            )

        return wrapper

    def setEditorData(self, editor, index):
        if isinstance(editor, NodeInputWidget):
            super().setEditorData(editor.editor, index)
            return
        super().setEditorData(editor, index)

    def setModelData(self, editor, model, index):
        if isinstance(editor, NodeInputWidget):
            super().setModelData(editor.editor, model, index)
            return
        super().setModelData(editor, model, index)

    def updateEditorGeometry(self, editor, option, index):
        if isinstance(editor, NodeInputWidget):
            editor.setGeometry(option.rect)
            return
        super().updateEditorGeometry(editor, option, index)

    def _clear_input(self, editor, model, node_ref, location) -> None:
        clear_input = getattr(model, "clearInput", None)
        if not callable(clear_input):
            return

        self.closeEditor.emit(
            editor, QStyledItemDelegate.EndEditHint.NoHint
        )
        clear_input(node_ref, location)

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)

        if index.data(InspectorRole.IsUsingDefaultRole):
            color = option.palette.color(
                QPalette.ColorGroup.Disabled,
                QPalette.ColorRole.Text,
            )
            option.palette.setColor(
                QPalette.ColorGroup.Active,
                QPalette.ColorRole.Text,
                color,
            )
            option.palette.setColor(
                QPalette.ColorGroup.Inactive,
                QPalette.ColorRole.Text,
                color,
            )
