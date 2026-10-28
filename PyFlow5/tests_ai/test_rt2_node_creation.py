"""Regression coverage for creating and displaying nodes with the new runtime."""

from collections.abc import Iterator

import pytest
from pytestqt.qtbot import QtBot
from qtpy.QtCore import QPoint, QPointF, Qt
from qtpy.QtWidgets import QDialog

from myqtx.selection_dialog_view import SelectionDialog
from pyflow5.models.pyflow5_document import PyFlowDocument
from pyflow5.views.pyflow5_documentwindow import PyFlow5DocumentWindow


@pytest.fixture
def editor(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch,
) -> Iterator[PyFlow5DocumentWindow]:
    document = PyFlowDocument()
    document.script_document.setPlainText(
        "def example(value: int = 7) -> int:\n    return value\n"
    )
    window = PyFlow5DocumentWindow(document)
    monkeypatch.setattr(window, "confirmSaveChanges", lambda: True)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(window.isVisible)
    window._fit_timer.stop()
    try:
        yield window
    finally:
        window.dispose()


def test_double_click_and_operator_selection_create_visible_nodes(
    editor: PyFlow5DocumentWindow, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def select_first_operator(dialog: SelectionDialog) -> int:
        tree = dialog._operator_tree
        tree.setCurrentIndex(tree.model().index(0, 0))
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(SelectionDialog, "exec", select_first_operator)
    model = editor.document().graph_model
    view = editor._graph_view

    for click in (QPoint(80, 100), QPoint(80, 300)):
        previous = set(model.nodes())
        position = view.mapToScene(QPointF(click))
        qtbot.mouseDClick(view, Qt.MouseButton.LeftButton, pos=click)
        added = set(model.nodes()) - previous
        assert len(added) == 1
        node = added.pop()
        assert model.nodePosition(node) == position
        assert model.nodeData(node) == "example"
        assert list(model.inlets(node)) == ["value"]
        bounds = view._nodeSceneRect(view._nodeStyleOption(node), node)
        assert not bounds.isEmpty()
        assert view.rect().intersects(view.mapFromScene(bounds).toAlignedRect())
        assert not view.grab().isNull()

    assert len(list(model.nodes())) == 2


def test_created_node_survives_document_reload(editor: PyFlow5DocumentWindow) -> None:
    document = editor.document()
    model = document.graph_model
    operator = document._engine.registry.get_operator_by_name("example")
    model.addNode(operator, QPointF(123, 234))

    # Updating a created node must find its snapshot and notify the adapters.
    node = model.mapToSource("example")
    assert node is not None
    document._engine.graph._update_node(node, operator, (), {"value": 9})

    restored = PyFlowDocument.deserialize(document.serialize())
    try:
        assert list(restored.graph_model.nodes()) == ["example"]
        assert restored.graph_model.nodeData("example") == "example"
        assert restored.graph_model.nodePosition("example") == QPointF(123, 234)
        assert restored.graph_model.nodeData(
            "example", restored.graph_model.OutputRole,
        ) == 9
        assert restored.script_document.toPlainText() == document.script_document.toPlainText()
    finally:
        restored.close()
