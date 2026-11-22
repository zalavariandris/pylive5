"""Exercise view-owned positions through the eager graph adapter and Qt events."""

from importlib import import_module
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot
from qtpy.QtCore import QEvent, QObject, QPoint, QPointF, Qt
from qtpy.QtGui import QRegion

from qdageditor5.models.abstract_dag_model import AbstractDAGModel, DirectionalLinkId, NodeName
from qdageditor5.views.directional_graph_view_5 import (
    DirectionalGraphView5, LinkingToolData, _GraphItemId,
)


@pytest.fixture
def graph_view(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch,
) -> tuple[DirectionalGraphView5, AbstractDAGModel]:
    root = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(root))
    monkeypatch.syspath_prepend(str(root / "GraphCook" / "src"))
    monkeypatch.syspath_prepend(str(root / "myqtx" / "src"))
    example = import_module("GraphCook.examples.eager_qdageditor")
    engine = example.EagerEngine(
        "def source(): return 1\n"
        "def target(value, other): return value + other\n"
    )
    source = engine.node("source")
    target = engine.node("target")
    engine.add_link(source, target, "value")
    engine.add_link(source, target, "other")
    model = example.EagerGraphModel(engine)
    view = DirectionalGraphView5()
    view.resize(800, 600)
    view.setModel(model)
    qtbot.addWidget(view)
    return view, model


def test_adapter_links_have_editor_shape_and_filter_inlets(
    graph_view: tuple[DirectionalGraphView5, AbstractDAGModel],
) -> None:
    _, model = graph_view
    source, target = model.nodes()
    links = [(source, "out", target, inlet) for inlet in ("value", "other")]
    assert list(model.links()) == links
    assert set(model.outLinks(source, "out")) == set(links)
    assert list(model.outLinks(source, "missing")) == []
    for link in links:
        assert list(model.inLinks(target, link[3])) == [link]
        assert model.linkSource(link) == (source, "out")
        assert model.linkTarget(link) == (target, link[3])


def test_engine_attributes_supply_node_signature_to_adapter(
    graph_view: tuple[DirectionalGraphView5, AbstractDAGModel],
) -> None:
    _, model = graph_view
    source, target = model.nodes()
    assert model.nodeHeaderData(source) == "source"
    assert model.nodeHeaderData(target) == "target"
    assert list(model.inlets(target)) == ["value", "other"]


def test_drag_twice_with_zoom_updates_nodes_ports_and_links(
    graph_view: tuple[DirectionalGraphView5, AbstractDAGModel], qtbot: QtBot,
) -> None:
    view, model = graph_view
    source, target = model.nodes()
    view.setNodePosition(source, QPointF(100, 100))
    view.setNodePosition(target, QPointF(100, 300))
    view._zoom = 1.5
    view._pan = QPointF(20, 30)
    view.show()
    qtbot.waitExposed(view)
    link = next(iter(model.links()))

    for delta in (QPoint(60, 30), QPoint(-30, 60)):
        old_position = view.nodePosition(source)
        old_port = view._outletPos(source, "out")
        old_link = view._linkSceneShape(link)
        body = view._nodeSceneRect(view._nodeStyleOption(source), source)
        start = view.mapFromScene(body.center()).toPoint()
        qtbot.mousePress(view, Qt.MouseButton.LeftButton, pos=start)
        qtbot.mouseMove(view, pos=start + delta)
        qtbot.mouseRelease(view, Qt.MouseButton.LeftButton, pos=start + delta)

        scene_delta = QPointF(delta) / view._zoom
        assert view.nodePosition(source) == old_position + scene_delta
        assert view._outletPos(source, "out") == old_port + scene_delta
        assert view._linkSceneShape(link) != old_link
        moved_body = view._nodeSceneRect(view._nodeStyleOption(source), source)
        assert view.itemAt(view.mapFromScene(moved_body.center())) == ("node", source)
        assert model.nodePosition(source) is None


def test_l_shortcut_layouts_nodes_without_model_positions(
    graph_view: tuple[DirectionalGraphView5, AbstractDAGModel], qtbot: QtBot,
) -> None:
    view, model = graph_view
    source, target = model.nodes()
    view.show()
    view.activateWindow()
    view.setFocus()
    qtbot.waitUntil(view.hasFocus)
    for node in model.nodes():
        view.setNodePosition(node, QPointF())
    qtbot.keyClick(view, Qt.Key.Key_L)
    qtbot.waitUntil(lambda: view.nodePosition(source) != view.nodePosition(target))
    assert all(model.nodePosition(node) is None for node in model.nodes())
    view.fitNodes()
    for node in model.nodes():
        body = view._nodeSceneRect(view._nodeStyleOption(node), node)
        assert view.rect().contains(view.mapFromScene(body.center()).toPoint())


def test_positions_are_per_view_and_survive_geometry_invalidation(
    graph_view: tuple[DirectionalGraphView5, AbstractDAGModel], qtbot: QtBot,
) -> None:
    view, model = graph_view
    node = next(iter(model.nodes()))
    other_view = DirectionalGraphView5()
    other_view.setModel(model)
    qtbot.addWidget(other_view)
    other_position = other_view.nodePosition(node)
    position = QPointF(120, 140)
    view.setNodePosition(node, position)
    position.setX(999)
    returned_position = view.nodePosition(node)
    returned_position.setY(999)
    model.nodesDataChanged.emit((node,), ())
    assert view.nodePosition(node) == QPointF(120, 140)
    assert other_view.nodePosition(node) == other_position


def test_example_window_layouts_disconnected_nodes(
    graph_view: tuple[DirectionalGraphView5, AbstractDAGModel], qtbot: QtBot,
) -> None:
    example = import_module("GraphCook.examples.eager_qdageditor")
    engine = example.EagerEngine("def source(): return 1\n")
    for _ in range(3):
        engine.node("source")
    window = example.EngineWindow(engine)
    qtbot.addWidget(window)
    window.editor.layout_nodes()
    positions = [window.editor.nodePosition(node) for node in window.model.nodes()]
    assert len({(position.x(), position.y()) for position in positions}) == 3


@pytest.mark.parametrize("event", ["remove", "reset", "replace"])
def test_positions_are_discarded_on_lifecycle_changes(
    graph_view: tuple[DirectionalGraphView5, AbstractDAGModel], event: str,
) -> None:
    view, model = graph_view
    node = next(iter(model.nodes()))
    initial_position = view.nodePosition(node)
    view.setNodePosition(node, QPointF(120, 140))
    if event == "remove":
        model.nodesRemoved.emit((node,))
    elif event == "reset":
        model._beginResetModel()
        model._endResetModel()
    else:
        view.setModel(None)
        view.setModel(model)
    expected = initial_position if event == "replace" else QPointF()
    assert view.nodePosition(node) == expected


@pytest.mark.parametrize("writable", [False, True])
def test_model_positions_remain_authoritative(
    graph_view: tuple[DirectionalGraphView5, AbstractDAGModel],
    monkeypatch: pytest.MonkeyPatch, writable: bool,
) -> None:
    view, model = graph_view
    node = next(iter(model.nodes()))
    positions = {item: QPointF(100, 100) for item in model.nodes()}

    def get_position(item: NodeName) -> QPointF:
        return QPointF(positions[item])

    def set_position(item: NodeName, position: QPointF) -> bool:
        model.nodeAboutToMove.emit(item)
        positions[item] = QPointF(position)
        model.nodeMoved.emit(item)
        return True

    monkeypatch.setattr(model, "nodePosition", get_position)
    if writable:
        monkeypatch.setattr(model, "setNodePosition", set_position)
    assert view.setNodePosition(node, QPointF(200, 250)) is writable
    expected = QPointF(200, 250) if writable else QPointF(100, 100)
    assert model.nodePosition(node) == view.nodePosition(node) == expected


@pytest.mark.parametrize("endpoint", ["head", "tail"])
@pytest.mark.parametrize("destination", ["empty", "socket"])
@pytest.mark.parametrize("allow_removal", [False, True])
def test_endpoint_drop_respects_removal_result(
    graph_view: tuple[DirectionalGraphView5, AbstractDAGModel],
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch,
    endpoint: str, destination: str, allow_removal: bool,
) -> None:
    view, model = graph_view
    source, target = model.nodes()
    view.setNodePosition(source, QPointF(150, 150))
    view.setNodePosition(target, QPointF(350, 400))
    view._zoom = 1.0
    view._pan = QPointF()
    view.show()
    qtbot.waitExposed(view)
    original_links = list(model.links())
    link = original_links[0]
    requests: list[DirectionalLinkId] = []
    view.requestLink.connect(lambda *args: requests.append(args))

    def remove_links(links: list[DirectionalLinkId]) -> bool:
        model._beginRemoveLinks(links)
        for src, _, dst, inlet in links:
            model.engine.graph.remove_link(src, dst, inlet)
        model._endRemoveLinks()
        return True

    if allow_removal:
        monkeypatch.setattr(model, "removeLinks", remove_links)

    if destination == "empty":
        drop = QPointF(650, 150 if endpoint == "head" else 500)
    elif endpoint == "head":
        drop = view._inletPos(target, "other")
    else:
        drop = view._outletPos(target, "out")

    view._tool = LinkingToolData(_GraphItemId(endpoint, link), drop)
    view.repaint()

    class PaintRecorder(QObject):
        def __init__(self) -> None:
            super().__init__()
            self.region = QRegion()

        def eventFilter(self, watched: QObject, event: QEvent) -> bool:
            if event.type() == QEvent.Type.Paint:
                self.region = self.region.united(event.region())
            return False

    recorder = PaintRecorder()
    view.installEventFilter(recorder)
    original_bounds = view.mapFromScene(view._linkSceneRect(link)).toAlignedRect()
    qtbot.mouseRelease(view, Qt.MouseButton.LeftButton, pos=view.mapFromScene(drop).toPoint())
    qtbot.waitUntil(lambda: recorder.region.contains(original_bounds))
    assert view._tool is None
    assert list(model.links()) == (original_links[1:] if allow_removal else original_links)
    if allow_removal and destination == "socket":
        expected = (source, "out", target, "other") if endpoint == "head" else (
            target, "out", target, "value"
        )
        assert requests == [expected]
    else:
        assert requests == []


def test_occupied_inlet_reports_error_and_preserves_engine_links(
    graph_view: tuple[DirectionalGraphView5, AbstractDAGModel], qtbot: QtBot,
) -> None:
    example = import_module("GraphCook.examples.eager_qdageditor")
    engine = example.EagerEngine(
        "def source(): return 1\n"
        "def target(value, other): return value + other\n"
    )
    source = engine.node("source")
    another_source = engine.node("source")
    target = engine.node("target")
    engine.add_link(source, target, "value")
    window = example.EngineWindow(engine)
    qtbot.addWidget(window)
    before = list(engine.links())

    window.editor.requestLink.emit(another_source, "out", target, "value")
    assert list(engine.links()) == before
    assert "Inlet already connected" in window.statusBar().currentMessage()

    window.editor.requestLink.emit(another_source, "out", target, "other")
    assert list(engine.links()) == before + [(another_source, target, "other")]
    assert window.statusBar().currentMessage() == ""
