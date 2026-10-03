import pygraphrt as rt

from pyflow5.inspector_roles import InspectorRole
from pyflow5.nodes_tree_model import NodesTreeModel


def test_clear_input_removes_and_shifts_positional_arguments(qtbot):
    graph = rt.GraphDefinitionRT()

    @graph.node(10, 20)
    def combine(first: int, second: int = 30) -> int:
        return first + second

    node_ref = graph.nodes()[0]
    model = NodesTreeModel(graph, rt.ModuleRegistry())
    node_index = model.index(0, 0)
    input_index = model.index(0, 1, node_index)

    assert input_index.data(InspectorRole.NodeRefRole) == node_ref
    assert input_index.data(InspectorRole.InputLocationRole) == "first"
    assert model.clearInput(node_ref, "first")
    assert node_ref.get_inputs() == ((20,), {})


def test_clear_input_removes_keyword_binding_and_restores_default(qtbot):
    graph = rt.GraphDefinitionRT()

    @graph.node(second=20)
    def combine(first: int = 10, second: int = 30) -> int:
        return first + second

    node_ref = graph.nodes()[0]
    model = NodesTreeModel(graph, rt.ModuleRegistry())

    assert model.clearInput(node_ref, "second")
    assert node_ref.get_inputs() == ((), {})

