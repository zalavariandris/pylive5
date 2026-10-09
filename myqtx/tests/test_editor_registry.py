from dataclasses import dataclass
from enum import Enum, IntEnum, StrEnum
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot
from qtpy.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox, QLineEdit, QSpinBox, QWidget

from myqtx import EditorRegistry


class Color(Enum):
    RED = (255, 0, 0)
    BLUE = (0, 0, 255)


class Priority(IntEnum):
    LOW = 1
    HIGH = 2


class Mode(StrEnum):
    FAST = "fast"
    SLOW = "slow"


class StringColor(str, Enum):
    RED = "red"
    BLUE = "blue"


@pytest.mark.parametrize(("value", "widget_type"), [
    ("hello", QLineEdit),
    (123, QSpinBox),
    (1.25, QDoubleSpinBox),
    (True, QCheckBox),
    (Path("example.txt"), QLineEdit),
    (Color.BLUE, QComboBox),
    (Priority.HIGH, QComboBox),
    (Mode.SLOW, QComboBox),
    (StringColor.BLUE, QComboBox),
])
def test_default_editors_round_trip_python_values(
    qtbot: QtBot, value: object, widget_type: type[QWidget],
) -> None:
    registry = EditorRegistry()
    factory = registry.factory_for(type(value))
    assert factory is not None
    editor = factory(type(value), None)
    qtbot.addWidget(editor.widget)
    assert isinstance(editor.widget, widget_type)
    editor.set_value(value)
    assert editor.get_value() == value
    assert type(editor.get_value()) is type(value)
    editor.set_value(None)
    if isinstance(value, Enum):
        assert editor.widget.currentIndex() == -1


def test_registry_uses_mro_and_keeps_replacements_local() -> None:
    @dataclass
    class Reading:
        value: int

    class SpecialReading(Reading):
        pass

    registry = EditorRegistry()
    other = EditorRegistry()
    factory = registry.factory_for(int)
    replacement = registry.factory_for(str)
    assert factory is not None and replacement is not None
    assert registry.factory_for(Reading) is None
    assert registry.factory_for(list) is None
    registry.register_editor(Reading, factory)
    assert registry.factory_for(SpecialReading) is factory
    registry.register_editor(SpecialReading, replacement)
    assert registry.factory_for(SpecialReading) is replacement
    registry.register_editor(Reading, replacement)
    assert registry.factory_for(Reading) is replacement
    assert other.factory_for(Reading) is None


def test_registry_rejects_invalid_registrations() -> None:
    registry = EditorRegistry()
    factory = registry.factory_for(str)
    with pytest.raises(TypeError, match="Python type"):
        registry.register_editor("str", factory)
    with pytest.raises(TypeError, match="callable"):
        registry.register_editor(str, None)
