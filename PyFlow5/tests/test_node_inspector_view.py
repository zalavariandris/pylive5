import pygraphrt as rt
import pytest
from qtpy.QtCore import QItemSelectionModel, Qt
from qtpy.QtTest import QTest
from qtpy.QtWidgets import QCheckBox, QDoubleSpinBox, QLabel, QLineEdit, QSpinBox

from pyflow5.formview import FormView
from pyflow5.node_inspector_view import NodeInspectorView
from pyflow5.properties_editor.node_input_delegate import NodeInputWidget


@pytest.fixture
def inspector(qtbot, make_input_model):
    graph = rt.GraphDefinitionRT()

    @graph.node(count=12, label="before", enabled=True, scale=2.5)
    def operation(
        count: int = 7, label: str = "default", enabled: bool = False,
        scale: float = 1.5,
    ) -> str:
        return label * count

    model = make_input_model(graph)
    view = NodeInspectorView()
    qtbot.addWidget(view)
    view.setModel(model)
    selection = QItemSelectionModel(model, view)
    view.setSelectionModel(selection)
    view.show()
    selection.select(model.index(0, 0), QItemSelectionModel.SelectionFlag.ClearAndSelect)
    return graph.nodes()[0], model, view, selection


@pytest.mark.parametrize(
    ("row", "name", "editor_type", "default", "replacement"),
    [
        (0, "count", QSpinBox, 7, -120),
        (1, "label", QLineEdit, "default", "after"),
        (2, "enabled", QCheckBox, False, True),
        (3, "scale", QDoubleSpinBox, 1.5, -200.5),
    ],
)
def test_form_clears_defaults_and_can_edit_again(
    inspector, row, name, editor_type, default, replacement,
) -> None:
    node, model, view, _ = inspector
    form = view.findChild(FormView)
    wrapper = form._mapper.mappedWidgetAt(row)
    assert isinstance(wrapper, NodeInputWidget)
    assert isinstance(wrapper.editor, editor_type)
    assert wrapper.editor.isVisible()
    assert wrapper.editor.height() > 0
    assert wrapper.clear_button.isVisible()

    QTest.mouseClick(wrapper.clear_button, Qt.MouseButton.LeftButton)

    assert name not in node.get_inputs()[1]
    index = model.index(row, 1, model.index(0, 0))
    assert index.data(Qt.ItemDataRole.EditRole) == default
    assert wrapper.isVisible()
    if isinstance(wrapper.editor, QLineEdit):
        assert wrapper.editor.text() == ""
        assert wrapper.editor.placeholderText() == default
    elif isinstance(wrapper.editor, QCheckBox):
        assert wrapper.editor.isChecked() == default
    else:
        assert wrapper.editor.value() == default

    # Neither focus changes nor submitting the form should restore the cleared input.
    QTest.keyClick(wrapper.editor, Qt.Key.Key_Tab)
    form._mapper.submit()
    assert name not in node.get_inputs()[1]

    if isinstance(wrapper.editor, QLineEdit):
        wrapper.editor.selectAll()
        QTest.keyClicks(wrapper.editor, replacement)
    elif isinstance(wrapper.editor, QCheckBox):
        wrapper.editor.setChecked(replacement)
    else:
        wrapper.editor.setValue(replacement)
    assert node.get_inputs()[1][name] == replacement


def test_form_hides_when_selection_is_cleared(inspector) -> None:
    _, _, view, selection = inspector
    form = view.findChild(FormView)
    assert form.isVisible()
    selection.clearSelection()
    assert not form.isVisible()


def test_clear_buttons_follow_rows_after_removal(qtbot, make_input_model) -> None:
    graph = rt.GraphDefinitionRT()
    node = graph._create_node(kwargs={"first": 1, "last": 2})
    model = make_input_model(graph)
    view = NodeInspectorView()
    qtbot.addWidget(view)
    view.setModel(model)
    selection = QItemSelectionModel(model, view)
    view.setSelectionModel(selection)
    selection.select(model.index(0, 0), QItemSelectionModel.SelectionFlag.ClearAndSelect)
    form = view.findChild(FormView)
    first = form._mapper.mappedWidgetAt(0)
    last = form._mapper.mappedWidgetAt(1)

    first.clear_button.click()
    assert node.get_inputs() == ((), {"last": 2})
    assert form._mapper.mappedWidgetAt(0) is last
    last.clear_button.click()
    assert node.get_inputs() == ((), {})
    assert form._layout.rowCount() == 0


def test_linked_input_is_a_label_and_can_be_cleared(qtbot, make_input_model) -> None:
    graph = rt.GraphDefinitionRT()
    source = graph._create_node()

    @graph.node(input=source)
    def operation(input: str = "default") -> str:
        return input

    target = graph.nodes()[1]
    model = make_input_model(graph)
    view = NodeInspectorView()
    qtbot.addWidget(view)
    view.setModel(model)
    selection = QItemSelectionModel(model, view)
    view.setSelectionModel(selection)
    selection.select(
        model.mapFromSource(target.get_name()),
        QItemSelectionModel.SelectionFlag.ClearAndSelect,
    )
    form = view.findChild(FormView)
    wrapper = form._mapper.mappedWidgetAt(0)
    assert isinstance(wrapper.editor, QLabel)
    assert wrapper.editor.textFormat() == Qt.TextFormat.PlainText
    assert wrapper.editor.text() == f"-> {source.get_name()}"
    wrapper.clear_button.click()
    assert target.get_inputs() == ((), {})
    assert not wrapper.editor.isReadOnly()
    assert wrapper.editor.text() == ""
    assert wrapper.editor.placeholderText() == "default"
    wrapper.editor.selectAll()
    QTest.keyClicks(wrapper.editor, "replacement")
    assert target.get_inputs() == ((), {"input": "replacement"})
    target.set_inputs(input=source)
    assert isinstance(wrapper.editor, QLabel)
    assert wrapper.editor.text() == f"-> {source.get_name()}"
    form._mapper.submit()
    assert target.get_inputs() == ((), {"input": source})
