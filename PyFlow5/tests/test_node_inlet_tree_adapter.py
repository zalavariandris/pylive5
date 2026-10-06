from pathlib import Path

import pygraphrt as rt
import pytest
from pygraphrt.abstract_operator import ParameterData
from pygraphrt.script_module import ScriptOperatorRef
from qdageditor5.adapters.node_inlet_tree_model_adapter import NodeInletTreeModelAdapter
from qtpy.QtCore import QModelIndex, QPersistentModelIndex, Qt

from pyflow5.nodert_input_roles import NodeRTInputRole


def test_tree_contract_and_persistent_indexes(qtmodeltester, make_input_model) -> None:
    graph = rt.GraphDefinitionRT()
    first = graph._create_node(args=(1, 2))
    second = graph._create_node(args=(3,))
    model = make_input_model(graph)
    qtmodeltester.check(model)

    parent = model.mapFromSource(second.get_name())
    value = QPersistentModelIndex(model.index(0, 1, parent))
    assert model.rowCount(model.index(0, 1)) == 0
    assert model.rowCount(QModelIndex(value)) == 0
    assert value.parent() == parent
    assert model.mapToSource(QModelIndex(value)) == second.get_name()
    assert not model.index(-1, 0).isValid()
    assert not model.index(0, 2).isValid()
    assert not model.index(0, 0, QModelIndex(value)).isValid()

    graph._delete_node(first)
    assert value.isValid()
    assert value.parent().row() == 0
    assert value.data() == 3
    second.set_inputs(3, 4)
    assert value.isValid()
    assert model.rowCount(value.parent()) == 2


def test_source_replacement_disconnects_old_graph(qtmodeltester, make_input_model) -> None:
    old_graph = rt.GraphDefinitionRT()
    old_graph._create_node(args=(1,))
    model = make_input_model(old_graph)
    qtmodeltester.check(model)
    old_index = QPersistentModelIndex(model.index(0, 0))

    new_graph = rt.GraphDefinitionRT()
    new_graph._create_node(args=(20,))
    other_model = make_input_model(new_graph)
    model.setSourceGraph(other_model.sourceGraph())
    assert not old_index.isValid()
    old_graph._create_node(args=(2,))
    assert model.rowCount() == 1
    assert model.index(0, 1, model.index(0, 0)).data() == 20
    foreign = other_model.index(0, 0)
    assert model.rowCount(foreign) == 0
    assert model.data(foreign) is None
    assert not model.parent(foreign).isValid()
    model.setSourceGraph(None)
    new_graph._create_node()
    assert model.rowCount() == 0


def test_base_stays_single_column_and_subclass_notifies_both(make_input_model) -> None:
    graph = rt.GraphDefinitionRT()
    node = graph._create_node(args=(1,))
    model = make_input_model(graph)
    source = model.sourceGraph()
    base = NodeInletTreeModelAdapter(source)
    assert base.columnCount() == 1
    assert base.index(0, 0, base.index(0, 0)).data() == "1"
    changes = []
    model.dataChanged.connect(lambda *args: changes.append(args))
    parent = model.index(0, 0)
    for signal, args in (
        (source.inletDataChanged, (node.get_name(), ("1",), [Qt.ItemDataRole.DisplayRole])),
        (source.linksAdded, ((("source", "out", node.get_name(), "1"),),)),
        (source.linksRemoved, ((("source", "out", node.get_name(), "1"),),)),
        (source.linksReset, ()),
    ):
        changes.clear()
        signal.emit(*args)
        assert changes == [(model.index(0, 0, parent), model.index(0, 1, parent), [])]


def test_extra_positional_inputs_keep_numeric_keywords_distinct(make_input_model) -> None:
    graph = rt.GraphDefinitionRT()
    node = graph._create_node(args=(10, 20), kwargs={"1": 30, "label": "hello"})
    model = make_input_model(graph)
    parent = model.index(0, 0)
    assert [model.index(row, 0, parent).data() for row in range(4)] == [
        "#1", "2", "1", "label"
    ]
    assert model.setData(model.index(0, 1, parent), 11)
    assert model.setData(model.index(2, 1, parent), 31)
    assert node.get_inputs() == ((11, 20), {"1": 31, "label": "hello"})
    assert model.setData(model.index(1, 1, parent), ParameterData.EMPTY)
    assert node.get_inputs() == ((11,), {"1": 31, "label": "hello"})


def test_linked_values_are_read_only_and_can_be_cleared(make_input_model) -> None:
    graph = rt.GraphDefinitionRT()
    source = graph._create_node()
    target = graph._create_node(kwargs={"input": source})
    model = make_input_model(graph)
    value = model.index(0, 1, model.mapFromSource(target.get_name()))
    assert value.data() == f"-> {source.get_name()}"
    assert value.data(Qt.ItemDataRole.EditRole) is None
    assert not model.flags(value) & Qt.ItemFlag.ItemIsEditable
    assert not model.setData(value, 1)
    assert model.setData(value, ParameterData.EMPTY)
    assert target.get_inputs() == ((), {})


@pytest.mark.parametrize("annotation, default, value, expected", [
    ("bool", False, "true", True),
    (Path, Path("before.txt"), "after.txt", Path("after.txt")),
    (int, 7, "12", 12),
])
def test_default_and_typed_editing(make_input_model, annotation, default, value, expected) -> None:
    graph = rt.GraphDefinitionRT()

    @graph.node()
    def operation(input: annotation = default):
        return input

    model = make_input_model(graph)
    index = model.index(0, 1, model.index(0, 0))
    assert index.data(NodeRTInputRole.IsUsingDefaultRole)
    assert index.data(Qt.ItemDataRole.EditRole) == (str(default) if annotation is Path else default)
    assert model.setData(index, value)
    assert graph.nodes()[0].get_inputs()[1]["input"] == expected
    assert not index.data(NodeRTInputRole.IsUsingDefaultRole)
    assert model.setData(index, ParameterData.EMPTY)
    assert index.data(NodeRTInputRole.IsUsingDefaultRole)


def test_operator_reload_updates_rows_defaults_and_annotations(qtmodeltester, make_input_model) -> None:
    registry = rt.ModuleRegistry()
    module = rt.ScriptModuleRT("test")
    module.set_script("def operation(first: int = 1, last: int = 3): return first + last")
    registry.add_module(module)
    graph = rt.GraphDefinitionRT()
    graph._create_node(ScriptOperatorRef(module, "operation"))
    model = make_input_model(graph, registry)
    qtmodeltester.check(model)
    parent = model.index(0, 0)
    last = QPersistentModelIndex(model.index(1, 1, parent))
    resets = []
    model.modelReset.connect(lambda: resets.append(True))

    module.set_script(
        "def operation(first: float = 1.5, middle: int = 2, last: int = 4): return first + middle + last"
    )
    assert model.rowCount(parent) == 3
    assert last.isValid() and last.row() == 2
    assert last.data() == "4"
    assert model.index(0, 1, parent).data(NodeRTInputRole.AnnotationRole) is float
    assert resets == []


def test_graph_model_mutations_do_not_duplicate_rows(make_input_model) -> None:
    graph = rt.GraphDefinitionRT()

    @graph.node(1)
    def operation(value: int) -> int:
        return value

    model = make_input_model(graph)
    source = model.sourceGraph()
    inserted, removed = [], []
    model.rowsInserted.connect(lambda *args: inserted.append(args))
    model.rowsRemoved.connect(lambda *args: removed.append(args))
    source.addNode(graph.nodes()[0].get_operator())
    assert inserted == [(QModelIndex(), 1, 1)]
    source.removeNodes([graph.nodes()[1].get_name()])
    assert removed == [(QModelIndex(), 1, 1)]
    source.reset_graph_from_scratch()
    assert model.rowCount() == 1


def test_window_uses_the_value_adapter_in_both_trees(qtbot) -> None:
    from pyflow5.properties_editor.node_input_delegate import NodeInputDelegate
    from pyflow5.pyflow5_document import PyFlowDocument
    from pyflow5.pyflow5_window import PyFlow5Window

    graph = rt.GraphDefinitionRT()

    @graph.node(7)
    def operation(value: int) -> int:
        return value

    window = PyFlow5Window()
    qtbot.addWidget(window)
    document = PyFlowDocument(graph)
    window._connectDocument(document)
    model = document.node_inlet_tree_adapter
    for view in (window._node_tree_view, window._node_inlet_treeview):
        assert view.model() is model
        assert isinstance(view.itemDelegateForColumn(1), NodeInputDelegate)

    node = graph.nodes()[0]
    document.graphselection_model.setCurrentNode(node.get_name())
    parent = model.mapFromSource(node.get_name())
    assert window._node_tree_view.rootIndex() == parent
    assert model.setData(model.index(0, 1, parent), 9)
    assert node.get_inputs() == ((9,), {})
