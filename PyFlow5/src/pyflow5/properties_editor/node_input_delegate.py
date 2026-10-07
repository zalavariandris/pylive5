

from qtpy.QtCore import QModelIndex, Qt, Signal
from qtpy.QtWidgets import (
    QDoubleSpinBox,
    QSpinBox,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QWidget,
    QPushButton,
    QLineEdit,
)

from qtpy.QtGui import QPainter, QPalette

from ..nodert_input_roles import NodeRTInputRole
from pygraphrt.abstract_operator import ParameterData


class NodeInputWidget(QWidget):
    clearRequested = Signal()

    def __init__(self, editor: QWidget, parent=None):
        super().__init__(parent)
        self.setAutoFillBackground(True)

        # create the editor
        self.editor = editor
        editor.setParent(self)

        self.clear_button = QPushButton("✖", self)
        
        self.clear_button.setStyleSheet("""\
            QPushButton {
                background: transparent; border: none; padding: 0; margin: 0; 
            }
            QPushButton:hover {
                color: palette(Highlight);
            }
            """
        )
        

        # self.clear_button.setStyleSheet(""""""
        #     "QPushButton { background-color: transparent; border: none; color: "
        #     "transparent; }"
        #     "QPushButton:hover { background-color: transparent; border: none; }"
        #     "QPushButton:pressed { background-color: transparent; border: none; }"
        # )
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
            rect.height()
        )

    # def paintEvent(self, event):
    #     painter = QPainter(self)
    #     painter.fillRect(self.rect(), self.palette().color(QPalette.Window))
    #     super().paintEvent(event)


class NodeInputDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)

    def createEditor(self, 
        parent: QWidget|None, 
        option: QStyleOptionViewItem, 
        index: QModelIndex
    ) -> QWidget|None:

        # find appropriate editor based on the annotation
        annotation = index.data(NodeRTInputRole.AnnotationRole)
        if annotation == "int" or annotation is int:
            editor = QSpinBox(parent)
        elif annotation == "float" or annotation is float:
            editor = QDoubleSpinBox(parent)
            editor.setDecimals(3)
            editor.setSingleStep(0.1)
        elif annotation == "str" or annotation is str:
            editor = QLineEdit(parent)
        else:
            editor = super().createEditor(parent, option, index)

        if editor is None:
            return None

        # create wrapper widget
        wrapper = NodeInputWidget(editor, parent)

        if isinstance(editor, QLineEdit):
            editor.textEdited.connect(
                lambda *_: self.commitData.emit(wrapper)
            )
        elif isinstance(editor, (QSpinBox, QDoubleSpinBox)):
            editor.valueChanged.connect(
                lambda *_: self.commitData.emit(wrapper)
            )

        wrapper.clearRequested.connect(
            lambda: self._clear_input(wrapper, index)
        )

        return wrapper

    def setEditorData(
        self, editor: QWidget | None, index: QModelIndex
    ) -> None:
        if editor is None:
            return
        target = editor.editor if isinstance(editor, NodeInputWidget) else editor
        signals_were_blocked = target.blockSignals(True)

        try:
            # todo: this is a temporary fix for the current twoway binding cycle see bug in TODO.md
            if isinstance(target, QLineEdit) and target.text() == index.data(Qt.ItemDataRole.EditRole):
                pass
            else:
                super().setEditorData(target, index) 
        finally:
            target.blockSignals(signals_were_blocked)

    def setModelData(self, editor, model, index):
        if isinstance(editor, NodeInputWidget):
            super().setModelData(editor.editor, model, index)
            return
        super().setModelData(editor, model, index)

    def _clear_input(self, editor, index) -> None:
        self.closeEditor.emit(
            editor, QStyledItemDelegate.EndEditHint.NoHint
        )
        index.model().setData(
            index, ParameterData.EMPTY, Qt.ItemDataRole.EditRole
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
                option.palette.setColor(
                    group, QPalette.ColorRole.Text, color
                )
                option.palette.setColor(
                    group, QPalette.ColorRole.HighlightedText, color
                )
