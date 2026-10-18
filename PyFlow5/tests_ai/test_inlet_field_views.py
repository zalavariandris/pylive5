from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Annotated

import numpy as np
import pygraphrt as rt
import pytest
from pygraphrt.graph_evaluator import GraphEvaluator, InlineExecutionBackend
from pytestqt.qtbot import QtBot
from qtpy.QtCore import QItemSelectionModel, QModelIndex, Qt
from qtpy.QtWidgets import QApplication, QLineEdit, QSpinBox, QStyleOptionViewItem, QTreeView

from pyflow5.core.input_roles import InputDataRole
from pyflow5.models.pygraphrt_graphmodel import PyGraphRTGraphModel
from pyflow5.models.pygraphrt_node_inlet_tree_model_adapter import PyGraphRTNodeInletTreeModelAdapter
from pyflow5.views.node_input_delegate import NodeInputFieldDelegate
from pyflow5.views.node_inspector_view import NodeInspectorView
from pyflow5.views.viewer_view import Viewer


@pytest.fixture
def make_model(qapp: object) -> Iterator[Callable[[rt.GraphDefinitionRT], PyGraphRTNodeInletTreeModelAdapter]]:
    models: list[PyGraphRTGraphModel] = []
    evaluators: list[GraphEvaluator] = []

    def make(graph: rt.GraphDefinitionRT) -> PyGraphRTNodeInletTreeModelAdapter:
        registry = rt.ModuleRegistry()
        invalidator = rt.GraphInvalidator(graph, registry)
        evaluator = GraphEvaluator(graph, InlineExecutionBackend(), invalidator=invalidator)
        source = PyGraphRTGraphModel(graph, registry, invalidator, evaluator)
        models.append(source)
        evaluators.append(evaluator)
        return PyGraphRTNodeInletTreeModelAdapter(source)

    yield make
    for model in models:
        model.close()
    for evaluator in evaluators:
        evaluator.close()


def test_labels_fields_and_source_writes(make_model: Callable) -> None:
    graph = rt.GraphDefinitionRT()

    @graph.node(7)
    def operation(count: int, label: str = "default") -> int:
        return count

    model = make_model(graph)
    source = model.sourceGraph()
    node = graph.nodes()[0]
    root = model.mapFromSource(node.get_name())
    field = model.index(0, 1, root)
    default = model.index(1, 1, root)
    assert root.data() == "operation"
    assert model.index(0, 0, root).data() == "count"
    assert field.data() == "7"
    assert field.data(Qt.ItemDataRole.EditRole) == 7
    assert field.data(InputDataRole.AnnotationRole) is int
    assert field.data(InputDataRole.InputLocationRole) == 0
    assert default.data(Qt.ItemDataRole.EditRole) == "default"
    assert default.data(InputDataRole.IsUsingDefaultRole)

    assert model.setData(field, "12")
    assert node.get_inputs() == ((12,), {})
    assert source.setInletData(node.get_name(), "label", "after", InputDataRole.InputValueRole)
    assert default.data(Qt.ItemDataRole.EditRole) == "after"
    assert model.setData(default, rt.ParameterData.EMPTY)
    assert default.data(Qt.ItemDataRole.EditRole) == "default"
    assert not model.setData(model.index(0, 0, root), "rename")
    assert not model.setData(field, "invalid int")
    assert not source.setInletData(node.get_name(), "missing", 1, InputDataRole.InputValueRole)
    assert not model.flags(QModelIndex())


@pytest.mark.parametrize("annotation, default, replacement, expected", [
    ("bool", False, "true", True),
    (Path, Path("before"), "after", Path("after")),
    (Annotated[tuple[int, int], "size"], (1, 2), (3.0, 4.0), (3, 4)),
])
def test_source_preserves_type_conversion(
    make_model: Callable, annotation: object, default: object,
    replacement: object, expected: object,
) -> None:
    graph = rt.GraphDefinitionRT()

    @graph.node()
    def operation(value: annotation = default) -> object:
        return value

    model = make_model(graph)
    field = model.index(0, 1, model.index(0, 0))
    assert model.setData(field, replacement)
    assert graph.nodes()[0].get_inputs()[1]["value"] == expected


def test_numeric_keywords_and_positional_clear(make_model: Callable) -> None:
    graph = rt.GraphDefinitionRT()
    node = graph._create_node(args=(10, 20), kwargs={"1": 30})
    model = make_model(graph)
    root = model.index(0, 0)
    assert model.index(0, 0, root).data() == "#1"
    assert model.setData(model.index(0, 1, root), 11)
    assert model.setData(model.index(2, 1, root), 31)
    assert node.get_inputs() == ((11, 20), {"1": 31})
    assert model.setData(model.index(0, 1, root), rt.ParameterData.EMPTY)
    assert node.get_inputs() == ((20,), {"1": 31})


def test_none_false_and_empty_string_are_explicit_values(make_model: Callable) -> None:
    graph = rt.GraphDefinitionRT()
    graph._create_node(kwargs={"nothing": None, "disabled": False, "empty": ""})
    model = make_model(graph)
    for row, expected in enumerate((None, False, "")):
        field = model.index(row, 1, model.index(0, 0))
        assert field.data(InputDataRole.InputIsSetRole)
        assert not field.data(InputDataRole.IsUsingDefaultRole)
        assert field.data(Qt.ItemDataRole.EditRole) == expected


def test_linked_input_is_read_only_and_clearable(make_model: Callable) -> None:
    graph = rt.GraphDefinitionRT()
    upstream = graph._create_node()
    target = graph._create_node(kwargs={"value": upstream})
    model = make_model(graph)
    field = model.index(0, 1, model.mapFromSource(target.get_name()))
    assert field.data() == f"-> {upstream.get_name()}"
    assert field.data(InputDataRole.ConnectionRole) == upstream.get_name()
    assert field.data(InputDataRole.InputIsSetRole)
    assert not model.setData(field, 1)
    assert not model.flags(field) & Qt.ItemFlag.ItemIsEditable
    assert model.setData(field, rt.ParameterData.EMPTY)
    assert target.get_inputs() == ((), {})


def test_inspector_loads_fields_and_defaults(qtbot: QtBot, make_model: Callable) -> None:
    graph = rt.GraphDefinitionRT()

    @graph.node(count=12)
    def operation(count: int = 7, label: str = "default") -> int:
        return count

    model = make_model(graph)
    inspector = NodeInspectorView()
    qtbot.addWidget(inspector)
    inspector.setModel(model)
    selection = QItemSelectionModel(model, inspector)
    inspector.setSelectionModel(selection)
    selection.select(model.index(0, 0), QItemSelectionModel.SelectionFlag.ClearAndSelect)
    form = inspector._form_view
    count_editor = form._mapper.mappedWidgetAt(0)
    label_editor = form._mapper.mappedWidgetAt(1)
    assert isinstance(count_editor, QSpinBox)
    assert isinstance(label_editor, QLineEdit)
    assert count_editor.value() == 12
    assert label_editor.text() == "default"
    count_editor.setValue(23)
    assert graph.nodes()[0].get_inputs()[1]["count"] == 23
    assert model.setData(model.index(0, 1, model.index(0, 0)), rt.ParameterData.EMPTY)
    assert count_editor.value() == 7
    form._mapper.submit()
    assert graph.nodes()[0].get_inputs() == ((), {})


def test_viewer_reads_node_execution_or_inlet_field(qtbot: QtBot, make_model: Callable) -> None:
    graph = rt.GraphDefinitionRT()

    @graph.node(count=7)
    def operation(count: int) -> int:
        return count

    node = graph.nodes()[0]
    model = make_model(graph)
    source = model.sourceGraph()
    result = np.zeros((3, 5, 4), dtype=np.float32)
    source._on_evaluated({node: rt.ExecutionSuccess(node, result)})
    viewer = Viewer()
    qtbot.addWidget(viewer)
    viewer.setModel(model)
    selection = QItemSelectionModel(model, viewer)
    viewer.setSelectionModel(selection)
    root = model.index(0, 0)
    assert root.data() == "operation"
    assert root.data(Qt.ItemDataRole.EditRole) is None
    assert root.data(source.ExecutionRole) is result
    for role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole, source.ExecutionRole):
        assert root.siblingAtColumn(1).data(role) is None
    selection.setCurrentIndex(root, QItemSelectionModel.SelectionFlag.NoUpdate)
    assert viewer._body_widget._cached_data is result
    assert viewer._lock_switch.text().endswith("operation")
    canvas = viewer._body_widget._stack.currentWidget()
    assert canvas.item.hasImage()
    assert canvas.item.boundingRect().width() == 5
    assert canvas.item.boundingRect().height() == 3
    selection.setCurrentIndex(QModelIndex(), QItemSelectionModel.SelectionFlag.NoUpdate)
    selection.setCurrentIndex(root, QItemSelectionModel.SelectionFlag.NoUpdate)
    assert viewer._body_widget._stack.currentWidget() is canvas
    selection.setCurrentIndex(root.siblingAtColumn(1), QItemSelectionModel.SelectionFlag.NoUpdate)
    assert viewer._body_widget._cached_data is result
    updated_result = np.ones_like(result)
    source._on_evaluated({node: rt.ExecutionSuccess(node, updated_result)})
    assert viewer._body_widget._cached_data is updated_result

    field = model.index(0, 1, root)
    selection.setCurrentIndex(field, QItemSelectionModel.SelectionFlag.NoUpdate)
    assert viewer._body_widget._cached_data == 7
    assert viewer._lock_switch.text().endswith("count")
    assert model.setData(field, 9)
    assert viewer._body_widget._cached_data == 9
    viewer._body_widget.display("stale")
    model.dataChanged.emit(field, field, [Qt.ItemDataRole.EditRole])
    assert viewer._body_widget._cached_data == 9


def test_viewer_shows_connection_field(qtbot: QtBot, make_model: Callable) -> None:
    graph = rt.GraphDefinitionRT()
    upstream = graph._create_node()
    target = graph._create_node(kwargs={"value": upstream})
    model = make_model(graph)
    viewer = Viewer()
    qtbot.addWidget(viewer)
    viewer.setModel(model)
    selection = QItemSelectionModel(model, viewer)
    label = model.index(0, 0, model.mapFromSource(target.get_name()))
    selection.setCurrentIndex(label, QItemSelectionModel.SelectionFlag.NoUpdate)
    viewer.setSelectionModel(selection)
    assert viewer._body_widget._cached_data == f"-> {upstream.get_name()}"


def test_clear_buttons_follow_inlet_rows(qtbot: QtBot, make_model: Callable) -> None:
    graph = rt.GraphDefinitionRT()
    node = graph._create_node(kwargs={"first": 1, "last": 2})
    model = make_model(graph)
    inspector = NodeInspectorView()
    qtbot.addWidget(inspector)
    inspector.setModel(model)
    selection = QItemSelectionModel(model, inspector)
    selection.select(model.index(0, 0), QItemSelectionModel.SelectionFlag.ClearAndSelect)
    inspector.setSelectionModel(selection)
    form = inspector._form_view
    first_label = form._layout.labelForField(form._mapper.mappedWidgetAt(0))
    last_label = form._layout.labelForField(form._mapper.mappedWidgetAt(1))
    first_label.clearRequested.emit()
    assert node.get_inputs() == ((), {"last": 2})
    last_label.clearRequested.emit()
    assert node.get_inputs() == ((), {})
    assert form._layout.rowCount() == 0


def test_window_shares_tree_fields_with_viewer_and_inspector(qtbot: QtBot) -> None:
    from pyflow5.models.pyflow5_document import PyFlowDocument
    from pyflow5.views.pyflow5_window import PyFlow5Window

    graph = rt.GraphDefinitionRT()

    @graph.node(count=7)
    def operation(count: int) -> int:
        return count * 2

    window = PyFlow5Window(use_session=False)
    qtbot.addWidget(window)
    document = PyFlowDocument(engine=rt.PyGraphEngine(graph=graph))
    window._connectDocument(document)
    model = document.node_inlet_tree_adapter
    selection = document.node_inlet_tree_selection_adapter
    assert window._node_tree_view.model() is model
    assert window._node_tree_view.selectionModel() is selection
    assert window._viewer.model() is model
    assert window._node_inspector.model() is model
    node = graph.nodes()[0]
    document.graphselection_model.setCurrentNode(node.get_name())
    document.graphselection_model.selectNodes({node.get_name()})
    qtbot.waitUntil(lambda: window._viewer._body_widget._cached_data == 14)

    root = model.mapFromSource(node.get_name())
    selection.setCurrentIndex(model.index(0, 1, root), QItemSelectionModel.SelectionFlag.NoUpdate)
    assert window._viewer._body_widget._cached_data == 7
    assert window._node_inspector._form_view.rootIndex() == root
    editor = window._node_inspector._form_view._mapper.mappedWidgetAt(0)
    editor.setValue(9)
    assert window._viewer._body_widget._cached_data == 9
    qtbot.waitUntil(lambda: root.data(PyGraphRTGraphModel.ExecutionRole) == 18)
    assert root.siblingAtColumn(1).data(Qt.ItemDataRole.EditRole) is None
    assert window._viewer._body_widget._cached_data == 9
    window.close()


def test_path_editor_loads_default_without_setting_input(qtbot: QtBot, make_model: Callable) -> None:
    graph = rt.GraphDefinitionRT()

    @graph.node()
    def operation(path: Path = Path("before.txt")) -> Path:
        return path

    model = make_model(graph)
    field = model.index(0, 1, model.index(0, 0))
    delegate = NodeInputFieldDelegate()
    editor = delegate.createEditor(None, QStyleOptionViewItem(), field)
    qtbot.addWidget(editor)
    delegate.setEditorData(editor, field)
    assert editor.text() == "before.txt"
    delegate.setModelData(editor, model, field)
    assert graph.nodes()[0].get_inputs() == ((), {})
    editor.setText("after.txt")
    delegate.setModelData(editor, model, field)
    assert graph.nodes()[0].get_inputs()[1]["path"] == Path("after.txt")


@pytest.mark.parametrize("view_kind", ["inspector", "tree"])
def test_focused_line_edit_keeps_cursor_and_drops_refreshes(
    qtbot: QtBot, make_model: Callable, view_kind: str,
) -> None:
    graph = rt.GraphDefinitionRT()

    @graph.node(label="abcd")
    def operation(label: str) -> str:
        return label

    model = make_model(graph)
    field = model.index(0, 1, model.index(0, 0))
    if view_kind == "inspector":
        view = NodeInspectorView()
        view.setModel(model)
        selection = QItemSelectionModel(model, view)
        view.setSelectionModel(selection)
        selection.select(model.index(0, 0), QItemSelectionModel.SelectionFlag.ClearAndSelect)
        editor = view._form_view._mapper.mappedWidgetAt(0)
    else:
        view = QTreeView()
        view.setModel(model)
        view.setItemDelegateForColumn(1, NodeInputFieldDelegate(view))
        view.expandAll()
        view.openPersistentEditor(field)
        editor = view.findChild(QLineEdit)

    qtbot.addWidget(view)
    assert isinstance(editor, QLineEdit)
    view.show()
    view.activateWindow()
    editor.setFocus()
    qtbot.waitUntil(editor.hasFocus)
    assert editor.text() == "abcd"
    editor.setCursorPosition(1)
    qtbot.keyClicks(editor, "XY")
    assert editor.text() == "aXYbcd"
    assert editor.cursorPosition() == 3
    assert editor.isUndoAvailable()
    assert graph.nodes()[0].get_inputs()[1]["label"] == "aXYbcd"

    editor.setSelection(1, 2)
    assert model.setData(field, "external")
    assert editor.text() == "aXYbcd"
    assert editor.selectedText() == "XY"
    editor.clearFocus()
    QApplication.processEvents()
    assert not editor.hasFocus()
    assert editor.text() == "aXYbcd"  # Focus loss does not replay the skipped update.
    assert field.data(Qt.ItemDataRole.EditRole) == "external"

    assert model.setData(field, "later")
    assert editor.text() == "later"


def test_nested_editor_focus_allows_initial_load_then_skips_updates(
    qtbot: QtBot, make_model: Callable,
) -> None:
    graph = rt.GraphDefinitionRT()

    @graph.node(size=(10, 20))
    def operation(size: tuple[int, int]) -> tuple[int, int]:
        return size

    model = make_model(graph)
    field = model.index(0, 1, model.index(0, 0))
    delegate = NodeInputFieldDelegate()
    editor = delegate.createEditor(None, QStyleOptionViewItem(), field)
    qtbot.addWidget(editor)
    spin = editor.findChild(QSpinBox)
    assert spin is not None
    editor.show()
    editor.activateWindow()
    spin.setFocus()
    qtbot.waitUntil(spin.hasFocus)
    delegate.setEditorData(editor, field)
    assert spin.value() == 10

    assert model.setData(field, (30, 40))
    delegate.setEditorData(editor, field)
    assert spin.value() == 10
    spin.clearFocus()
    QApplication.processEvents()
    assert spin.value() == 10
    delegate.setEditorData(editor, field)
    assert spin.value() == 30
