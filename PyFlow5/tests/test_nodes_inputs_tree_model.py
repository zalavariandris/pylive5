import pygraphrt as rt
from qtpy.QtCore import QPersistentModelIndex, QModelIndex

from pyflow5.nodert_input_roles import NodeRTInputRole
from pygraphrt.abstract_operator import ParameterData


def test_clear_input_removes_and_shifts_positional_arguments(qtbot, make_input_model):
    graph = rt.GraphDefinitionRT()

    @graph.node(10, 20)
    def combine(first: int, second: int = 30) -> int:
        return first + second

    node_ref = graph.nodes()[0]
    model = make_input_model(graph)
    node_index = model.index(0, 0)
    input_index = model.index(0, 1, node_index)

    assert input_index.data(NodeRTInputRole.NodeRefRole) == node_ref
    assert input_index.data(NodeRTInputRole.InputLocationRole) == "first"
    assert model.setData(input_index, ParameterData.EMPTY)
    assert node_ref.get_inputs() == ((20,), {})
    assert model.index(0, 1, node_index).data() == 20
    assert model.index(1, 1, node_index).data() == "30"


def test_clear_input_removes_keyword_binding_and_restores_default(qtbot, make_input_model):
    graph = rt.GraphDefinitionRT()

    @graph.node(second=20)
    def combine(first: int = 10, second: int = 30) -> int:
        return first + second

    node_ref = graph.nodes()[0]
    model = make_input_model(graph)

    node_index = model.index(0, 0)
    input_index = model.index(1, 1, node_index)

    assert model.setData(input_index, ParameterData.EMPTY)
    assert node_ref.get_inputs() == ((), {})


def test_input_update_emits_data_changed_without_resetting_model(qtbot, make_input_model):
    graph = rt.GraphDefinitionRT()

    @graph.node(10, 20)
    def combine(first: int, second: int) -> int:
        return first + second

    node_ref = graph.nodes()[0]
    model = make_input_model(graph)
    node_index = model.index(0, 0)
    input_index = model.index(0, 1, node_index)
    persistent_input_index = QPersistentModelIndex(input_index)
    data_changes = []
    resets = []
    model.dataChanged.connect(
        lambda top_left, bottom_right, roles: data_changes.append(
            (top_left, bottom_right, roles)
        )
    )
    model.modelReset.connect(lambda: resets.append(True))

    assert model.setData(input_index, 15)

    assert node_ref.get_inputs() == ((15, 20), {})
    assert persistent_input_index.isValid()
    assert resets == []
    child_changes = [change for change in data_changes if change[0].parent().isValid()]
    assert len(child_changes) == 1
    top_left, bottom_right, _ = child_changes[0]
    assert top_left == model.index(0, 0, node_index)
    assert bottom_right == model.index(1, 1, node_index)


def test_node_add_and_remove_emit_row_signals_without_resetting_model(qtbot, make_input_model):
    graph = rt.GraphDefinitionRT()

    @graph.node(10)
    def first(value: int) -> int:
        return value

    model = make_input_model(graph)
    inserted_rows = []
    removed_rows = []
    resets = []
    model.rowsInserted.connect(
        lambda parent, first, last: inserted_rows.append((parent, first, last))
    )
    model.rowsRemoved.connect(
        lambda parent, first, last: removed_rows.append((parent, first, last))
    )
    model.modelReset.connect(lambda: resets.append(True))

    @graph.node(20)
    def second(value: int) -> int:
        return value

    added_node = graph.nodes()[1]
    graph._delete_node(added_node)

    assert inserted_rows == [(QModelIndex(), 1, 1)]
    assert removed_rows == [(QModelIndex(), 1, 1)]
    assert resets == []
    assert model.rowCount() == 1


def test_input_row_changes_emit_child_row_signals_without_resetting_model(qtbot, make_input_model):
    graph = rt.GraphDefinitionRT()
    node_ref = graph._create_node(args=(10,))
    model = make_input_model(graph)
    node_index = model.index(0, 0)
    inserted_rows = []
    removed_rows = []
    resets = []
    model.rowsInserted.connect(
        lambda parent, first, last: inserted_rows.append((parent, first, last))
    )
    model.rowsRemoved.connect(
        lambda parent, first, last: removed_rows.append((parent, first, last))
    )
    model.modelReset.connect(lambda: resets.append(True))

    node_ref.set_inputs(10, 20)
    node_ref.set_inputs(10)

    assert inserted_rows == [(node_index, 1, 1)]
    assert removed_rows == [(node_index, 1, 1)]
    assert resets == []
    assert model.rowCount(node_index) == 1
