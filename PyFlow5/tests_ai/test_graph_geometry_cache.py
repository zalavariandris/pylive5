"""Regression checks for view-owned geometry during interactive node movement."""

from collections.abc import Iterator

import pytest
from pytestqt.qtbot import QtBot
from qtpy.QtCore import QEvent, QPoint, QPointF, Qt
from qtpy.QtGui import QColor, QImage, QMouseEvent, QPainter, QPalette

import pygraphrt as rt
from pyflow5.models.pygraphrt_graphmodel import PyGraphRTGraphModel
from pygraphrt.graph_executor_3_draft import GraphEvaluator, InlineExecutionBackend
from qdageditor5.models.graph_selection_model import GraphSelectionModel
from qdageditor5.views.directional_graph_view_5 import DirectionalGraphView5


def make_model() -> PyGraphRTGraphModel:
    graph = rt.GraphDefinitionRT()

    @graph.node()
    def first() -> int:
        return 1

    @graph.node(first)
    def second(value: int) -> int:
        return value

    @graph.node(second)
    def third(value: int) -> int:
        return value

    registry = rt.ModuleRegistry()
    invalidator = rt.GraphInvalidator(graph, registry)
    evaluator = GraphEvaluator(graph, InlineExecutionBackend(), invalidator=invalidator)
    model = PyGraphRTGraphModel(graph, registry, invalidator, evaluator)
    for row, node in enumerate(model.nodes()):
        model.setNodePosition(node, QPointF(220, 80 + row * 120))
    return model


@pytest.fixture
def graph_view(qtbot: QtBot) -> Iterator[tuple[DirectionalGraphView5, PyGraphRTGraphModel]]:
    model = make_model()
    view = DirectionalGraphView5()
    view.resize(800, 650)
    view.setModel(model)
    view.setSelectionModel(GraphSelectionModel(model))
    qtbot.addWidget(view)
    yield view, model
    model.close()
    model._evaluator.close()


def render(view: DirectionalGraphView5) -> QImage:
    image = QImage(view.size(), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    try:
        view.render(painter, QPoint())
    finally:
        painter.end()
    return image


def test_view_and_delegate_expose_position_independent_local_geometry(
    graph_view: tuple[DirectionalGraphView5, PyGraphRTGraphModel],
) -> None:
    view, model = graph_view
    node = "second"
    option = view._createNodeStyleOption(node)
    local_rect = view._nodeLocalRect(option, node)
    local_shape = view._nodeLocalShape(option, node)
    delegate = view._nodes_delegate
    assert delegate._nodeLocalRect(option, model, node) == local_rect
    assert delegate._nodeLocalShape(option, model, node) == local_shape

    position = QPointF(-350.25, 200.5)
    model.setNodePosition(node, position)
    view._zoom = 2.0
    view._pan = QPointF(30, 40)
    moved_option = view._createNodeStyleOption(node)
    assert moved_option.rect == option.rect
    assert view._nodeLocalRect(moved_option, node) == local_rect
    assert view._nodeLocalShape(moved_option, node) == local_shape
    assert delegate._nodeLocalRect(moved_option, model, node) == local_rect
    assert delegate._nodeLocalShape(moved_option, model, node) == local_shape
    assert view._nodeSceneRect(moved_option, node) == local_rect.translated(position)
    assert view._nodeSceneShape(moved_option, node) == local_shape.translated(position)

    # Callers may transform returned values without modifying the cached layout.
    returned_rect = view._nodeLocalRect(moved_option, node)
    returned_shape = view._nodeLocalShape(moved_option, node)
    returned_rect.translate(position)
    returned_shape.translate(position)
    assert view._nodeLocalRect(moved_option, node) == local_rect
    assert view._nodeLocalShape(moved_option, node) == local_shape


def test_group_drag_reuses_geometry_for_bounds_hit_testing_and_paint(
    graph_view: tuple[DirectionalGraphView5, PyGraphRTGraphModel],
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    view, model = graph_view
    view._zoom = 1.5
    view._pan = QPointF(30, 20)
    view._selection_model.selectNodes(list(model.nodes()))
    render(view)
    before = {
        node: view._nodeSceneRect(view._createNodeStyleOption(node), node)
        for node in model.nodes()
    }
    inlet_before = view._inletPos("second", "value")
    link = next(iter(model.links()))
    link_before = view._linkShape(link)

    def unexpected_measurement(*args: object, **kwargs: object) -> None:
        pytest.fail("Moving and painting cached nodes must not measure their labels again")

    monkeypatch.setattr(view._nodes_delegate, "createNodeLocalGeometry", unexpected_measurement)
    start = view.mapFromScene(model.nodePosition("second")).toPoint()
    qtbot.mousePress(view, Qt.MouseButton.LeftButton, pos=start)
    delta = QPointF(80, 40)
    end = start + (delta * view._zoom).toPoint()
    view.mouseMoveEvent(QMouseEvent(
        QEvent.Type.MouseMove, QPointF(end), QPointF(view.mapToGlobal(end)),
        Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    ))
    qtbot.mouseRelease(view, Qt.MouseButton.LeftButton, pos=end)

    for node in model.nodes():
        rect = view._nodeSceneRect(view._createNodeStyleOption(node), node)
        assert rect == before[node].translated(delta)
        item = view.itemAt(view.mapFromScene(model.nodePosition(node)))
        assert item is not None and item.kind == "node" and item.item == node
    assert view._inletPos("second", "value") == inlet_before + delta
    assert view._linkShape(link) == link_before.translated(delta)
    render(view)


def test_result_label_change_remeasures_only_the_changed_node(
    graph_view: tuple[DirectionalGraphView5, PyGraphRTGraphModel],
) -> None:
    view, model = graph_view
    render(view)
    old_geometry = dict(view._node_local_geometry)
    node = model.mapToSource("second")
    model._on_evaluated({node: rt.ExecutionFailure(node, ValueError("A much longer error label"))})

    rect = view._nodeSceneRect(view._createNodeStyleOption("second"), "second")
    assert rect.width() > old_geometry["second"].bounding_rect.width()
    assert view._node_local_geometry["first"] is old_geometry["first"]
    assert view._node_local_geometry["third"] is old_geometry["third"]
    cached_image = render(view)
    view._node_local_geometry.clear()
    assert render(view) == cached_image


def test_palette_and_selection_stay_live_without_remeasuring(
    graph_view: tuple[DirectionalGraphView5, PyGraphRTGraphModel],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    view, model = graph_view
    before = render(view)

    def unexpected_measurement(*args: object, **kwargs: object) -> None:
        pytest.fail("Palette and selection changes must reuse node layout")

    monkeypatch.setattr(view._nodes_delegate, "createNodeLocalGeometry", unexpected_measurement)
    palette = view.palette()
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("magenta"))
    view.setPalette(palette)
    recolored = render(view)
    assert recolored != before
    view._selection_model.selectNode("second")
    assert render(view) != recolored


def test_font_change_remeasures_bounds(
    graph_view: tuple[DirectionalGraphView5, PyGraphRTGraphModel],
) -> None:
    view, _ = graph_view
    before = view._nodeSceneRect(view._createNodeStyleOption("first"), "first")
    font = view.font()
    font.setPointSizeF(font.pointSizeF() * 2)
    view.setFont(font)
    after = view._nodeSceneRect(view._createNodeStyleOption("first"), "first")
    assert after.width() > before.width()
    assert after.height() > before.height()


@pytest.mark.parametrize("change", ["reset", "replace", "remove"])
def test_model_lifecycle_discards_cached_nodes(
    graph_view: tuple[DirectionalGraphView5, PyGraphRTGraphModel], change: str,
) -> None:
    view, model = graph_view
    view._createNodeStyleOption("first")
    assert "first" in view._node_local_geometry
    if change == "reset":
        model._beginResetModel()
        model._endResetModel()
    elif change == "replace":
        replacement = make_model()
        view.setModel(replacement)
        replacement.close()
        replacement._evaluator.close()
    else:
        model.removeNodes(["first"])
    assert "first" not in view._node_local_geometry


def test_changed_ports_reposition_without_stale_node_bounds(
    graph_view: tuple[DirectionalGraphView5, PyGraphRTGraphModel],
) -> None:
    view, model = graph_view
    previous = view._inletPos("second", "value")
    second = model.mapToSource("second")
    second.set_inputs(model.mapToSource("first"), extra=2, another=3)
    assert view._inletPos("second", "value") != previous
    assert view._inletPos("second", "extra").x() > view._inletPos("second", "value").x()
