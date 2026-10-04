import pytest
import pygraphrt as rt
from qtpy.QtCore import Qt
from qtpy.QtGui import QPalette
from qtpy.QtTest import QTest
from qtpy.QtWidgets import QLineEdit, QSpinBox, QStyle, QStyleOptionViewItem, QTreeView

from pyflow5.inspector.node_input_delegate import NodeInputDelegate, NodeInputWidget
from pyflow5.inspector.pygraphrt_nodes_inputs_tree_model import NodesTreeAdapterModel


@pytest.fixture
def input_graph():
    graph = rt.GraphDefinitionRT()

    @graph.node(7, "before")
    def transform(count: int, label: str) -> str:
        return label * count

    node_ref = graph.nodes()[0]
    model = NodesTreeAdapterModel(graph, rt.ModuleRegistry())
    return node_ref, model


@pytest.fixture
def tree_view(qtbot, input_graph):
    _, model = input_graph
    view = QTreeView()
    qtbot.addWidget(view)
    view.setItemDelegateForColumn(1, NodeInputDelegate(view))
    view.setModel(model)
    view.resize(640, 240)
    view.setColumnWidth(1, 320)
    view.expandAll()
    view.show()
    return view


@pytest.mark.parametrize(
    ("input_row", "editor_type"),
    [(0, QSpinBox), (1, QLineEdit)],
)
def test_wrapped_editor_and_clear_button_are_visible_and_fill_cell(
    qtbot, input_graph, tree_view, input_row, editor_type,
):
    _, model = input_graph
    view = tree_view
    index = model.index(input_row, 1, model.index(0, 0))

    view.edit(index)
    qtbot.waitUntil(lambda: view.findChild(NodeInputWidget) is not None)
    wrapper = view.findChild(NodeInputWidget)
    qtbot.waitUntil(lambda: wrapper.editor.isVisible())

    assert isinstance(wrapper.editor, editor_type)
    assert wrapper.isVisible()
    assert wrapper.clear_button.isVisible()
    assert wrapper.editor.width() > 0
    assert wrapper.clear_button.width() == wrapper.clear_button.sizeHint().width()
    assert wrapper.editor.height() == wrapper.contentsRect().height()
    assert wrapper.clear_button.height() == wrapper.contentsRect().height()
    assert (
        wrapper.editor.geometry().right() + 1
        == wrapper.clear_button.geometry().left()
    )


@pytest.mark.parametrize(
    ("input_row", "value"),
    [(0, 23), (1, "after")],
)
def test_delegate_commits_int_and_string_values(
    qtbot, input_graph, tree_view, input_row, value,
):
    node_ref, model = input_graph
    view = tree_view
    index = model.index(input_row, 1, model.index(0, 0))

    view.edit(index)
    qtbot.waitUntil(lambda: view.findChild(NodeInputWidget) is not None)
    wrapper = view.findChild(NodeInputWidget)
    qtbot.waitUntil(
        lambda: (
            wrapper.editor.value() == 7
            if isinstance(wrapper.editor, QSpinBox)
            else wrapper.editor.text() == "before"
        )
    )

    if isinstance(wrapper.editor, QSpinBox):
        wrapper.editor.setValue(value)
    else:
        wrapper.editor.setText(value)

    QTest.keyClick(wrapper.editor, Qt.Key.Key_Return)
    qtbot.waitUntil(
        lambda: node_ref.get_inputs()[0][input_row] == value
    )
    assert node_ref.get_inputs()[0][input_row] == value


def test_line_edit_updates_model_for_each_keystroke(qtbot, input_graph, tree_view):
    node_ref, model = input_graph
    index = model.index(1, 1, model.index(0, 0))
    updates = []
    model.dataChanged.connect(
        lambda *_args: updates.append(node_ref.get_inputs()[0][1])
    )

    tree_view.edit(index)
    qtbot.waitUntil(lambda: tree_view.findChild(NodeInputWidget) is not None)
    wrapper = tree_view.findChild(NodeInputWidget)
    qtbot.waitUntil(lambda: wrapper.editor.text() == "before")
    wrapper.editor.selectAll()

    QTest.keyClicks(wrapper.editor, "ok")

    assert node_ref.get_inputs()[0][1] == "ok"
    assert updates == ["o", "ok"]
    assert wrapper.isVisible()


def test_spin_box_updates_model_without_committing_initial_value(
    qtbot, input_graph, tree_view,
):
    node_ref, model = input_graph
    index = model.index(0, 1, model.index(0, 0))
    updates = []
    model.dataChanged.connect(
        lambda *_args: updates.append(node_ref.get_inputs()[0][0])
    )

    tree_view.edit(index)
    qtbot.waitUntil(lambda: tree_view.findChild(NodeInputWidget) is not None)
    wrapper = tree_view.findChild(NodeInputWidget)
    qtbot.waitUntil(lambda: wrapper.editor.value() == 7)
    assert updates == []

    QTest.keyClick(wrapper.editor, Qt.Key.Key_Up)

    assert node_ref.get_inputs()[0][0] == 8
    assert updates == [8]
    assert wrapper.isVisible()


def test_default_value_uses_dim_text_when_selected(qtbot):
    graph = rt.GraphDefinitionRT()

    @graph.node()
    def with_default(count: int = 7) -> int:
        return count

    model = NodesTreeAdapterModel(graph, rt.ModuleRegistry())
    index = model.index(0, 1, model.index(0, 0))
    option = QStyleOptionViewItem()
    option.state |= QStyle.StateFlag.State_Selected
    dim_text = option.palette.color(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.Text,
    )

    NodeInputDelegate().initStyleOption(option, index)

    assert option.palette.color(
        QPalette.ColorGroup.Active,
        QPalette.ColorRole.HighlightedText,
    ) == dim_text
    assert option.font.italic()


def test_clear_button_removes_input_through_model_set_data(
    qtbot, input_graph, tree_view,
):
    node_ref, model = input_graph
    index = model.index(1, 1, model.index(0, 0))

    tree_view.edit(index)
    qtbot.waitUntil(lambda: tree_view.findChild(NodeInputWidget) is not None)
    wrapper = tree_view.findChild(NodeInputWidget)

    QTest.mouseClick(wrapper.clear_button, Qt.MouseButton.LeftButton)

    qtbot.waitUntil(lambda: node_ref.get_inputs() == ((7,), {}))