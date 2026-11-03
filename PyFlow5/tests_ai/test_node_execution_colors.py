"""Graph colors reflect runtime state, including asynchronous document loading."""

import json
from collections.abc import Iterator

import pytest
from pytestqt.qtbot import QtBot
from qtpy.QtCore import QCoreApplication, QPoint, QPointF, Qt
from qtpy.QtGui import QColor, QImage, QPainter, QPalette
from qtpy.QtWidgets import QStyleFactory

from PyGraphRT2.tests_ai.controlled_backend import ControlledBackend
from pygraphrt2 import Graph
from pyflow5.core.node_execution_state import NodeExecutionState
from pygraphrt2.execution_plan import ExecutionResult, NodeExecutionError, evaluate
from pyflow5.models.pyflow5_document import PyFlowDocument
from pyflow5.models.pygraphrt_graphmodel import PyGraphRTGraphModel
from qdageditor5.core.item_data_roles import NodeDataRole
from qdageditor5.models.graph_selection_model import GraphSelectionModel
from qdageditor5.views.directional_graph_view_5 import DirectionalGraphView5


SOURCE = "def answer(): return 42"


@pytest.fixture
def loading_document(
    qapp: object, monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[PyFlowDocument, ControlledBackend]]:
    backends: list[ControlledBackend] = []

    def make_backend(graph: Graph) -> ControlledBackend:
        backend = ControlledBackend(graph)
        backends.append(backend)
        return backend

    monkeypatch.setattr("pygraphrt2.engine.ThreadedBackend", make_backend)
    document = PyFlowDocument.deserialize(json.dumps({
        "version": 4,
        "script": {"source": SOURCE},
        "graph": {"nodes": {"answer": {"operator": "answer"}}},
    }))
    try:
        assert len(backends) == 1
        assert len(backends[0].evaluations) == 1
        yield document, backends[0]
    finally:
        document.close()


def test_opening_graph_is_yellow_then_normal_and_execution_repaints(
    loading_document: tuple[PyFlowDocument, ControlledBackend], qtbot: QtBot,
) -> None:
    document, backend = loading_document
    model = document.graph_model
    view = DirectionalGraphView5()
    qtbot.addWidget(view)
    view.setModel(model)
    changed_roles: list[tuple[int, ...]] = []
    model.nodesDataChanged.connect(lambda nodes, roles: changed_roles.append(tuple(roles)))

    assert model.nodeData("answer", model.StateRole) is NodeExecutionState.EXECUTING
    assert model.nodeData("answer", Qt.ItemDataRole.BackgroundRole) == QColor("yellow")
    option = view._nodeStyleOption("answer")
    assert option.backgroundBrush.color() == QColor("yellow")
    assert option.palette.color(QPalette.ColorRole.Text) == QColor("black")
    assert model.nodeData("answer", NodeDataRole.TrailingRole) is None

    backend.evaluations[-1].set_result(evaluate(SOURCE))
    QCoreApplication.processEvents()
    assert model.nodeData("answer", model.StateRole) is NodeExecutionState.IDLE
    assert model.nodeData("answer", Qt.ItemDataRole.BackgroundRole) is None
    assert not document.isModified()

    changed_roles.clear()
    document.subscribeNode("answer", lambda _: None)
    assert model.nodeData("answer", Qt.ItemDataRole.BackgroundRole) == QColor("yellow")
    assert any(Qt.ItemDataRole.BackgroundRole in roles for roles in changed_roles)
    QCoreApplication.processEvents()
    backend.executions[-1].set_result(ExecutionResult({"answer": 42}))
    QCoreApplication.processEvents()
    assert model.nodeData("answer", model.StateRole) is NodeExecutionState.IDLE
    assert model.nodeData("answer", Qt.ItemDataRole.BackgroundRole) is None
    assert model.nodeData("answer", model.OutputRole) == 42
    assert not document.isModified()


@pytest.mark.parametrize("failure", ["script", "missing", "execution"])
def test_real_errors_turn_red_and_recovery_removes_error_text(
    loading_document: tuple[PyFlowDocument, ControlledBackend], failure: str,
) -> None:
    document, backend = loading_document
    model = document.graph_model
    if failure == "script":
        backend.evaluations[-1].set_exception(SyntaxError("broken source"))
    elif failure == "missing":
        backend.evaluations[-1].set_result({})
    else:
        backend.evaluations[-1].set_result(evaluate(SOURCE))
    QCoreApplication.processEvents()
    if failure == "execution":
        document.subscribeNode("answer", lambda _: None)
        QCoreApplication.processEvents()
        backend.executions[-1].set_exception(NodeExecutionError("answer", ValueError("bad input")))
        QCoreApplication.processEvents()

    assert model.nodeData("answer", model.StateRole) is NodeExecutionState.ERROR
    assert model.nodeData("answer", Qt.ItemDataRole.BackgroundRole) == QColor(200, 20, 20)
    assert model.nodeData("answer", NodeDataRole.TrailingRole)
    document.script_document.setPlainText(SOURCE + "\n")
    assert model.nodeData("answer", Qt.ItemDataRole.BackgroundRole) == QColor("yellow")
    assert model.nodeData("answer", NodeDataRole.TrailingRole) is None
    backend.evaluations[-1].set_result(evaluate(SOURCE))
    QCoreApplication.processEvents()
    if failure == "execution":
        backend.executions[-1].set_result(ExecutionResult({"answer": 42}))
        QCoreApplication.processEvents()
    assert model.nodeData("answer", model.StateRole) is NodeExecutionState.IDLE
    assert model.nodeData("answer", Qt.ItemDataRole.BackgroundRole) is None
    assert model.nodeData("answer", NodeDataRole.TrailingRole) is None


def test_real_document_load_evaluates_and_executes_once(qtbot: QtBot) -> None:
    document = PyFlowDocument.deserialize(json.dumps({
        "version": 4,
        "script": {"source": SOURCE},
        "graph": {"nodes": {"answer": {"operator": "answer"}}},
    }))
    try:
        document.subscribeNode("answer", lambda _: None)
        qtbot.waitUntil(lambda: document.graph_model.nodeData("answer", document.graph_model.OutputRole) == 42)
        node = document.graph_model.mapToSource("answer")
        assert node is not None
        assert document.graph_model.nodeData(node.name(), document.graph_model.StateRole) is NodeExecutionState.IDLE
        assert document.graph_model.nodeData("answer", Qt.ItemDataRole.BackgroundRole) is None
    finally:
        document.close()


@pytest.mark.parametrize("selected", [False, True])
@pytest.mark.parametrize("fails", [False, True])
def test_status_color_is_painted_even_when_selected(
    loading_document: tuple[PyFlowDocument, ControlledBackend],
    qtbot: QtBot, selected: bool, fails: bool,
) -> None:
    document, backend = loading_document
    model = document.graph_model
    if fails:
        backend.evaluations[-1].set_exception(ValueError("bad source"))
        QCoreApplication.processEvents()
    view = DirectionalGraphView5()
    qtbot.addWidget(view)
    view.setStyle(QStyleFactory.create("Fusion"))
    view.resize(500, 250)
    view.setModel(model)
    model.setNodePosition("answer", QPointF(150, 100))
    selection = GraphSelectionModel(model)
    view.setSelectionModel(selection)
    if selected:
        selection.selectNode("answer")

    color = QColor(200, 20, 20) if fails else QColor("yellow")
    if selected:
        color = color.lighter(115)
    rendered = QImage(view.size(), QImage.Format.Format_ARGB32_Premultiplied)
    rendered.fill(Qt.GlobalColor.transparent)
    painter = QPainter(rendered)
    try:
        view.render(painter, QPoint())
    finally:
        painter.end()
    # Native styles may shade the selected fill with a gradient.
    colored_pixels = 0
    for x in range(rendered.width()):
        for y in range(rendered.height()):
            pixel = rendered.pixelColor(x, y)
            if abs(pixel.hue() - color.hue()) <= 2 and pixel.saturation() > 150:
                colored_pixels += 1
    assert colored_pixels > 100
    option = view._nodeStyleOption("answer")
    if selected:
        assert option.palette.highlight().color() == color
    assert option.palette.placeholderText() == view.palette().placeholderText()
