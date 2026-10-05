import pytest
from pytestqt.qtbot import QtBot
from qtpy.QtCore import QItemSelection, QItemSelectionModel

import pygraphrt as rt
from pyflow5.pyflow5_document import PyFlowDocument
from qdageditor5.adapters.nodes_list_model_adapter import NodesListModelAdapter
from qdageditor5.adapters.nodes_list_selection_model_adapter import NodesListSelectionModelAdapter
from qdageditor5.models.abstract_dag_model import NodeName
from qdageditor5.models.graph_selection_model import GraphSelectionModel


@pytest.fixture
def document(qtbot: QtBot) -> PyFlowDocument:
    graph = rt.GraphDefinitionRT()

    @graph.node(name="first")
    def first() -> int:
        return 1

    @graph.node(first, name="second")
    def second(value: int) -> int:
        return value + 1

    @graph.node(name="third")
    def third() -> int:
        return 3

    return PyFlowDocument(graph=graph)


@pytest.fixture
def adapter(document: PyFlowDocument) -> NodesListSelectionModelAdapter:
    model = NodesListModelAdapter(document.graph_model)
    adapter = NodesListSelectionModelAdapter(model)
    adapter.setSourceSelection(document.graphselection_model)
    return adapter


def selected_nodes(adapter: NodesListSelectionModelAdapter) -> set[NodeName]:
    return {adapter.model().mapToSource(index) for index in adapter.selectedIndexes()}


def current_node(adapter: NodesListSelectionModelAdapter) -> NodeName | None:
    return adapter.model().mapToSource(adapter.currentIndex())


def test_attaching_adopts_selection_and_an_unselected_current_node(document: PyFlowDocument) -> None:
    source = document.graphselection_model
    source.selectNodes(["first", "third"])
    source.setCurrentNode("second")
    adapter = NodesListSelectionModelAdapter(NodesListModelAdapter(document.graph_model))
    adapter.setSourceSelection(source)

    assert adapter.sourceSelection() is source
    assert selected_nodes(adapter) == {"first", "third"}
    assert current_node(adapter) == "second"


def test_source_selection_and_current_update_independently(
    document: PyFlowDocument, adapter: NodesListSelectionModelAdapter,
) -> None:
    source = document.graphselection_model
    source.selectNode("first")
    source.selectNodes(["second", "third"])
    assert selected_nodes(adapter) == {"second", "third"}
    assert current_node(adapter) == "first"

    source.clearSelection()
    assert selected_nodes(adapter) == set()
    assert current_node(adapter) == "first"

    source.setCurrentNode(None)
    assert not adapter.currentIndex().isValid()


def test_list_selection_and_current_update_independently_and_preserve_links(
    document: PyFlowDocument, adapter: NodesListSelectionModelAdapter,
) -> None:
    source = document.graphselection_model
    link = next(iter(document.graph_model.links()))
    source.selectLink(link)
    flags = QItemSelectionModel.SelectionFlag
    first = adapter.model().mapFromSource("first")
    second = adapter.model().mapFromSource("second")

    adapter.setCurrentIndex(first, flags.NoUpdate)
    adapter.select(second, flags.ClearAndSelect)
    assert source.currentNode() == "first"
    assert set(source.selectedNodes()) == {"second"}

    adapter.select(first, flags.Toggle)
    assert set(source.selectedNodes()) == {"first", "second"}
    adapter.select(second, flags.Deselect)
    assert set(source.selectedNodes()) == {"first"}

    adapter.clearSelection()
    assert source.selectedNodes() == ()
    assert source.currentNode() == "first"
    adapter.clearCurrentIndex()
    assert source.currentNode() is None
    assert source.selectedLinks() == (link,)
    assert source.currentLink() == link


def test_interactive_selection_can_shrink_without_echo_committing_it(
    document: PyFlowDocument, adapter: NodesListSelectionModelAdapter,
) -> None:
    flags = QItemSelectionModel.SelectionFlag
    first = adapter.model().mapFromSource("first")
    second = adapter.model().mapFromSource("second")
    third = adapter.model().mapFromSource("third")

    adapter.select(first, flags.Select)
    adapter.select(second, flags.Select)
    adapter.select(QItemSelection(second, third), flags.SelectCurrent)
    assert selected_nodes(adapter) == {"first", "second", "third"}
    adapter.select(second, flags.SelectCurrent)

    assert selected_nodes(adapter) == {"first", "second"}
    assert set(document.graphselection_model.selectedNodes()) == {"first", "second"}
    assert document.graphselection_model.currentNode() is None


def test_replacing_and_detaching_disconnect_the_previous_source(
    document: PyFlowDocument, adapter: NodesListSelectionModelAdapter,
) -> None:
    old_source = document.graphselection_model
    old_source.selectNode("first")
    replacement = GraphSelectionModel(document.graph_model)
    replacement.selectNode("second")
    adapter.setSourceSelection(replacement)
    adapter.setSourceSelection(replacement)
    old_source.selectNode("third")

    assert selected_nodes(adapter) == {"second"}
    assert current_node(adapter) == "second"
    adapter.clear()
    assert replacement.selectedNodes() == ()
    assert replacement.currentNode() is None
    assert set(old_source.selectedNodes()) == {"first", "third"}

    replacement.selectNode("second")
    adapter.setSourceSelection(None)
    assert adapter.sourceSelection() is None
    assert selected_nodes(adapter) == set()
    assert not adapter.currentIndex().isValid()
    assert replacement.selectedNodes() == ("second",)
    assert replacement.currentNode() == "second"

    replacement.selectNode("first")
    adapter.setCurrentIndex(adapter.model().mapFromSource("third"), QItemSelectionModel.ClearAndSelect)
    assert selected_nodes(adapter) == {"third"}
    assert set(replacement.selectedNodes()) == {"first", "second"}
    assert replacement.currentNode() == "first"


def test_two_adapters_share_changes_without_duplicate_notifications(
    document: PyFlowDocument, adapter: NodesListSelectionModelAdapter,
) -> None:
    source = document.graphselection_model
    other = NodesListSelectionModelAdapter(NodesListModelAdapter(document.graph_model))
    other.setSourceSelection(source)
    selections: list[tuple[set[NodeName], set[NodeName]]] = []
    currents: list[tuple[NodeName | None, NodeName | None]] = []
    source.nodesSelectionChanged.connect(lambda added, removed: selections.append((added, removed)))
    source.currentNodeChanged.connect(lambda current, previous: currents.append((current, previous)))

    adapter.setCurrentIndex(adapter.model().mapFromSource("second"), QItemSelectionModel.ClearAndSelect)

    assert selected_nodes(other) == {"second"}
    assert current_node(other) == "second"
    assert selections == [({"second"}, set())]
    assert currents == [("second", None)]


def test_list_reset_restores_source_state(
    document: PyFlowDocument, adapter: NodesListSelectionModelAdapter,
) -> None:
    source = document.graphselection_model
    source.selectNode("second")
    adapter.model().setSourceGraph(document.graph_model)

    assert selected_nodes(adapter) == {"second"}
    assert current_node(adapter) == "second"
    assert source.selectedNodes() == ("second",)


def test_selection_during_insertion_is_applied_when_the_list_row_exists(document: PyFlowDocument) -> None:
    source = document.graphselection_model

    def select_added_node(nodes: tuple[NodeName, ...]) -> None:
        source.selectNode(nodes[0])

    # This listener runs before NodesListModel processes the insertion.
    document.graph_model.nodesAdded.connect(select_added_node)
    model = NodesListModelAdapter(document.graph_model)
    adapter = NodesListSelectionModelAdapter(model)
    adapter.setSourceSelection(source)
    operator = document.graph_model.mapToSource("first").get_operator()
    assert document.graph_model.addNode(operator)

    assert len(source.selectedNodes()) == 1
    assert selected_nodes(adapter) == set(source.selectedNodes())
    assert current_node(adapter) == source.currentNode()
    assert adapter.currentIndex().isValid()


def test_detached_adapter_keeps_local_selection_when_a_node_is_inserted(
    document: PyFlowDocument, adapter: NodesListSelectionModelAdapter,
) -> None:
    adapter.setSourceSelection(None)
    adapter.setCurrentIndex(adapter.model().mapFromSource("second"), QItemSelectionModel.ClearAndSelect)
    operator = document.graph_model.mapToSource("first").get_operator()
    assert document.graph_model.addNode(operator)

    assert selected_nodes(adapter) == {"second"}
    assert current_node(adapter) == "second"
    assert document.graphselection_model.selectedNodes() == ()


@pytest.mark.parametrize("action", ["remove_current", "remove_earlier", "reset", "replace"])
def test_graph_changes_do_not_leave_stale_indexes(
    document: PyFlowDocument, adapter: NodesListSelectionModelAdapter, action: str,
) -> None:
    source = document.graphselection_model
    source.selectNode("second")
    source.selectNodes(["second", "third"])

    if action == "remove_current":
        document.graph_model.removeNodes(["second"])
    elif action == "remove_earlier":
        document.graph_model.removeNodes(["first"])
    elif action == "reset":
        document.graph_model._beginResetModel()
        document.graph_model._endResetModel()
    else:
        replacement = PyFlowDocument()
        source.setModel(replacement.graph_model)
        adapter.model().setSourceGraph(replacement.graph_model)

    assert selected_nodes(adapter) == set(source.selectedNodes())
    assert current_node(adapter) == source.currentNode()
    if action == "remove_earlier":
        assert current_node(adapter) == "second"
        assert selected_nodes(adapter) == {"second", "third"}
    elif action == "remove_current":
        assert not adapter.currentIndex().isValid()
        assert selected_nodes(adapter) == {"third"}
    else:
        assert selected_nodes(adapter) == set()
        assert not adapter.currentIndex().isValid()
