from dataclasses import dataclass
from enum import Enum, IntEnum, StrEnum
from pathlib import Path
from typing import Tuple

import pytest
from pytestqt.qtbot import QtBot
from qtpy.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox, QLineEdit, QSpinBox, QWidget

from myqtx import EditorContext, EditorFactory, EditorRegistry
from myqtx.editors import int_editor, string_editor
from myqtx.tuple_editor import numeric_tuple_editor


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


def test_providers_use_context_and_fall_back_to_type_lookup() -> None:
    registry = EditorRegistry()
    calls: list[EditorContext] = []

    def provider(context: EditorContext) -> EditorFactory | None:
        calls.append(context)
        if context.operator_name == "render" and context.parameter_name == "position":
            return numeric_tuple_editor
        return None

    registry.register_provider("graphics", provider)
    context = EditorContext("graphics", "render", "position", Tuple[float, float])
    assert registry.factory_for(context.annotation, context=context) is numeric_tuple_editor
    assert calls == [context]
    fallback = EditorContext("graphics", "render", "count", int)
    assert registry.factory_for(int, context=fallback) is int_editor
    other = EditorContext("geometry", "render", "position", context.annotation)
    assert registry.factory_for(other.annotation, context=other) is None
    assert registry.factory_for(context.annotation) is None
    assert registry.factory_for("unfinished annotation") is None
    assert len(calls) == 2


def test_file_provider_precedence_normalization_and_instance_isolation(tmp_path: Path) -> None:
    registry = EditorRegistry()
    path = tmp_path / "graphics.py"
    registry.register_provider("graphics.py", lambda context: string_editor)
    registry.register_provider(path, lambda context: int_editor)
    context = EditorContext("graphics.py", "render", "count", int, path.parent / "." / path.name)
    assert registry.factory_for(int, context=context) is int_editor
    assert EditorRegistry().factory_for(int, context=context) is int_editor

    other_file = EditorContext("graphics.py", "render", "count", int, tmp_path / "other" / path.name)
    assert registry.factory_for(int, context=other_file) is string_editor
    registry.register_provider(path, lambda context: None)
    assert registry.factory_for(int, context=context) is string_editor
    registry.register_provider(path, lambda context: numeric_tuple_editor)
    assert registry.factory_for(int, context=context) is numeric_tuple_editor
    assert EditorRegistry().factory_for(int, context=context) is int_editor


def test_registry_rejects_invalid_providers() -> None:
    registry = EditorRegistry()
    with pytest.raises(ValueError, match="module"):
        registry.register_provider("", lambda context: None)
    with pytest.raises(TypeError, match="callable"):
        registry.register_provider("graphics", None)
    registry.register_provider("graphics", lambda context: 42)
    with pytest.raises(TypeError, match="factory or None"):
        registry.factory_for(int, context=EditorContext("graphics", "render", "count", int))
