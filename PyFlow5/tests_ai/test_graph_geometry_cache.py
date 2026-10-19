"""Regression checks for view-owned geometry during interactive node movement."""

from collections.abc import Iterator
from unittest.mock import patch

import pytest
from pytestqt.qtbot import QtBot
from qtpy.QtCore import QEvent, QPoint, QPointF, QRectF, Qt
from qtpy.QtGui import QColor, QImage, QMouseEvent, QPainter, QPainterPath, QPalette
from qtpy.QtWidgets import QStyleOptionViewItem

import pygraphrt as rt
from pyflow5.models.pygraphrt_graphmodel import PyGraphRTGraphModel
from pyflow5.core.input_roles import InputDataRole
from qdageditor5.core.item_data_roles import NodeDataRole
from qdageditor5.models.abstract_dag_model import AbstractDAGModel, NodeName
from qdageditor5.models.graph_selection_model import GraphSelectionModel
from qdageditor5.views.directional_graph_view_5 import DirectionalGraphView5
from qdageditor5.views.styled_node_delegate import StyledNodeDelegate


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
    engine = rt.GraphEvaluatorEngine(graph, registry, backend=rt.InlineExecutionBackend())
    model = PyGraphRTGraphModel(engine)
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
    model._engine.close()


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
    option = view._nodeStyleOption(node)
    local_rect = view._nodeLocalRect(option, node)
    local_shape = view._nodeLocalShape(option, node)
    delegate = view._nodes_delegate
    assert delegate._nodeLocalRect(option, model, node) == local_rect
    assert delegate._nodeLocalShape(option, model, node) == local_shape

    position = QPointF(-350.25, 200.5)
    model.setNodePosition(node, position)
    view._zoom = 2.0
    view._pan = QPointF(30, 40)
    moved_option = view._nodeStyleOption(node)
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
        node: view._nodeSceneRect(view._nodeStyleOption(node), node)
        for node in model.nodes()
    }
    inlet_before = view._inletPos("second", "value")
    link = next(iter(model.links()))
    link_before = view._linkSceneShape(link)

    def unexpected_measurement(*args: object, **kwargs: object) -> None:
        pytest.fail("Moving and painting cached nodes must reuse their bounds and shape")

    monkeypatch.setattr(view._nodes_delegate, "_nodeLocalRect", unexpected_measurement)
    monkeypatch.setattr(view._nodes_delegate, "_nodeLocalShape", unexpected_measurement)
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
        rect = view._nodeSceneRect(view._nodeStyleOption(node), node)
        assert rect == before[node].translated(delta)
        item = view.itemAt(view.mapFromScene(model.nodePosition(node)))
        assert item is not None and item.kind == "node" and item.item == node
    assert view._inletPos("second", "value") == inlet_before + delta
    assert view._linkSceneShape(link) == link_before.translated(delta)
    render(view)


def test_result_label_change_remeasures_only_the_changed_node(
    graph_view: tuple[DirectionalGraphView5, PyGraphRTGraphModel],
) -> None:
    view, model = graph_view
    render(view)
    old_cache = dict(view._node_item_cache)
    node = model.mapToSource("second")
    model._on_evaluated({node: rt.ExecutionFailure(node, ValueError("A much longer error label"))})

    rect = view._nodeSceneRect(view._nodeStyleOption("second"), "second")
    assert rect.width() > old_cache["second"].bounding_rect.width()
    assert view._node_item_cache["first"] is old_cache["first"]
    assert view._node_item_cache["third"] is old_cache["third"]
    cached_image = render(view)
    view._node_item_cache.clear()
    assert render(view) == cached_image


def test_palette_and_selection_stay_live_without_remeasuring(
    graph_view: tuple[DirectionalGraphView5, PyGraphRTGraphModel],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    view, model = graph_view
    before = render(view)

    def unexpected_measurement(*args: object, **kwargs: object) -> None:
        pytest.fail("Palette and selection changes must reuse node layout")

    monkeypatch.setattr(view._nodes_delegate, "_nodeLocalRect", unexpected_measurement)
    monkeypatch.setattr(view._nodes_delegate, "_nodeLocalShape", unexpected_measurement)
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
    before = view._nodeSceneRect(view._nodeStyleOption("first"), "first")
    font = view.font()
    font.setPointSizeF(font.pointSizeF() * 2)
    view.setFont(font)
    after = view._nodeSceneRect(view._nodeStyleOption("first"), "first")
    assert after.width() > before.width()
    assert after.height() > before.height()


@pytest.mark.parametrize("change", ["reset", "replace", "remove"])
def test_model_lifecycle_discards_cached_nodes(
    graph_view: tuple[DirectionalGraphView5, PyGraphRTGraphModel], change: str,
) -> None:
    view, model = graph_view
    render(view)
    assert "first" in view._node_item_cache
    assert "first" in view._outlet_item_cache
    assert view._link_item_cache
    if change == "reset":
        model._beginResetModel()
        model._endResetModel()
    elif change == "replace":
        replacement = make_model()
        view.setModel(replacement)
        replacement.close()
        replacement._engine.close()
    else:
        model.removeNodes(["first"])
    assert "first" not in view._node_item_cache
    assert "first" not in view._outlet_item_cache
    assert all(source != "first" and target != "first" for source, _, target, _ in view._link_item_cache)


def test_view_owns_geometry_returned_by_a_custom_delegate(
    graph_view: tuple[DirectionalGraphView5, PyGraphRTGraphModel],
) -> None:
    view, model = graph_view
    local_rect = QRectF(-60, -20, 120, 40)
    local_shape = QPainterPath()
    local_shape.addEllipse(QRectF(-40, -15, 80, 30))
    painted_nodes: list[NodeName] = []

    class CustomDelegate(StyledNodeDelegate):
        def _nodeLocalRect(
            self, option: QStyleOptionViewItem, model: AbstractDAGModel, node: NodeName,
        ) -> QRectF:
            return local_rect

        def _nodeLocalShape(
            self, option: QStyleOptionViewItem, model: AbstractDAGModel, node: NodeName,
        ) -> QPainterPath:
            return local_shape

        def paint(
            self, painter: QPainter, option: QStyleOptionViewItem,
            model: AbstractDAGModel, node: NodeName,
        ) -> None:
            painted_nodes.append(node)
            painter.fillRect(option.rect, QColor("cyan"))

    view._nodes_delegate = CustomDelegate()
    option = view._nodeStyleOption("first")
    expected_rect = QRectF(local_rect)
    expected_shape = QPainterPath(local_shape)
    assert view._nodeLocalRect(option, "first") == expected_rect
    assert view._nodeLocalShape(option, "first") == expected_shape
    assert option.rect == expected_shape.boundingRect().toAlignedRect()
    render(view)
    assert set(painted_nodes) == set(model.nodes())

    # The delegate may retain mutable Qt objects; the view owns its copies.
    local_rect.translate(100, 100)
    local_shape.translate(100, 100)
    assert view._nodeLocalRect(option, "first") == expected_rect
    assert view._nodeLocalShape(option, "first") == expected_shape


@pytest.mark.parametrize("role", [NodeDataRole.LeadingRole, NodeDataRole.TrailingRole])
def test_paint_reads_current_labels_without_rebuilding_the_cache(
    graph_view: tuple[DirectionalGraphView5, PyGraphRTGraphModel],
    monkeypatch: pytest.MonkeyPatch,
    role: int,
) -> None:
    view, model = graph_view
    original_node_data = model.nodeData
    label = "123"

    def node_data(node: NodeName, requested_role: int = Qt.ItemDataRole.DisplayRole) -> object:
        if node == "second" and requested_role == role:
            return label
        return original_node_data(node, requested_role)

    monkeypatch.setattr(model, "nodeData", node_data)
    before = render(view)
    cached = view._node_item_cache["second"]

    # Deliberately skip a data-change signal to check that paint owns its labels.
    label = "updated label"
    assert render(view) != before
    assert view._node_item_cache["second"] is cached


def test_changed_ports_reposition_without_stale_node_bounds(
    graph_view: tuple[DirectionalGraphView5, PyGraphRTGraphModel],
) -> None:
    view, model = graph_view
    previous = view._inletPos("second", "value")
    second = model.mapToSource("second")
    second.set_inputs(model.mapToSource("first"), extra=2, another=3)
    assert view._inletPos("second", "value") != previous
    assert view._inletPos("second", "extra").x() > view._inletPos("second", "value").x()


def test_node_shape_does_not_measure_label_bounds_until_requested(
    graph_view: tuple[DirectionalGraphView5, PyGraphRTGraphModel],
) -> None:
    view, _ = graph_view
    delegate = view._nodes_delegate
    with (
        patch.object(delegate, "_nodeLocalRect", wraps=delegate._nodeLocalRect) as measure_rect,
        patch.object(delegate, "_nodeLocalShape", wraps=delegate._nodeLocalShape) as measure_shape,
    ):
        option = view._nodeStyleOption("second")
        view._nodeLocalShape(option, "second")
        measure_shape.assert_called_once()
        measure_rect.assert_not_called()

        view._nodeLocalRect(option, "second")
        view._nodeLocalRect(option, "second")
        measure_rect.assert_called_once()


def test_warm_paint_builds_only_one_style_option_per_node(
    graph_view: tuple[DirectionalGraphView5, PyGraphRTGraphModel],
) -> None:
    view, model = graph_view
    before = render(view)
    with patch.object(view, "_nodeStyleOption", wraps=view._nodeStyleOption) as make_option:
        assert render(view) == before
        assert [call.args[0] for call in make_option.call_args_list] == list(model.nodes())


def test_cached_link_reads_do_not_resolve_endpoints_again(
    graph_view: tuple[DirectionalGraphView5, PyGraphRTGraphModel],
) -> None:
    view, model = graph_view
    link = next(iter(model.links()))
    shape = view._linkSceneShape(link)
    with (
        patch.object(view, "_outletPos", wraps=view._outletPos) as outlet_pos,
        patch.object(view, "_inletPos", wraps=view._inletPos) as inlet_pos,
    ):
        view._linkSceneRect(link)
        assert view._linkSceneShape(link) == shape
        outlet_pos.assert_not_called()
        inlet_pos.assert_not_called()


def test_moving_one_node_updates_link_endpoints_and_reuses_port_layout(
    graph_view: tuple[DirectionalGraphView5, PyGraphRTGraphModel],
) -> None:
    view, model = graph_view
    render(view)
    link = ("first", "out", "second", "value")
    view._get_affected_rect("first")
    old_shape = view._linkSceneShape(link)
    old_outlet = view._outletPos("first", "out")
    delta = QPointF(50, -30)
    with patch.object(view, "_nodeStyleOption", wraps=view._nodeStyleOption) as make_option:
        model.setNodePosition("first", model.nodePosition("first") + delta)
        assert view._outletPos("first", "out") == old_outlet + delta
        shape = view._linkSceneShape(link)
        assert shape != old_shape
        assert shape.pointAtPercent(0) == view._outletPos("first", "out")
        assert shape.pointAtPercent(1) == view._inletPos("second", "value")
        make_option.assert_not_called()


def test_outlet_positions_share_layout_and_follow_reordering(
    graph_view: tuple[DirectionalGraphView5, PyGraphRTGraphModel],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    view, model = graph_view
    original_outlets = model.outlets
    outlets = ["out", "extra"]
    monkeypatch.setattr(model, "outlets", lambda node: tuple(outlets) if node == "first" else original_outlets(node))
    with patch.object(view, "_nodeStyleOption", wraps=view._nodeStyleOption) as make_option:
        left = view._outletPos("first", "out")
        right = view._outletPos("first", "extra")
        view._outletRect("first", "out")
        view._outletShape("first", "extra")
        assert right.x() - left.x() == 10
        make_option.assert_called_once_with("first")

    outlets.reverse()
    model.outletsReset.emit("first")
    assert view._outletPos("first", "out") == right
    assert view._outletPos("first", "extra") == left


def test_inlet_value_can_resize_node_and_move_its_outlet_and_link(
    graph_view: tuple[DirectionalGraphView5, PyGraphRTGraphModel],
) -> None:
    view, model = graph_view
    second = model.mapToSource("second")
    second.set_inputs(value=40)

    class ValueSizedDelegate(StyledNodeDelegate):
        def _nodeLocalShape(
            self, option: QStyleOptionViewItem, model: AbstractDAGModel, node: NodeName,
        ) -> QPainterPath:
            if node != "second":
                return super()._nodeLocalShape(option, model, node)
            width = model.inletData(node, "value", InputDataRole.InputValueRole)
            shape = QPainterPath()
            shape.addRect(QRectF(0, 0, width, 20))
            return shape

    view._nodes_delegate = ValueSizedDelegate()
    link = ("second", "out", "third", "value")
    before = view._linkSceneShape(link)
    second.set_inputs(value=120)
    after = view._linkSceneShape(link)
    assert after.pointAtPercent(0).x() == before.pointAtPercent(0).x() + 40
    assert after.pointAtPercent(0) == view._outletPos("second", "out")
    assert after.pointAtPercent(1) == view._inletPos("third", "value")


def test_font_change_invalidates_links_before_any_node_option_is_requested(
    graph_view: tuple[DirectionalGraphView5, PyGraphRTGraphModel],
) -> None:
    view, model = graph_view
    link = ("first", "out", "second", "value")
    before = view._linkSceneShape(link)
    font = view.font()
    font.setPointSizeF(font.pointSizeF() * 2)
    view.setFont(font)
    after = view._linkSceneShape(link)
    assert after != before
    assert after.pointAtPercent(0) == view._outletPos("first", "out")
    assert after.pointAtPercent(1) == view._inletPos("second", "value")
