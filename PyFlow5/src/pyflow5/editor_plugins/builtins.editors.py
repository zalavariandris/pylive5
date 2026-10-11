from qtpy.QtWidgets import QLineEdit, QSpinBox, QDoubleSpinBox, QStyleOptionViewItem, QWidget
from typing import Any

from qtpy.QtCore import QModelIndex
from pyflow5.core.nodert_input_roles import NodeRTInputRole

from pyflow5.views.abstract_input_editor_provider import AbstractInputEditorProvider

from pyflow5.views.node_input_delegate import NodeInputFieldDelegate

class BuiltinInputEditorProvider(AbstractInputEditorProvider):
    def createEditor(
        self,
        parent: QWidget | None,
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> QWidget | None:
        datatype = index.data(NodeRTInputRole.AnnotationRole)
        editor: QWidget | None = None
        if datatype == str:
            editor = QLineEdit(parent)
            editor.textChanged.connect(lambda: self.commitData.emit(editor))

        elif datatype == int:
            editor = QSpinBox(parent)
            editor.valueChanged.connect(lambda: self.commitData.emit(editor))
            
        elif datatype == float:
            editor = QDoubleSpinBox(parent)
            editor.valueChanged.connect(lambda: self.commitData.emit(editor))
            
        return editor

NodeInputFieldDelegate.register_input_editor_provider(BuiltinInputEditorProvider)
