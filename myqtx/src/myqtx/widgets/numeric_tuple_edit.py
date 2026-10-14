"""Tuple editors following vfxops' color, vector, size, and rectangle conventions."""

from typing import Any, get_args, get_origin

from qtpy.QtCore import QModelIndex, Property, QSignalBlocker, QSize, Signal
from qtpy.QtWidgets import QSizePolicy
from qtpy.QtWidgets import (
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QStyle,
    QStyleOptionFrame,
    QWidget,
)

class NumericTupleEdit(QWidget):
    valueChanged = Signal()

    def __init__(
        self,
        component_types: tuple[type[int] | type[float], ...],
        parent: QWidget | None = None,
        *,
        labels: tuple[str, ...] = (),
    ) -> None:
        super().__init__(parent)
        if not component_types or any(t not in (int, float) for t in component_types):
            raise TypeError("Expected a fixed-length tuple of int or float components")
        if labels and len(labels) != len(component_types):
            raise ValueError("Expected one label per tuple component")

        self._components: list[QSpinBox | QDoubleSpinBox] = []
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        for index, component_type in enumerate(component_types):
            component: QSpinBox | QDoubleSpinBox
            if component_type is int:
                component = QSpinBox(self)
            else:
                component = QDoubleSpinBox(self)
                component.setDecimals(3)
                component.setSingleStep(0.1)
            component.setRange(-1_000, 1_000)
            component.setSizePolicy(
                QSizePolicy.Policy.Preferred,
                QSizePolicy.Policy.Fixed,
            )
            self._components.append(component)
            if labels:
                label = QLabel(labels[index], self)
                label.setBuddy(component)
                component.setAccessibleName(labels[index])
                layout.addWidget(label)
            layout.addWidget(component, 1)
            component.valueChanged.connect(self._on_component_changed)
        self.setFocusProxy(self._components[0])

    def _on_component_changed(self, value: int | float) -> None:
        self.valueChanged.emit()

    def getValue(self) -> list[int | float]:
        return [component.value() for component in self._components]

    def setValue(self, value: list[int | float] | tuple[int | float, ...] | None) -> None:
        for index, component in enumerate(self._components):
            item = value[index] if value is not None and index < len(value) else 0
            with QSignalBlocker(component):
                component.setValue(item)

    def sizeHint(self) -> QSize:
        self.ensurePolished()
        style = self.style()
        metrics = self.fontMetrics()

        option = QStyleOptionFrame()
        option.initFrom(self)
        option.lineWidth = style.pixelMetric(
            QStyle.PixelMetric.PM_DefaultFrameWidth, option, self
        )

        content_size = QSize(
            metrics.horizontalAdvance("0") * 3,
            metrics.height(),
        )
        return style.sizeFromContents(
            QStyle.ContentsType.CT_LineEdit,
            option,
            content_size,
            self,
        )

    value = Property(list, getValue, setValue, user=True)