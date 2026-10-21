"""Graph snapshots narrow runtime notifications without changing model reads."""

from collections.abc import Iterator

import pygraphrt as rt
import pytest
from pytestqt.modeltest import ModelTester
from qtpy.QtCore import QPersistentModelIndex, Qt

from pyflow5.core.input_roles import InputDataRole
from pyflow5.models.pygraphrt_graphmodel import PyGraphRTGraphModel
from pyflow5.models.pygraphrt_node_inlet_tree_model_adapter import (
    PyGraphRTNodeInletTreeModelAdapter,
)
from qdageditor5.models.graph_selection_model import GraphSelectionModel


@pytest.fixture
def module() -> rt.ScriptModuleRT:
    module = rt.ScriptModuleRT("example")
    module.set_script("def operation(first: int = 1, second: int = 2): return first + second")
    module._evaluate()
    return module


@pytest.fixture
def model(qapp: object, module: rt.ScriptModuleRT) -> Iterator[PyGraphRTGraphModel]:
    graph = rt.GraphDefinitionRT()
    graph._create_node(name="source")
    graph._create_node(
        module.get_operator_by_name("operation"),
        kwargs={"first": 3, "second": 4},
        name="target",
    )
    registry = rt.ModuleRegistry()
    registry.add_module(module)
    engine = rt.GraphEngine(graph=graph, registry=registry)
    model = PyGraphRTGraphModel(engine)
    yield model
    model.close()
    engine.close()


@pytest.fixture
def target(model: PyGraphRTGraphModel) -> rt.NodeRef:
    node = model.mapToSource("target")
    assert node is not None
    return node


@pytest.fixture
def events(model: PyGraphRTGraphModel) -> list[tuple[object, ...]]:
    events: list[tuple[object, ...]] = []
    model.inletsReset.connect(lambda node: events.append(("inlets_reset", node)))
    model.inletDataChanged.connect(
        lambda node, inlets, roles: events.append(("inlets", node, inlets, roles))
    )
    model.nodesDataChanged.connect(
        lambda nodes, roles: events.append(("nodes", nodes, roles))
    )
    model.linksReset.connect(lambda: events.append(("links_reset",)))
    model.linksAdded.connect(lambda links: events.append(("links_added", links)))
    model.linksRemoved.connect(lambda links: events.append(("links_removed", links)))
    return events


def test_value_edit_notifies_only_its_inlet_and_repeated_value_is_silent(
    model: PyGraphRTGraphModel, target: rt.NodeRef, events: list[tuple[object, ...]],
) -> None:
    assert model.setInletData("target", "first", 5, InputDataRole.InputValueRole)
    assert events == [("inlets", "target", ("first",), [])]
    events.clear()
    target.set_inputs(first=5, second=4)
    assert events == []


def test_tree_updates_only_the_changed_row(
    model: PyGraphRTGraphModel, target: rt.NodeRef, qtmodeltester: ModelTester,
) -> None:
    tree = PyGraphRTNodeInletTreeModelAdapter(model)
    qtmodeltester.check(tree)
    parent = tree.mapFromSource("target")
    unchanged = QPersistentModelIndex(tree.index(1, 1, parent))
    changes: list[tuple[object, ...]] = []
    tree.dataChanged.connect(lambda *args: changes.append(args))
    target.set_inputs(first=9, second=4)
    assert changes == [(tree.index(0, 0, parent), tree.index(0, 1, parent), [])]
    assert unchanged.isValid() and unchanged.data() == "4"


def test_missing_input_and_none_are_distinct(
    model: PyGraphRTGraphModel, target: rt.NodeRef, events: list[tuple[object, ...]],
) -> None:
    target.set_inputs(second=4)
    events.clear()
    target.set_inputs(first=None, second=4)
    assert events == [("inlets", "target", ("first",), [])]
    assert model.inletData("target", "first", InputDataRole.InputIsSetRole)
    assert model.inletData("target", "first", InputDataRole.InputValueRole) is None


@pytest.mark.parametrize("value", [True, 1.0])
def test_equal_values_of_different_types_still_notify(
    target: rt.NodeRef, events: list[tuple[object, ...]], value: object,
) -> None:
    target.set_inputs(first=1, second=4)
    events.clear()
    target.set_inputs(first=value, second=4)
    assert events == [("inlets", "target", ("first",), [])]


def test_binding_location_changes_without_resetting_inlets(
    model: PyGraphRTGraphModel, target: rt.NodeRef, events: list[tuple[object, ...]],
) -> None:
    target.set_inputs(3, second=4)
    assert events == [("inlets", "target", ("first",), [])]
    assert model.inletData("target", "first", InputDataRole.InputLocationRole) == 0


@pytest.mark.parametrize("parameters", [
    "first: float = 1.5, second: int = 2",
    "first: int = 9, second: int = 2",
])
def test_metadata_change_updates_inlet_without_reset(
    module: rt.ScriptModuleRT, events: list[tuple[object, ...]], parameters: str,
) -> None:
    module.set_script(f"def operation({parameters}): return first + second")
    module._evaluate()
    assert events == [("inlets", "target", ("first",), [])]


@pytest.mark.parametrize("parameters", [
    "second: int = 2, first: int = 1",
    "first: int = 1, middle: int = 0, second: int = 2",
])
def test_inlet_order_or_membership_change_resets_inlets(
    module: rt.ScriptModuleRT, events: list[tuple[object, ...]], parameters: str,
) -> None:
    module.set_script(f"def operation({parameters}): return first + second")
    module._evaluate()
    assert events == [("inlets_reset", "target")]


def test_function_body_change_does_not_change_presentation(
    module: rt.ScriptModuleRT, events: list[tuple[object, ...]],
) -> None:
    module.set_script("def operation(first: int = 1, second: int = 2): return first - second")
    module._evaluate()
    assert events == []


def test_operator_change_updates_header_without_resetting_identical_inlets(
    model: PyGraphRTGraphModel, target: rt.NodeRef, events: list[tuple[object, ...]],
) -> None:
    def renamed(first: int = 1, second: int = 2) -> int:
        return first + second

    args, kwargs = target.get_inputs()
    model._engine._graph._update_node(target, rt.FunctionOperator(renamed), args, kwargs)
    assert events == [(
        "nodes", ("target",), (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.BackgroundRole),
    )]


def test_direct_connection_change_prunes_selected_link(
    model: PyGraphRTGraphModel, target: rt.NodeRef, events: list[tuple[object, ...]],
) -> None:
    source = model.mapToSource("source")
    assert source is not None
    target.set_inputs(first=source, second=4)
    assert events == [("inlets", "target", ("first",), []), ("links_reset",)]
    selection = GraphSelectionModel(model)
    selection.selectLink(("source", "out", "target", "first"))
    events.clear()
    target.set_inputs(first=3, second=4)
    assert events == [("inlets", "target", ("first",), []), ("links_reset",)]
    assert selection.selectedLinks() == ()
    assert selection.currentLink() is None


def test_link_commands_keep_their_own_notifications(
    model: PyGraphRTGraphModel, events: list[tuple[object, ...]],
) -> None:
    link = ("source", "out", "target", "first")
    model.addLink(*link)
    assert events == [("inlets", "target", ("first",), []), ("links_added", (link,))]
    events.clear()
    model.removeLinks([link])
    assert events == [("inlets", "target", ("first",), []), ("links_removed", (link,))]


@pytest.mark.parametrize("through_model", [False, True])
def test_added_and_recreated_nodes_start_with_current_snapshots(
    model: PyGraphRTGraphModel, module: rt.ScriptModuleRT,
    events: list[tuple[object, ...]], through_model: bool,
) -> None:
    operator = module.get_operator_by_name("operation")
    assert operator is not None
    for _ in range(2):
        if through_model:
            model.addNode(operator)
        else:
            model._engine._graph._create_node(operator, name="operation")
        node = model.mapToSource("operation")
        assert node is not None
        events.clear()
        node.set_inputs()
        assert events == []
        node.set_inputs(first=8)
        assert events == [("inlets", "operation", ("first",), [])]
        if through_model:
            model.removeNodes(["operation"])
        else:
            model._engine._graph._delete_node(node)


def test_recovery_rebuilds_snapshots_before_next_notification(
    model: PyGraphRTGraphModel, target: rt.NodeRef, events: list[tuple[object, ...]],
) -> None:
    graph = model._engine._graph
    graph.blockSignals(True)
    try:
        target.set_inputs(first=10, second=4)
    finally:
        graph.blockSignals(False)
    model.reset_graph_from_scratch()
    target.set_inputs(first=10, second=4)
    assert events == []
    target.set_inputs(first=11, second=4)
    assert events == [("inlets", "target", ("first",), [])]


def test_mutable_input_is_conservatively_refreshed(
    target: rt.NodeRef, events: list[tuple[object, ...]],
) -> None:
    value = [1]
    target.set_inputs(first=value, second=4)
    events.clear()
    value.append(2)
    target.set_inputs(first=value, second=4)
    assert events == [("inlets", "target", ("first",), [])]
