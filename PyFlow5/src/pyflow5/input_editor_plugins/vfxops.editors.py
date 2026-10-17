"""Editors for vfxops' ranges, colors, vectors, sizes, and rectangles."""

from typing import Annotated, Any, get_args, get_origin

from qtpy.QtCore import QModelIndex, Property, QSignalBlocker, QSize, Signal
from qtpy.QtGui import QColor
from qtpy.QtWidgets import QSizePolicy
from qtpy.QtWidgets import (
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QStyle,
    QStyleOptionFrame,
    QStyleOptionViewItem,
    QWidget,
)

from myqtx.widgets.coloredit import ColorEdit
from myqtx.widgets.numeric_tuple_edit import NumericTupleEdit
from myqtx.widgets.qfloatslider import QFloatSlider
from vfxops_interleaved.core import Range

from pyflow5.core.input_roles import InputDataRole
from pyflow5.views.abstract_input_editor_provider import AbstractInputEditorProvider
from pyflow5.views.node_input_delegate import NodeInputFieldDelegate


class VFXInputEditorProvider(AbstractInputEditorProvider):
    def createEditor(
        self,
        parent: QWidget | None,
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> QWidget | None:
        annotation = index.data(InputDataRole.AnnotationRole)
        if get_origin(annotation) is Annotated:
            annotation, *metadata = get_args(annotation)
            value_range = next(
                (item for item in metadata if isinstance(item, Range)), None,
            )
            if annotation is float and value_range is not None:
                slider = QFloatSlider(
                    parent=parent,
                    minimum=value_range.minimum,
                    maximum=value_range.maximum,
                    step=value_range.step,
                )
                slider.valueChanged.connect(lambda: self.commitData.emit(slider))
                return slider

        if get_origin(annotation) is not tuple:
            return None

        components = get_args(annotation)
        editor: NumericTupleEdit | ColorEdit
        if components == (float, float, float, float):
            editor = ColorEdit(parent)
            editor.colorChanged.connect(lambda: self.commitData.emit(editor))

        elif components in ((float, float), (float, float, float)):
            editor = NumericTupleEdit(components, parent, labels=("X", "Y", "Z")[:len(components)])

        elif components == (int, int):
            editor = NumericTupleEdit(components, parent, labels=("W", "H"))

        elif components == (int, int, int, int):
            editor = NumericTupleEdit(components, parent, labels=("X", "Y", "W", "H"))
            
        else:
            return None

        if isinstance(editor, NumericTupleEdit):
            editor.valueChanged.connect(lambda: self.commitData.emit(editor))
        return editor

    def setEditorValue(self, editor: QWidget, value: Any) -> None:
        if isinstance(editor, QFloatSlider):
            editor.setValue(editor.minimum() if value is None else float(value))
        elif isinstance(editor, ColorEdit):
            rgba = (0.0, 0.0, 0.0, 1.0) if value is None else value
            editor.setColor(QColor.fromRgbF(*rgba))
        elif isinstance(editor, NumericTupleEdit):
            editor.setValue(value)
        else:
            super().setEditorValue(editor, value)

    def editorValue(self, editor: QWidget) -> Any:
        if isinstance(editor, ColorEdit):
            return tuple(editor.getColor().getRgbF())
        if isinstance(editor, NumericTupleEdit):
            return tuple(editor.getValue())
        return super().editorValue(editor)


NodeInputFieldDelegate.register_input_editor_provider(VFXInputEditorProvider)
