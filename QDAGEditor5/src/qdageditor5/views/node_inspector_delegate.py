from typing import Any
import inspect
from qtpy.QtGui import QPalette
from qtpy.QtWidgets import QLabel
from qtpy.QtCore import Qt, QObject, QSignalBlocker
from qtpy.QtWidgets import  (
    QDoubleSpinBox, 
    QLineEdit, 
    QSpinBox,
    QWidget
)

from ..models.abstract_dag_model import (
    AbstractDAGModel, 
    NodeName, 
    InletName,
    OutletName
)

from ..core.inspector_roles import InspectorRoles


class NodeInspectorDelegate(QObject):
    EMPTY = None

    def __init__(self, parent:QObject|None=None):
        super().__init__(parent=parent)
        self._model = None

    def _datatype(
        self, model: AbstractDAGModel, node: NodeName, inlet: InletName,
    ) -> object:
        datatype = model.inletData(node, inlet, InspectorRoles.DataTypeRole)
        if (
            datatype is not None
            and datatype is not Any
            and datatype is not inspect.Parameter.empty
        ):
            return datatype

        value = model.inletData(node, inlet, Qt.ItemDataRole.EditRole)
        if value is not self.EMPTY:
            return type(value)

        default = model.inletData(node, inlet, InspectorRoles.DefaultValueRole)
        if default is not None and default is not inspect.Parameter.empty:
            return type(default)

        return None

    def createEditor(self, model:AbstractDAGModel, node: NodeName, inlet: InletName) -> QWidget:
        datatype = self._datatype(model, node, inlet)

        # match editor based on datatype
        editor:QWidget|None = None
        if datatype is str:
            editor = QLineEdit()

        if datatype is int:
            editor = QSpinBox()
            editor.setRange(-(2**31), 2**31 - 1)
            editor.clear()

        if datatype is float:
            editor = QDoubleSpinBox()
            editor.setRange(-999, 999)
            editor.clear()

        if editor is None:
            if datatype is None:
                reason = "unset · unknown type"
                details = "No value is assigned, and no input type could be determined."
            else:
                type_name = getattr(datatype, "__name__", str(datatype))
                reason = f"No editor for {type_name}"
                details = f"The input type is {type_name}, but no editor is available for it."
            label = QLabel(reason)
            label.setToolTip(details)
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            label.setForegroundRole(QPalette.ColorRole.PlaceholderText)
            return label

        return editor

    def setEditorData(self, model:AbstractDAGModel, node: NodeName, inlet: InletName, widget: QWidget) -> None:
        value = model.inletData(node, inlet, Qt.ItemDataRole.EditRole)
        is_empty = value is self.EMPTY

        with QSignalBlocker(widget):
            metaobject = widget.metaObject()
            if metaobject is None:
                return

            user_property = metaobject.userProperty()
            if not user_property.isValid():
                return

            if is_empty:
                try:
                    widget.clear()
                except AttributeError:
                    pass
            else:
                # write the value to the widget's user property
                if user_property.read(widget) != value:
                    user_property.write(widget, value)

    def setModelData(self, model:AbstractDAGModel, node: NodeName, key: InletName, widget: QWidget) -> None:
        metaobject = widget.metaObject()
        if metaobject is None:
            return
        
        user_property = metaobject.userProperty()
        if not user_property.isValid():
            return
        
        new_value = user_property.read(widget)
        model.setInletData(node, key, new_value, Qt.ItemDataRole.EditRole)
