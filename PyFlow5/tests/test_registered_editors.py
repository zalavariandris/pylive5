from dataclasses import dataclass
from enum import Enum, IntEnum, StrEnum
from pathlib import Path

import pygraphrt as rt
import pytest
from qtpy.QtCore import Qt
from qtpy.QtGui import QPalette
from qtpy.QtWidgets import QComboBox, QLineEdit, QSpinBox, QWidget

from myqtx import Editor, EditorRegistry
from pyflow5.views.formview import FormView
from pyflow5.views.node_input_delegate import NodeInputDelegate


class Color(Enum):
    RED = "red"
    BLUE = "blue"


class Priority(IntEnum):
    LOW = 1
    HIGH = 2


class Mode(StrEnum):
    FAST = "fast"
    SLOW = "slow"


@dataclass
class Reading:
    value: int


def reading_editor(datatype: type[Reading], parent: QWidget | None) -> Editor[Reading]:
    widget = QSpinBox(parent)
    return Editor(
        widget,
        lambda: datatype(widget.value()),
        lambda value: widget.setValue(0 if value is None else value.value),
        widget.valueChanged,
    )


@pytest.fixture
def make_form(qtbot, make_input_model):
    def make(graph: rt.GraphDefinitionRT, registry: EditorRegistry | None = None):
        model = make_input_model(graph)
        form = FormView()
        qtbot.addWidget(form)
        form.setItemDelegate(NodeInputDelegate(form, editor_registry=registry))
        form.setModel(model)
        form.setRootIndex(model.index(0, 0))
        form.show()
        return model, form
    return make


@pytest.mark.parametrize("datatype", [Color, Priority, Mode])
def test_enum_editing_and_clearing_preserve_enum_members(make_form, datatype: type[Enum]) -> None:
    graph = rt.GraphDefinitionRT()
    first, second = list(datatype)

    @graph.node()
    def operation(value: datatype = first) -> object:
        return value

    model, form = make_form(graph)
    node = graph.nodes()[0]
    wrapper = form._mapper.mappedWidgetAt(0)
    assert isinstance(wrapper.editor, QComboBox)
    assert wrapper.editor.currentText() == first.name
    assert node.get_inputs() == ((), {})
    wrapper.editor.setCurrentIndex(1)
    assert node.get_inputs()[1]["value"] is second
    assert model.index(0, 1, model.index(0, 0)).data(Qt.ItemDataRole.EditRole) is second
    wrapper.clear_button.click()
    assert wrapper.editor.currentText() == first.name
    form._mapper.submit()
    assert node.get_inputs() == ((), {})


def test_required_enum_starts_without_selecting_a_value(make_form) -> None:
    graph = rt.GraphDefinitionRT()

    @graph.node()
    def operation(value: Color) -> Color:
        return value

    _, form = make_form(graph)
    wrapper = form._mapper.mappedWidgetAt(0)
    assert wrapper.editor.currentIndex() == -1
    form._mapper.submit()
    assert graph.nodes()[0].get_inputs() == ((), {})
    wrapper.editor.setCurrentIndex(0)
    assert graph.nodes()[0].get_inputs()[1]["value"] is Color.RED
    wrapper.clear_button.click()
    assert wrapper.editor.currentIndex() == -1


def test_path_editor_stores_paths_and_restores_defaults(make_form) -> None:
    graph = rt.GraphDefinitionRT()
    default = Path("before.txt")

    @graph.node()
    def operation(value: Path = default) -> Path:
        return value

    model, form = make_form(graph)
    wrapper = form._mapper.mappedWidgetAt(0)
    assert isinstance(wrapper.editor, QLineEdit)
    assert wrapper.editor.text() == ""
    assert wrapper.editor.placeholderText() == str(default)
    wrapper.editor.setText("after.txt")
    value = graph.nodes()[0].get_inputs()[1]["value"]
    assert isinstance(value, Path) and value == Path("after.txt")
    assert model.index(0, 1, model.index(0, 0)).data(Qt.ItemDataRole.EditRole) is value
    wrapper.clear_button.click()
    assert wrapper.editor.text() == ""
    assert wrapper.editor.placeholderText() == str(default)
    form._mapper.submit()
    assert graph.nodes()[0].get_inputs() == ((), {})


def test_custom_registration_replaces_read_only_editor_and_round_trips_objects(make_form) -> None:
    graph = rt.GraphDefinitionRT()
    default = Reading(3)

    @graph.node()
    def operation(value: Reading = default) -> Reading:
        return value

    registry = EditorRegistry()
    model, form = make_form(graph, registry)
    wrapper = form._mapper.mappedWidgetAt(0)
    assert wrapper.editor.isReadOnly()
    registry.register_editor(Reading, reading_editor)
    form._mapper.revert()
    assert isinstance(wrapper.editor, QSpinBox)
    assert wrapper.editor.isVisible()
    assert wrapper.editor.value() == 3
    assert graph.nodes()[0].get_inputs() == ((), {})
    wrapper.editor.setValue(8)
    assert graph.nodes()[0].get_inputs() == ((), {"value": Reading(8)})
    instance = Reading(12)
    index = model.index(0, 1, model.index(0, 0))
    assert model.setData(index, instance)
    assert graph.nodes()[0].get_inputs()[1]["value"] is instance
    assert wrapper.editor.value() == 12
    assert not model.setData(index, "not a Reading")
    wrapper.clear_button.click()
    assert wrapper.editor.value() == 3
    form._mapper.submit()
    assert graph.nodes()[0].get_inputs() == ((), {})


def test_custom_editor_can_handle_an_unset_type_without_a_zero_argument_constructor(make_form) -> None:
    graph = rt.GraphDefinitionRT()

    @graph.node()
    def operation(value: Reading) -> Reading:
        return value

    registry = EditorRegistry()
    registry.register_editor(Reading, reading_editor)
    _, form = make_form(graph, registry)
    wrapper = form._mapper.mappedWidgetAt(0)
    form._mapper.submit()
    assert graph.nodes()[0].get_inputs() == ((), {})
    wrapper.editor.setValue(4)
    assert graph.nodes()[0].get_inputs() == ((), {"value": Reading(4)})


@pytest.mark.parametrize("default", ["hello", Path("file.txt"), 7, 1.5, False, Color.RED])
def test_defaults_are_styled_but_explicit_equal_values_are_not(make_form, default: object) -> None:
    graph = rt.GraphDefinitionRT()
    datatype = type(default)

    @graph.node()
    def operation(value: datatype = default) -> object:
        return value

    model, form = make_form(graph)
    wrapper = form._mapper.mappedWidgetAt(0)
    widget = wrapper.editor
    assert widget.property("usingDefault") is True
    assert widget.font().italic()
    assert widget.palette().color(QPalette.ColorRole.Text) == widget.palette().color(QPalette.ColorRole.Mid)
    if isinstance(widget, QLineEdit):
        assert widget.text() == ""
        assert widget.placeholderText() == str(default)
    form._mapper.submit()
    assert graph.nodes()[0].get_inputs() == ((), {})

    index = model.index(0, 1, model.index(0, 0))
    assert model.setData(index, default)
    assert widget.property("usingDefault") is False
    assert not widget.font().italic()
    if isinstance(widget, QLineEdit):
        assert widget.text() == str(default)
        assert widget.placeholderText() == ""

    wrapper.clear_button.click()
    assert widget.property("usingDefault") is True
    assert widget.font().italic()
    form._mapper.submit()
    assert graph.nodes()[0].get_inputs() == ((), {})


def test_empty_string_is_an_explicit_value_until_cleared(make_form) -> None:
    graph = rt.GraphDefinitionRT()

    @graph.node()
    def operation(value: str = "default") -> str:
        return value

    _, form = make_form(graph)
    wrapper = form._mapper.mappedWidgetAt(0)
    wrapper.editor.setText("typed")
    wrapper.editor.clear()
    assert graph.nodes()[0].get_inputs() == ((), {"value": ""})
    assert wrapper.editor.property("usingDefault") is False
    assert wrapper.editor.placeholderText() == ""
    wrapper.clear_button.click()
    assert graph.nodes()[0].get_inputs() == ((), {})
    assert wrapper.editor.placeholderText() == "default"
