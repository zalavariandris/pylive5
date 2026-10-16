"""Exercise node drops, popup cancellation and connected inlet geometry."""

from collections.abc import Iterable

import pytest
from pytestqt.qtbot import QtBot
from qtpy.QtCore import QEvent, QPoint, QPointF, Qt, QTimer
from qtpy.QtGui import QAction, QMouseEvent
from qtpy.QtWidgets import QMenu

from qdageditor5.core.item_data_roles import SocketDataRole
from qdageditor5.models.abstract_dag_model import (
    AbstractDAGModel, DirectionalLinkId, InletName, NodeName, OutletName,
)
from qdageditor5.views.directional_graph_view_5 import (
    DirectionalGraphView5, LinkingToolData, _GraphItemId,
)


class HiddenInletsModel(AbstractDAGModel):
    def __init__(self) -> None:
        super().__init__()
        self.ports: dict[NodeName, list[InletName]] = {
            "source": [], "old": ["value"], "target": ["visible", "hidden"],
        }
        self.hidden: set[InletName] = {"hidden"}
        self.connections: list[DirectionalLinkId] = []

    def nodes(self) -> Iterable[NodeName]:
        return tuple(self.ports)

    def nodeData(self, node: NodeName, role: int = Qt.ItemDataRole.DisplayRole) -> object:
        return str(node) if role == Qt.ItemDataRole.DisplayRole else None

    def nodePosition(self, node: NodeName) -> QPointF:
        return QPointF(200, 80 + tuple(self.ports).index(node) * 120)

    def nodeCellCount(self, node: NodeName) -> int:
        return 0

    def nodeCellData(self, node: NodeName, column: int, role: int) -> object:
        return None

    def inlets(self, node: NodeName) -> Iterable[InletName]:
        return tuple(self.ports[node])

    def inletData(self, node: NodeName, inlet: InletName, role: int) -> object:
        if role == SocketDataRole.HiddenRole:
            return inlet in self.hidden
        return str(inlet) if role == Qt.ItemDataRole.DisplayRole else None

    def outlets(self, node: NodeName) -> Iterable[OutletName]:
        return ("out",)

    def outletData(self, node: NodeName, outlet: OutletName, role: int) -> object:
        return str(outlet) if role == Qt.ItemDataRole.DisplayRole else None

    def inLinks(self, node: NodeName, inlet: InletName) -> Iterable[DirectionalLinkId]:
        return tuple(link for link in self.connections if link[2:] == (node, inlet))

    def outLinks(self, node: NodeName, outlet: OutletName) -> Iterable[DirectionalLinkId]:
        return tuple(link for link in self.connections if link[:2] == (node, outlet))

    def links(self) -> Iterable[DirectionalLinkId]:
        return tuple(self.connections)

    def linkSource(self, link: DirectionalLinkId) -> tuple[NodeName, OutletName]:
        return link[0], link[1]

    def linkTarget(self, link: DirectionalLinkId) -> tuple[NodeName, InletName]:
        return link[2], link[3]

    def add_link(
        self, source: NodeName, outlet: OutletName, target: NodeName, inlet: InletName,
    ) -> None:
        link = (source, outlet, target, inlet)
        self._beginAddLinks((link,))
        self.connections.append(link)
        self._endAddLinks()

    def removeLinks(self, links: Iterable[DirectionalLinkId]) -> bool:
        links = tuple(links)
        self._beginRemoveLinks(links)
        for link in links:
            self.connections.remove(link)
        self._endRemoveLinks()
        return True


@pytest.fixture
def graph_view(qtbot: QtBot) -> tuple[DirectionalGraphView5, HiddenInletsModel]:
    model = HiddenInletsModel()
    view = DirectionalGraphView5()
    view.resize(800, 650)
    view.setModel(model)
    view.requestLink.connect(model.add_link)
    qtbot.addWidget(view)
    return view, model


def drop_on_node(
    view: DirectionalGraphView5,
    model: HiddenInletsModel,
    start: _GraphItemId | None = None,
) -> None:
    position = view.mapFromScene(model.nodePosition("target")).toPoint()
    if start is None:
        start = _GraphItemId("outlet", ("source", "out"))
    view._tool = LinkingToolData(start, view.mapToScene(QPointF(position)))
    view.mouseReleaseEvent(QMouseEvent(
        QEvent.Type.MouseButtonRelease, QPointF(position),
        QPointF(view.mapToGlobal(position)), Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
    ))


@pytest.mark.parametrize("chosen", ["visible", "hidden"])
def test_node_popup_lists_all_inlets_and_connects_selection(
    graph_view: tuple[DirectionalGraphView5, HiddenInletsModel],
    monkeypatch: pytest.MonkeyPatch,
    chosen: str,
) -> None:
    view, model = graph_view
    view._zoom = 1.5
    view._pan = QPointF(25, 30)

    def choose(menu: QMenu, position: QPoint) -> QAction:
        assert view._tool is None
        assert [action.text() for action in menu.actions()] == ["visible", "hidden"]
        expected = view.mapFromScene(model.nodePosition("target")).toPoint()
        assert position == view.mapToGlobal(expected)
        return next(action for action in menu.actions() if action.text() == chosen)

    monkeypatch.setattr(QMenu, "exec", choose)
    drop_on_node(view, model)
    assert model.connections == [("source", "out", "target", chosen)]
    item = view.itemAt(view.mapFromScene(view._inletPos("target", chosen)))
    assert item == _GraphItemId("inlet", ("target", chosen))
    assert view._tool is None


@pytest.mark.parametrize("ports", ["visible", "empty", "already_connected"])
def test_no_menu_when_no_inlets_are_hidden(
    graph_view: tuple[DirectionalGraphView5, HiddenInletsModel],
    monkeypatch: pytest.MonkeyPatch,
    ports: str,
) -> None:
    view, model = graph_view
    if ports == "visible":
        model.hidden.clear()
    elif ports == "empty":
        model.ports["target"] = []
    else:
        model.add_link("source", "out", "target", "hidden")
    before = list(model.connections)

    def unexpected_menu(*args: object) -> None:
        pytest.fail("A node with no hidden inlets must not create a menu")

    monkeypatch.setattr(QMenu, "__init__", unexpected_menu)
    drop_on_node(view, model)
    assert model.connections == before
    assert view._tool is None


@pytest.mark.parametrize("choose", [False, True])
def test_reconnecting_head_preserves_old_link_until_selection(
    graph_view: tuple[DirectionalGraphView5, HiddenInletsModel],
    monkeypatch: pytest.MonkeyPatch,
    choose: bool,
) -> None:
    view, model = graph_view
    original = ("source", "out", "old", "value")
    model.add_link(*original)

    def select(menu: QMenu, position: QPoint) -> QAction | None:
        assert model.connections == [original]
        return menu.actions()[1] if choose else None

    monkeypatch.setattr(QMenu, "exec", select)
    drop_on_node(view, model, _GraphItemId("head", original))
    expected = ("source", "out", "target", "hidden") if choose else original
    assert model.connections == [expected]


def test_direct_socket_drop_does_not_open_menu(
    graph_view: tuple[DirectionalGraphView5, HiddenInletsModel],
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    view, model = graph_view

    def unexpected_menu(*args: object) -> None:
        pytest.fail("Direct socket drops should connect immediately")

    monkeypatch.setattr(QMenu, "__init__", unexpected_menu)
    start = view.mapFromScene(view._outletPos("source", "out")).toPoint()
    end = view.mapFromScene(view._inletPos("target", "visible")).toPoint()
    qtbot.mousePress(view, Qt.MouseButton.LeftButton, pos=start)
    qtbot.mouseRelease(view, Qt.MouseButton.LeftButton, pos=end)
    assert model.connections == [("source", "out", "target", "visible")]


@pytest.mark.parametrize("change", ["replace_model", "remove_node", "remove_inlet", "reject_link"])
def test_stale_selection_does_not_remove_existing_link(
    graph_view: tuple[DirectionalGraphView5, HiddenInletsModel],
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    view, model = graph_view
    original = ("source", "out", "old", "value")
    model.add_link(*original)

    def select(menu: QMenu, position: QPoint) -> QAction:
        if change == "replace_model":
            view.setModel(HiddenInletsModel())
        elif change == "remove_node":
            del model.ports["target"]
        elif change == "remove_inlet":
            model.ports["target"].remove("hidden")
        else:
            monkeypatch.setattr(model, "canCompleteLink", lambda *args: False)
        return menu.actions()[1]

    monkeypatch.setattr(QMenu, "exec", select)
    drop_on_node(view, model, _GraphItemId("head", original))
    assert model.connections == [original]


def test_menu_disables_rejected_links(
    graph_view: tuple[DirectionalGraphView5, HiddenInletsModel],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    view, model = graph_view

    def can_link(source: NodeName, outlet: OutletName, target: NodeName, inlet: InletName) -> bool:
        return inlet != "hidden"

    def select(menu: QMenu, position: QPoint) -> None:
        assert [action.isEnabled() for action in menu.actions()] == [True, False]

    monkeypatch.setattr(model, "canCompleteLink", can_link)
    monkeypatch.setattr(QMenu, "exec", select)
    drop_on_node(view, model)
    assert model.connections == []


@pytest.mark.parametrize("cancel", [False, True])
def test_real_popup_handles_mouse_selection_and_escape(
    graph_view: tuple[DirectionalGraphView5, HiddenInletsModel],
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    cancel: bool,
) -> None:
    view, model = graph_view
    original_exec = QMenu.exec

    def execute(menu: QMenu, position: QPoint) -> QAction | None:
        def interact() -> None:
            if cancel:
                qtbot.keyClick(menu, Qt.Key.Key_Escape)
            else:
                point = menu.actionGeometry(menu.actions()[1]).center()
                qtbot.mouseClick(menu, Qt.MouseButton.LeftButton, pos=point)

        QTimer.singleShot(0, interact)
        return original_exec(menu, position)

    monkeypatch.setattr(QMenu, "exec", execute)
    drop_on_node(view, model)
    assert model.connections == ([] if cancel else [("source", "out", "target", "hidden")])
    assert view._tool is None


@pytest.mark.parametrize("removal", ["remove", "reset"])
def test_connected_hidden_inlet_repositions_and_invalidates_bounds(
    graph_view: tuple[DirectionalGraphView5, HiddenInletsModel],
    removal: str,
) -> None:
    view, model = graph_view
    original_position = view._inletPos("target", "visible")
    original_bounds = view._nodeLocalPaintedRect("target")
    model.add_link("source", "out", "target", "hidden")
    assert "target" not in view._node_local_painted_rects
    assert view._inletPos("target", "visible") != original_position
    assert view._inletPos("target", "hidden") != view._inletPos("target", "visible")
    view._nodeLocalPaintedRect("target")

    if removal == "remove":
        model.removeLinks(model.connections)
    else:
        model.linksAboutToBeReset.emit()
        model.connections.clear()
        model.linksReset.emit()
    assert "target" not in view._node_local_painted_rects
    assert view._inletPos("target", "visible") == original_position
    assert view._nodeLocalPaintedRect("target") == original_bounds
