from typing import Any

from qtpy.QtCore import Qt, QObject, QSignalBlocker
from qtpy.QtWidgets import  (
    QDoubleSpinBox, 
    QGraphicsColorizeEffect, 
    QGraphicsOpacityEffect,
    QGraphicsEffect, 
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

    def createEditor(self, model:AbstractDAGModel, node: NodeName, inlet: InletName) -> QWidget:
        inlet_value = model.inletData(node, inlet, Qt.ItemDataRole.EditRole)
        is_connected = bool(list(model.inLinks(node, inlet)))
        
        datatype = model.inletData(node, inlet, InspectorRoles.DataTypeRole)

        # fallback to infer the datatype from the type fo the value
        if datatype is self.EMPTY or datatype is Any:
            datatype = type(inlet_value)

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
            # fallback to display the data
            editor = QLineEdit()
            editor.setReadOnly(True)

        # add the dim effect to the editors
        opacity_effect = QGraphicsOpacityEffect(editor)
        opacity_effect.setOpacity(0.15)
        opacity_effect.setEnabled(False)
        colorize_effect = QGraphicsColorizeEffect(editor)
        colorize_effect.setColor(Qt.GlobalColor.gray)
        colorize_effect.setStrength(0.5)
        colorize_effect.setEnabled(False)
        editor.setGraphicsEffect(colorize_effect)
        return editor

    def setEditorData(self, model:AbstractDAGModel, node: NodeName, inlet: InletName, widget: QWidget) -> None:
        value = model.inletData(node, inlet, Qt.ItemDataRole.EditRole)
        is_connected = bool(list(model.inLinks(node, inlet)))
        is_empty = value is self.EMPTY
        effect = widget.graphicsEffect()
        if effect is not None:
            effect.setEnabled(is_connected or is_empty)

        with QSignalBlocker(widget):
            metaobject = widget.metaObject()
            if metaobject is None:
                return

            user_property = metaobject.userProperty()
            if not user_property.isValid():
                return

            if is_connected:
                widget.setEnabled(False)
            else:
                widget.setEnabled(True)

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
