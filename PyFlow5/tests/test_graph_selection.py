import pytest
from pytestqt.qtbot import QtBot
from qtpy.QtCore import QEvent, QPoint, QPointF, Qt
from qtpy.QtGui import QMouseEvent, QPaintEvent
from qtpy.QtWidgets import QApplication, QStyle

import pygraphrt as rt
from pyflow5.models.pyflow5_document import PyFlowDocument
from qdageditor5.models.graph_selection_model import GraphSelectionModel
from qdageditor5.views.directional_graph_view_5 import DirectionalGraphView5


@pytest.fixture
def document(qtbot: QtBot) -> PyFlowDocument:
    graph = rt.GraphDefinitionRT()

    @graph.node(name="first")
    def first() -> int:
        return 1

    @graph.node(name="second")
    def second() -> int:
        return 2

    @graph.node(name="third")
    def third() -> int:
        return 3

    document = PyFlowDocument(graph=graph)
    for row, node in enumerate(document.graph_model.nodes()):
        document.graph_model.setNodePosition(node, QPointF(250, 100 + row * 120))
    return document


class PaintCountingGraphView(DirectionalGraphView5):
    def __init__(self) -> None:
        super().__init__()
        self.paint_count = 0

    def paintEvent(self, event: QPaintEvent) -> None:
        self.paint_count += 1
        super().paintEvent(event)


@pytest.fixture
def view(document: PyFlowDocument, qtbot: QtBot) -> PaintCountingGraphView:
    view = PaintCountingGraphView()
    view.resize(800, 500)
    view.setModel(document.graph_model)
    view.setSelectionModel(document.graphselection_model)
    qtbot.addWidget(view)
    view.show()
    QApplication.processEvents()
    return view


def move_selection_pointer(view: DirectionalGraphView5, position: QPoint) -> None:
    event = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(position),
        QPointF(view.mapToGlobal(position)),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(view, event)


def test_bulk_selection_preserves_an_unselected_current_node(document: PyFlowDocument) -> None:
    selection = document.graphselection_model
    selection.selectNode("first")
    selection.selectNodes(["second", "third"])

    assert set(selection.selectedNodes()) == {"second", "third"}
    assert selection.currentNode() == "first"


def test_toggle_can_leave_the_current_node_unselected(document: PyFlowDocument) -> None:
    selection = document.graphselection_model
    flags = GraphSelectionModel.SelectionFlag
    selection.selectNode("first")
    selection.selectNode("first", flags.Toggle | flags.Current)

    assert selection.selectedNodes() == ()
    assert selection.currentNode() == "first"


def test_current_only_command_does_not_select(document: PyFlowDocument) -> None:
    selection = document.graphselection_model
    selection.selectNode("second", GraphSelectionModel.SelectionFlag.Current)

    assert selection.currentNode() == "second"
    assert selection.selectedNodes() == ()


def test_clear_selection_preserves_current_but_clear_resets_it(document: PyFlowDocument) -> None:
    selection = document.graphselection_model
    selection.selectNode("first")
    selection.clearSelection()

    assert selection.selectedNodes() == ()
    assert selection.currentNode() == "first"

    selection.clear()
    assert selection.currentNode() is None


@pytest.mark.parametrize("action", ["remove", "reset", "replace"])
def test_current_node_is_cleared_when_its_model_item_is_invalidated(
    document: PyFlowDocument, action: str,
) -> None:
    selection = document.graphselection_model
    selection.setCurrentNode("first")
    changes: list[tuple[object, object]] = []
    selection.currentNodeChanged.connect(lambda current, previous: changes.append((current, previous)))

    if action == "remove":
        document.graph_model.removeNodes(["first"])
    elif action == "reset":
        document.graph_model._beginResetModel()
        document.graph_model._endResetModel()
    else:
        replacement = PyFlowDocument()
        selection.setModel(replacement.graph_model)

    assert selection.currentNode() is None
    assert changes == [(None, "first")]


@pytest.mark.parametrize("removal", ["link", "source"])
def test_link_current_is_independent_and_cleared_on_removal(qtbot: QtBot, removal: str) -> None:
    graph = rt.GraphDefinitionRT()

    @graph.node(name="source")
    def source() -> int:
        return 1

    @graph.node(source, name="target")
    def target(value: int) -> int:
        return value

    document = PyFlowDocument(graph=graph)
    selection = document.graphselection_model
    link = next(iter(document.graph_model.links()))
    selection.selectLink(link)
    selection.selectLink(link, GraphSelectionModel.SelectionFlag.Toggle | GraphSelectionModel.SelectionFlag.Current)

    assert selection.selectedLinks() == ()
    assert selection.currentLink() == link
    selection.clearSelection()
    assert selection.currentLink() == link

    if removal == "link":
        document.graph_model.removeLinks([link])
    else:
        document.graph_model.removeNodes(["source"])
    assert selection.currentLink() is None


def test_pressing_a_selected_node_updates_current_and_preserves_group_drag(
    document: PyFlowDocument, view: PaintCountingGraphView, qtbot: QtBot,
) -> None:
    selection = document.graphselection_model
    selection.selectNodes(["first", "second"])
    selection.setCurrentNode("first")

    qtbot.mousePress(view, Qt.MouseButton.LeftButton, pos=QPoint(250, 220))
    assert selection.currentNode() == "second"
    assert set(selection.selectedNodes()) == {"first", "second"}

    move_selection_pointer(view, QPoint(280, 250))
    qtbot.mouseRelease(view, Qt.MouseButton.LeftButton, pos=QPoint(280, 250))
    assert selection.currentNode() == "second"
    assert set(selection.selectedNodes()) == {"first", "second"}
    assert document.graph_model.nodePosition("first") == QPointF(280, 130)
    assert document.graph_model.nodePosition("second") == QPointF(280, 250)


def test_dragging_an_unselected_node_selects_it_and_makes_it_current(
    document: PyFlowDocument, view: PaintCountingGraphView, qtbot: QtBot,
) -> None:
    selection = document.graphselection_model
    selection.selectNode("first")

    qtbot.mousePress(view, Qt.MouseButton.LeftButton, pos=QPoint(250, 220))
    assert selection.currentNode() == "second"
    assert selection.selectedNodes() == ("second",)

    move_selection_pointer(view, QPoint(280, 250))
    qtbot.mouseRelease(view, Qt.MouseButton.LeftButton, pos=QPoint(280, 250))
    assert selection.currentNode() == "second"


@pytest.mark.parametrize("zoom,pan", [(1.0, QPointF()), (1.5, QPointF(40, -30))])
def test_rectangle_current_follows_pointer_in_both_directions(
    document: PyFlowDocument, view: PaintCountingGraphView, qtbot: QtBot,
    zoom: float, pan: QPointF,
) -> None:
    selection = document.graphselection_model
    view._zoom, view._pan = zoom, pan

    def view_position(x: float, y: float) -> QPoint:
        return view.mapFromScene(QPointF(x, y)).toPoint()

    qtbot.mousePress(view, Qt.MouseButton.LeftButton, pos=view_position(50, 40))
    move_selection_pointer(view, view_position(250, 100))
    assert selection.currentNode() == "first"
    move_selection_pointer(view, view_position(250, 220))
    assert selection.currentNode() == "second"
    assert set(selection.selectedNodes()) == {"first", "second"}

    move_selection_pointer(view, view_position(250, 100))
    assert selection.currentNode() == "first"
    assert selection.selectedNodes() == ("first",)

    # Shrinking into empty space removes the selection, but retains current.
    move_selection_pointer(view, view_position(60, 50))
    assert selection.selectedNodes() == ()
    assert selection.currentNode() == "first"
    qtbot.mouseRelease(view, Qt.MouseButton.LeftButton, pos=view_position(60, 50))
    assert selection.currentNode() == "first"


def test_rectangle_release_uses_the_final_pointer_position(
    document: PyFlowDocument, view: PaintCountingGraphView, qtbot: QtBot,
) -> None:
    selection = document.graphselection_model
    qtbot.mousePress(view, Qt.MouseButton.LeftButton, pos=QPoint(50, 400))
    move_selection_pointer(view, QPoint(250, 340))
    assert selection.currentNode() == "third"

    # A release can arrive at a new position without a preceding move event.
    qtbot.mouseRelease(view, Qt.MouseButton.LeftButton, pos=QPoint(250, 100))
    assert set(selection.selectedNodes()) == {"first", "second", "third"}
    assert selection.currentNode() == "first"


def test_clicking_empty_space_clears_selection_but_preserves_current(
    document: PyFlowDocument, view: PaintCountingGraphView, qtbot: QtBot,
) -> None:
    selection = document.graphselection_model
    selection.selectNode("first")
    qtbot.mouseClick(view, Qt.MouseButton.LeftButton, pos=QPoint(650, 450))

    assert selection.selectedNodes() == ()
    assert selection.currentNode() == "first"


def test_current_only_change_repaints_and_moves_the_focus_indicator(
    document: PyFlowDocument, view: PaintCountingGraphView, qtbot: QtBot,
) -> None:
    selection = document.graphselection_model
    selection.selectNodes(["first", "second"])
    selection.setCurrentNode("first")
    QApplication.processEvents()
    previous_paints = view.paint_count

    selection.setCurrentNode("second")
    qtbot.waitUntil(lambda: view.paint_count > previous_paints)
    assert not view._createStyleOption("first").state & QStyle.StateFlag.State_HasFocus
    assert view._createStyleOption("second").state & QStyle.StateFlag.State_HasFocus
    assert set(selection.selectedNodes()) == {"first", "second"}
