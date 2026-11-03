"""Document subscriptions and independent selection/viewer lifetimes."""

from collections.abc import Iterator

import pytest
from pytestqt.qtbot import QtBot
from qtpy.QtCore import QCoreApplication, QItemSelectionModel

from pygraphrt2 import Engine, Graph
from pyflow5.models.pyflow5_document import PyFlowDocument
from pyflow5.views.pyflow5_documentwindow import PyFlow5DocumentWindow
from PyGraphRT2.tests_ai.test_engine_subscriptions import RecordingBackend


@pytest.fixture
def window(qtbot: QtBot) -> Iterator[tuple[PyFlow5DocumentWindow, RecordingBackend]]:
    graph = Graph()
    backend = RecordingBackend(graph)
    engine = Engine(graph=graph, backend=backend)
    engine.add_node(lambda value=1: value, name="first")
    engine.add_node(lambda: 2, name="second")
    document = PyFlowDocument(engine=engine)
    view = PyFlow5DocumentWindow(document)
    qtbot.addWidget(view, before_close_func=lambda widget: widget.dispose())
    try:
        yield view, backend
    finally:
        view.dispose()


@pytest.mark.parametrize("output", [42, None, {"answer": 42}])
def test_document_delivers_output_after_model_outputs_are_updated(
    window: tuple[PyFlow5DocumentWindow, RecordingBackend], output: object,
) -> None:
    view, backend = window
    document = view.document()
    node = document.graph_model.mapToSource("first")
    document._engine._graph._update_node(node, lambda: output)
    received: list[tuple[object, object]] = []
    subscription = document.subscribeNode(
        "first",
        lambda result: received.append((result, document.graph_model.nodeData("first", document.graph_model.OutputRole))),
    )
    assert received == []
    QCoreApplication.processEvents()
    backend.finish()
    assert len(received) == 1
    assert received[0][0] is output
    assert received[0][1] is output
    subscription.unsubscribe()
    subscription.unsubscribe()
    with pytest.raises(KeyError):
        document.subscribeNode("missing", lambda _: None)
    document.close()
    with pytest.raises(RuntimeError):
        document.subscribeNode("first", lambda _: None)


def test_selection_and_locked_viewer_keep_independent_subscriptions(
    window: tuple[PyFlow5DocumentWindow, RecordingBackend],
) -> None:
    view, backend = window
    document = view.document()
    engine = document._engine
    view.graphselection_model.setCurrentNode("first")
    QCoreApplication.processEvents()
    backend.finish()
    assert view._outputviewer._body_widget._cached_data == 1
    selected_first = view._selection_subscription
    viewed_first = view._viewer_subscription
    assert selected_first is not viewed_first
    view._outputviewer._lock_switch.setChecked(True)
    view.graphselection_model.setCurrentNode("second")
    assert not selected_first.active
    assert viewed_first.active
    assert view._selection_subscription.node.name() == "second"
    QCoreApplication.processEvents()
    backend.finish()
    assert view._outputviewer._body_widget._cached_data == 1

    first = document.graph_model.mapToSource("first")
    engine._graph._update_node(first, lambda: 10)
    QCoreApplication.processEvents()
    backend.finish()
    assert view._outputviewer._body_widget._cached_data == 10

    view._outputviewer._lock_switch.setChecked(False)
    assert not viewed_first.active
    assert view._viewer_subscription.node.name() == "second"
    assert view._outputviewer._body_widget._cached_data == 2
    assert first not in engine._subscriptions


def test_inlet_selection_reuses_its_owning_node_subscription(
    window: tuple[PyFlow5DocumentWindow, RecordingBackend],
) -> None:
    view, backend = window
    document = view.document()
    view.graphselection_model.setCurrentNode("first")
    subscription = view._viewer_subscription
    model = document.node_inlet_tree_adapter
    root = model.mapFromSource("first")
    inlet = model.index(0, 1, root)
    assert inlet.isValid()
    view.node_inlet_tree_selection_adapter.setCurrentIndex(
        inlet, QItemSelectionModel.SelectionFlag.NoUpdate,
    )
    assert view._viewer_subscription is subscription
    QCoreApplication.processEvents()
    backend.finish()
    assert view._outputviewer._body_widget._cached_data == 1


@pytest.mark.parametrize("action", ["reset", "delete", "disconnect"])
def test_clearing_view_releases_even_a_locked_subscription(
    window: tuple[PyFlow5DocumentWindow, RecordingBackend], action: str,
) -> None:
    view, backend = window
    document = view.document()
    engine = document._engine
    view.graphselection_model.setCurrentNode("first")
    QCoreApplication.processEvents()
    backend.finish()
    selection = view._selection_subscription
    viewer = view._viewer_subscription
    view._outputviewer._lock_switch.setChecked(True)
    if action == "reset":
        document.graph_model.reset_graph_from_scratch()
    elif action == "delete":
        document.deleteNodes(["first"])
    else:
        view._disconnectDocument()
    assert not selection.active
    assert not viewer.active
    assert view._selection_subscription is None
    assert view._viewer_subscription is None
    assert engine._subscriptions == {}
    if action == "disconnect":
        document.close()


def test_reconnecting_document_does_not_accumulate_subscriptions(
    window: tuple[PyFlow5DocumentWindow, RecordingBackend],
) -> None:
    view, backend = window
    document = view.document()
    for _ in range(3):
        view.graphselection_model.setCurrentNode("first")
        node = document.graph_model.mapToSource("first")
        assert len(document._engine._subscriptions[node]) == 2
        view._disconnectDocument()
        assert document._engine._subscriptions == {}
        view._connectDocument(document)


def test_deleting_an_earlier_row_preserves_the_locked_viewed_node(
    window: tuple[PyFlow5DocumentWindow, RecordingBackend],
) -> None:
    view, backend = window
    document = view.document()
    view.graphselection_model.setCurrentNode("second")
    QCoreApplication.processEvents()
    backend.finish()
    subscription = view._viewer_subscription
    view._outputviewer._lock_switch.setChecked(True)
    document.deleteNodes(["first"])
    assert subscription.active
    assert view._viewer_subscription is subscription
    root = view._outputviewer.currentRoot()
    assert root.row() == 0
    assert document.node_inlet_tree_adapter.mapToSource(root) == "second"
    assert view._outputviewer._body_widget._cached_data == 2
