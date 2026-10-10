"""Small adapters between ordinary Qt widgets and Python values."""

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Generic, TypeVar

from qtpy.QtCore import Qt, SignalInstance
from qtpy.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QLabel, QLineEdit, QSpinBox, QWidget,
)


T = TypeVar("T")


@dataclass
class Editor(Generic[T]):
    """A widget, typed value accessors, and its user-change signal.

    set_value must accept None for an input without a value or default.
    The delegate suppresses commits while calling set_value.
    Optional set_default customizes default presentation (for example, a
    placeholder). Without it, defaults use set_value and the delegate's styling.
    """

    widget: QWidget
    get_value: Callable[[], T]
    set_value: Callable[[T | None], None]
    changed: SignalInstance | None
    set_default: Callable[[T | None], None] | None = None

# Parameterized annotations, such as Tuple[float, float], are not Python types.
EditorFactory = Callable[[object, QWidget | None], Editor[Any]]

def _set_text(widget: QLineEdit, value: object) -> None:
    widget.setPlaceholderText("")
    text = "" if value is None else str(value)
    # Preserve the cursor when the model echoes a keystroke.
    if widget.text() != text:
        widget.setText(text)

def _set_placeholder(widget: QLineEdit, value: object) -> None:
    _set_text(widget, None)
    widget.setPlaceholderText("" if value is None else str(value))

def string_editor(datatype: object, parent: QWidget | None) -> Editor[str]:
    widget = QLineEdit(parent)
    return Editor(
        widget, 
        get_value   = widget.text, 
        set_value   = lambda value: _set_text(widget, value), 
        changed     = widget.textChanged,
        set_default = lambda value: _set_placeholder(widget, value),
    )

def int_editor(datatype: object, parent: QWidget | None) -> Editor[int]:
    widget = QSpinBox(parent)
    widget.setRange(-1_000_000, 1_000_000)
    return Editor(
        widget, 
        get_value = widget.value,
        set_value = lambda value: widget.setValue(0 if value is None else value),
        changed = widget.valueChanged,
    )

def float_editor(datatype: object, parent: QWidget | None) -> Editor[float]:
    widget = QDoubleSpinBox(parent)
    widget.setRange(-1_000_000, 1_000_000)
    widget.setDecimals(3)
    widget.setSingleStep(0.1)
    return Editor(
        widget, 
        get_value = widget.value,
        set_value = lambda value: widget.setValue(0.0 if value is None else value),
        changed   = widget.valueChanged,
    )

def bool_editor(datatype: object, parent: QWidget | None) -> Editor[bool]:
    widget = QCheckBox(parent)

    def set_value(value: bool | None) -> None:
        widget.setText("")
        widget.setChecked(False if value is None else value)

    def set_default(value: bool | None) -> None:
        set_value(value)
        widget.setText("Default")

    return Editor(
        widget, 
        get_value   = widget.isChecked, 
        set_value   = set_value, 
        changed     = widget.toggled,
        set_default = set_default,
    )

def path_editor(datatype: object, parent: QWidget | None) -> Editor[Path]:
    if not isinstance(datatype, type) or not issubclass(datatype, Path):
        raise TypeError("Expected a Path type")
    widget = QLineEdit(parent)
    return Editor(
        widget, 
        get_value   = lambda: datatype(widget.text()),
        set_value   = lambda value: _set_text(widget, value), 
        changed     = widget.textChanged,
        set_default = lambda value: _set_placeholder(widget, value),
    )

def enum_editor(datatype: object, parent: QWidget | None) -> Editor[Enum | None]:
    if not isinstance(datatype, type) or not issubclass(datatype, Enum):
        raise TypeError("Expected an Enum type")
    widget = QComboBox(parent)
    members = list(datatype)
    widget.addItems([member.name for member in members])

    def get_value() -> Enum | None:
        index = widget.currentIndex()
        return members[index] if index >= 0 else None

    def set_value(value: Enum | None) -> None:
        widget.setCurrentIndex(members.index(value) if value in members else -1)

    return Editor(
        widget, 
        get_value, 
        set_value, 
        changed = widget.currentIndexChanged
    )

def label_editor(datatype: object, parent: QWidget | None) -> Editor[object]:
    widget = QLabel(parent)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    return Editor(
        widget, 
        get_value = widget.text,
        set_value = lambda value: widget.setText("" if value is None else str(value)),
        changed=None,
    )

def read_only_editor(datatype: object, parent: QWidget | None) -> Editor[object]:
    widget = QLineEdit(parent)
    widget.setReadOnly(True)
    return Editor(
        widget, 
        get_value = widget.text, 
        set_value = lambda value: _set_text(widget, value), 
        changed   = widget.textChanged,
    )

"""A reusable editor for fixed-length numeric tuple annotations."""
from typing import Any, get_args, get_origin
from qtpy.QtCore import QSignalBlocker, Signal
from qtpy.QtWidgets import QHBoxLayout, QLabel, QWidget, QLineEdit, QComboBox

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
