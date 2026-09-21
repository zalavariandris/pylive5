from types import SimpleNamespace

import pytest
from qtpy.QtCore import QPoint

from pyflow5.pygraphrt_model import PyFlowRTModel
from pygraphrt.graph_rt import GraphRT
from qdageditor5.models.graph_selection_model import GraphSelectionModel
from qdageditor5.views.directional_graph_view_5 import DirectionalGraphView5


Flags = GraphSelectionModel.SelectionFlag
LINK_AB = ("a", "out", "b", "value")
LINK_AC = ("a", "out", "c", "value")


def make_model():
    graph = GraphRT()

    @graph.node()
    def a():
        return 1

    @graph.node(value=a)
    def b(value):
        return value

    @graph.node(value=a)
    def c(value):
        return value

    return PyFlowRTModel(graph)


@pytest.fixture
def model(qapp):
    return make_model()


@pytest.fixture(params=["node", "link"])
def selection_api(model, request):
    selection = GraphSelectionModel(model)
    if request.param == "node":
        return SimpleNamespace(
            selection=selection, first="a", second="b",
            select=selection.selectNode, select_many=selection.selectNodes,
            selected=selection.selectedNodes, current=selection.currentNode,
            set_current=selection.setCurrentNode,
            changed=selection.nodesSelectionChanged,
            current_changed=selection.currentNodeChanged,
        )
    return SimpleNamespace(
        selection=selection, first=LINK_AB, second=LINK_AC,
        select=selection.selectLink, select_many=selection.selectLinks,
        selected=selection.selectedLinks, current=selection.currentLink,
        set_current=selection.setCurrentLink,
        changed=selection.linksSelectionChanged,
        current_changed=selection.currentLinkChanged,
    )


def test_current_and_selection_signals_observe_committed_state(selection_api):
    api = selection_api
    selections, currents = [], []
    api.changed.connect(lambda added, removed: selections.append(
        (added, removed, api.current(), set(api.selected()))
    ))
    api.current_changed.connect(lambda current, previous: currents.append(
        (current, previous, set(api.selected()))
    ))

    api.select(api.first)
    api.select(api.first)  # Re-selecting is a no-op.
    api.select(api.second, Flags.ClearAndSelect | Flags.Current)

    assert selections == [
        ({api.first}, set(), api.first, {api.first}),
        ({api.second}, {api.first}, api.second, {api.second}),
    ]
    assert currents == [
        (api.first, None, {api.first}),
        (api.second, api.first, {api.second}),
    ]


@pytest.mark.parametrize("mode", [Flags.Deselect, Flags.Toggle, Flags.Toggle | Flags.Current])
def test_deselecting_current_does_not_choose_a_replacement(selection_api, mode):
    api = selection_api
    api.select(api.first)
    api.select(api.second)
    api.select(api.second, mode)
    assert set(api.selected()) == {api.first}
    assert api.current() is None


def test_bulk_selection_never_picks_an_arbitrary_current(selection_api):
    api = selection_api
    api.select_many({api.first, api.second}, Flags.ClearAndSelect | Flags.Current)
    assert api.current() is None

    api.set_current(api.first)
    api.select_many((item for item in [api.first, api.second]))
    assert api.current() == api.first

    api.select_many([api.second])
    assert api.current() is None
    assert api.selected() == (api.second,)


def test_current_can_change_without_changing_selection(selection_api):
    api = selection_api
    api.set_current(api.first)
    assert api.current() == api.first
    assert api.selected() == ()


def test_clear_publishes_fully_cleared_state_and_is_idempotent(model):
    selection = GraphSelectionModel(model)
    selection.selectNode("b")
    selection.selectLink(LINK_AB)
    observed = []

    def record(*args):
        observed.append((
            selection.selectedNodes(), selection.selectedLinks(),
            selection.currentNode(), selection.currentLink(),
        ))

    for signal in (selection.nodesSelectionChanged, selection.linksSelectionChanged,
                   selection.currentNodeChanged, selection.currentLinkChanged):
        signal.connect(record)

    selection.clearSelection()
    selection.clearSelection()
    assert observed == [((), (), None, None)] * 4


def test_node_removal_cleans_current_and_incident_links_before_mutation(model):
    selection = GraphSelectionModel(model)
    selection.selectNode("b")
    selection.selectLink(LINK_AB)
    selection.selectLink(LINK_AC, Flags.Select)
    before_removal = []
    model.nodesAboutToBeRemoved.connect(lambda nodes: before_removal.append((
        selection.currentNode(), selection.currentLink(), set(selection.selectedLinks())
    )))

    model.removeNodes(["b"])

    assert before_removal == [(None, None, {LINK_AC})]
    assert selection.selectedNodes() == ()
    assert selection.selectedLinks() == (LINK_AC,)


def test_unrelated_removal_preserves_current_without_selection(model):
    selection = GraphSelectionModel(model)
    selection.setCurrentNode("c")
    selection.setCurrentLink(LINK_AC)
    model.removeNodes(["b"])
    assert selection.currentNode() == "c"
    assert selection.currentLink() == LINK_AC


def test_link_removal_clears_selected_link_but_preserves_nodes(model):
    selection = GraphSelectionModel(model)
    selection.selectNode("b")
    selection.selectLink(LINK_AB)
    model.removeLinks([LINK_AB])
    assert selection.selectedLinks() == ()
    assert selection.currentLink() is None
    assert selection.currentNode() == "b"


def test_runtime_binding_change_prunes_disappeared_link(model):
    selection = GraphSelectionModel(model)
    selection.selectLink(LINK_AB)
    model.getNode("b").set_inputs(value=42)
    assert selection.selectedLinks() == ()
    assert selection.currentLink() is None


def test_link_reset_prunes_disappeared_link(model):
    selection = GraphSelectionModel(model)
    selection.selectLink(LINK_AB)
    model.links = lambda: [LINK_AC]
    model.linksReset.emit()
    assert selection.selectedLinks() == ()
    assert selection.currentLink() is None


def test_model_reset_clears_before_other_reset_observers(model):
    selection = GraphSelectionModel(model)
    selection.selectNode("b")
    selection.selectLink(LINK_AB)
    observed = []
    model.modelAboutToBeReset.connect(lambda: observed.append((
        selection.currentNode(), selection.currentLink()
    )))
    model.reset()
    assert observed == [(None, None)]
    assert selection.selectedNodes() == ()
    assert selection.selectedLinks() == ()


def test_replacing_model_disconnects_old_model(model):
    selection = GraphSelectionModel(model)
    selection.selectNode("b")
    replacement = make_model()
    selection.setModel(replacement)
    assert selection.model() is replacement
    assert selection.selectedNodes() == ()
    assert selection.currentNode() is None

    selection.selectNode("b")
    selection.selectLink(LINK_AB)
    selection.setModel(replacement)  # Same-model assignment preserves state.
    model.removeNodes(["b"])
    model.reset()
    assert selection.currentNode() == "b"
    assert selection.currentLink() == LINK_AB

    replacement.removeNodes(["b"])
    assert selection.currentNode() is None
    assert selection.currentLink() is None


def test_nonexistent_items_cannot_become_selected_or_current(model):
    selection = GraphSelectionModel(model)
    missing_link = ("missing", "out", "b", "value")
    selection.selectNodes(["missing", "b"])
    selection.selectLinks([missing_link, LINK_AB])
    assert selection.selectedNodes() == ("b",)
    assert selection.selectedLinks() == (LINK_AB,)
    with pytest.raises(ValueError):
        selection.setCurrentNode("missing")
    with pytest.raises(ValueError):
        selection.setCurrentLink(missing_link)


def test_graph_click_sets_current_and_blank_click_clears(qtbot, model, monkeypatch):
    selection = GraphSelectionModel(model)
    view = DirectionalGraphView5()
    qtbot.addWidget(view)
    view.setModel(model)
    view.setSelectionModel(selection)
    event = SimpleNamespace(pos=lambda: QPoint(10, 10))

    monkeypatch.setattr(view, "itemAt", lambda position: ("node", "b"))
    view._mouse_click_event(event)
    assert selection.selectedNodes() == ("b",)
    assert selection.currentNode() == "b"

    monkeypatch.setattr(view, "itemAt", lambda position: None)
    view._mouse_click_event(event)
    assert selection.selectedNodes() == ()
    assert selection.currentNode() is None
