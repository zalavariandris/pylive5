"""A reusable editor for fixed-length numeric tuple annotations."""

from typing import Any, get_args, get_origin

from qtpy.QtCore import QSignalBlocker, Signal
from qtpy.QtWidgets import QHBoxLayout, QLabel, QWidget

from .editors import Editor, float_editor, int_editor


class NumericTupleEdit(QWidget):
    valueChanged = Signal()

    def __init__(
        self, component_types: tuple[type[int] | type[float], ...],
        parent: QWidget | None = None, *, labels: tuple[str, ...] = (),
    ) -> None:
        super().__init__(parent)
        if not component_types or any(t not in (int, float) for t in component_types):
            raise TypeError("Expected a fixed-length tuple of int or float components")
        if labels and len(labels) != len(component_types):
            raise ValueError("Expected one label per tuple component")
        self._components: list[Editor[Any]] = []
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        for index, component_type in enumerate(component_types):
            factory = int_editor if component_type is int else float_editor
            component = factory(component_type, self)
            self._components.append(component)
            if labels:
                label = QLabel(labels[index], self)
                label.setBuddy(component.widget)
                component.widget.setAccessibleName(labels[index])
                layout.addWidget(label)
            layout.addWidget(component.widget, 1)
            if component.changed is not None:
                component.changed.connect(self._on_component_changed)
        self.setFocusProxy(self._components[0].widget)

    def _on_component_changed(self, *args: object) -> None:
        self.valueChanged.emit()

    def value(self) -> tuple[int | float, ...]:
        return tuple(component.get_value() for component in self._components)

    def setValue(self, value: tuple[int | float, ...] | None) -> None:
        # Live annotation edits may change the tuple length. Preserve the values
        # that still fit and initialize any new components without storing them.
        for index, component in enumerate(self._components):
            item = (
                value[index]
                if isinstance(value, (tuple, list)) and index < len(value) else None
            )
            with QSignalBlocker(component.widget):
                component.set_value(item)


def numeric_tuple_editor(
    annotation: object, parent: QWidget | None, *, labels: tuple[str, ...] = (),
) -> Editor[tuple[int | float, ...]]:
    if get_origin(annotation) is not tuple:
        raise TypeError("Expected a parameterized tuple annotation")
    widget = NumericTupleEdit(get_args(annotation), parent, labels=labels)
    return Editor(widget, widget.value, widget.setValue, widget.valueChanged)
