from typing import Annotated, Any, get_args, get_origin
from pathlib import Path

from qtpy.QtCore import QModelIndex
from qtpy.QtWidgets import QCheckBox, QLineEdit, QSpinBox, QDoubleSpinBox, QStyleOptionViewItem, QWidget
from myqtx.widgets.qpathedit import QPathEdit

from pyflow5.core.input_roles import InputDataRole
from pyflow5.views.abstract_input_editor_provider import AbstractInputEditorProvider
from pyflow5.views.node_input_delegate import NodeInputFieldDelegate


class BuiltinInputEditorProvider(AbstractInputEditorProvider):
    def createEditor(
        self,
        parent: QWidget | None,
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> QWidget | None:
        datatype = index.data(InputDataRole.AnnotationRole)
        if get_origin(datatype) is Annotated:
            datatype = get_args(datatype)[0]
        editor: QWidget | None = None
        if datatype in (str, str | Path):
            editor = QLineEdit(parent)
            # editor.textChanged.connect(lambda: self.commitData.emit(editor))

        elif datatype == bool:
            editor = QCheckBox(parent)
            # editor.stateChanged.connect(lambda: self.commitData.emit(editor))

        elif datatype == int:
            editor = QSpinBox(parent)
            # editor.valueChanged.connect(lambda: self.commitData.emit(editor))
            
        elif datatype == float:
            editor = QDoubleSpinBox(parent)
            # editor.valueChanged.connect(lambda: self.commitData.emit(editor))

        elif datatype == Path:
            editor = QPathEdit(parent=parent)
            # editor.pathChanged.connect(lambda: self.commitData.emit(editor))

        return editor

    def setEditorValue(self, editor: QWidget, value: Any) -> None:
        if isinstance(editor, QPathEdit):
            #todo: QPathEdit does not support QProperty. QMetaProperty.read() fails in this environment.
            #      so this is a temporary fix. the issue needs more investigation.
            editor.setPath("" if value is None else str(value))
        elif isinstance(editor, QLineEdit):
            editor.setText("" if value is None else str(value))
        else:
            super().setEditorValue(editor, value)

    def editorValue(self, editor: QWidget) -> Any:
        if isinstance(editor, QPathEdit):
            return Path(editor.getPath())
        elif isinstance(editor, QLineEdit):
            return editor.text()
        else:
            return super().editorValue(editor)

NodeInputFieldDelegate.register_input_editor_provider(BuiltinInputEditorProvider)
