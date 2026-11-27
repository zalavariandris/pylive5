"""Selection-model lifecycle checks with real inspector widgets."""

from collections.abc import Iterable
from typing import Any

import pytest
from pytestqt.qtbot import QtBot
from qtpy.QtCore import Qt
from qtpy.QtWidgets import QLineEdit

from qdageditor5.models.abstract_dag_model import (
    AbstractDAGModel,
    DirectionalLinkId,
    InletName,
    NodeName,
    OutletName,
)
from qdageditor5.models.graph_selection_model import GraphSelectionModel
from qdageditor5.views.node_inspector_view import NodeInspectorView


class InspectorModel(AbstractDAGModel):
    def __init__(self) -> None:
        super().__init__()
        self.inputs: dict[NodeName, dict[InletName, str]] = {
            "first": {"text": "First"},
            "second": {"text": "Second"},
        }
        self.connections: list[DirectionalLinkId] = []

    def nodes(self) -> Iterable[NodeName]:
        return tuple(self.inputs)

    def nodeData(
        self, node: NodeName, column: int, role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        return f"Details for {node}" if role == Qt.ItemDataRole.DisplayRole else None

    def inlets(self, node: NodeName) -> Iterable[InletName]:
        return tuple(self.inputs[node])

    def inletData(
        self, node: NodeName, inlet: InletName, role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return self.inputs[node][inlet]
        return None

    def setInletData(
        self, node: NodeName, inlet: InletName, value: Any, role: int,
    ) -> bool:
        if role != Qt.ItemDataRole.EditRole:
            return False
        self.inputs[node][inlet] = value
        self.inletDataChanged.emit(node, (inlet,), [role])
        return True

    def outlets(self, node: NodeName) -> Iterable[OutletName]:
        return ("out",)

    def outletData(self, node: NodeName, outlet: OutletName, role: int) -> Any:
        return None

    def inLinks(self, node: NodeName, inlet: InletName) -> Iterable[DirectionalLinkId]:
        return tuple(link for link in self.connections if link[2:] == (node, inlet))

    def outLinks(self, node: NodeName, outlet: OutletName) -> Iterable[DirectionalLinkId]:
        return tuple(link for link in self.connections if link[:2] == (node, outlet))

    def links(self) -> Iterable[DirectionalLinkId]:
        return tuple(self.connections)

    def remove_node(self, node: NodeName) -> None:
        self._beginRemoveNodes((node,))
        del self.inputs[node]
        self._endRemoveNodes()


@pytest.fixture
def inspector(qtbot: QtBot) -> NodeInspectorView:
    view = NodeInspectorView()
    qtbot.addWidget(view)
    return view


def text_editor(view: NodeInspectorView, inlet: InletName = "text") -> QLineEdit:
    editor = view._editors[inlet]
    assert isinstance(editor, QLineEdit)
    return editor


def test_set_model_creates_a_default_selection_model(inspector: NodeInspectorView) -> None:
    assert inspector.selectionModel() is None
    inspector.setCurrentNode(None)
    with pytest.raises(ValueError, match="Set a model"):
        inspector.setCurrentNode("first")

    model = InspectorModel()
    inspector.setModel(model)
    selection = inspector.selectionModel()
    assert selection is not None
    assert selection.model() is model
    assert selection.parent() is inspector
    assert selection.currentNode() is None

    inspector.setCurrentNode("first")
    assert selection.currentNode() == "first"
    assert text_editor(inspector).text() == "First"
    with pytest.raises(ValueError, match="does not exist"):
        inspector.setCurrentNode("missing")
    assert text_editor(inspector).text() == "First"


def test_same_model_preserves_shared_selection_and_editors(inspector: NodeInspectorView) -> None:
    model = InspectorModel()
    selection = GraphSelectionModel(model)
    selection.selectNode("first")
    inspector.setModel(model)
    inspector.setSelectionModel(selection)
    editor = text_editor(inspector)

    inspector.setModel(model)
    inspector.setSelectionModel(selection)
    assert inspector.selectionModel() is selection
    assert selection.currentNode() == "first"
    assert selection.selectedNodes() == ("first",)
    assert text_editor(inspector) is editor


def test_new_model_preserves_the_old_shared_selection(
    inspector: NodeInspectorView, qtbot: QtBot,
) -> None:
    old_model = InspectorModel()
    inspector.setModel(old_model)
    old_selection = inspector.selectionModel()
    assert old_selection is not None
    old_selection.selectNode("first")

    other = NodeInspectorView()
    qtbot.addWidget(other)
    other.setModel(old_model)
    other.setSelectionModel(old_selection)

    new_model = InspectorModel()
    new_model.inputs["first"]["text"] = "Replacement"
    inspector.setModel(new_model)
    selection = inspector.selectionModel()
    assert selection is not None and selection is not old_selection
    assert selection.model() is new_model
    assert selection.currentNode() is None
    assert inspector._inlets_form.rowCount() == 0
    assert inspector._title.text() == "- no selection -"
    assert old_selection.model() is old_model
    assert old_selection.currentNode() == "first"
    assert old_selection.selectedNodes() == ("first",)
    assert text_editor(other).text() == "First"

    old_selection.setCurrentNode("second")
    assert text_editor(other).text() == "Second"
    assert inspector._inlets_form.rowCount() == 0
    inspector.setCurrentNode("first")
    old_model.setInletData("first", "text", "Old model", Qt.ItemDataRole.EditRole)
    assert text_editor(inspector).text() == "Replacement"


def test_replacing_selection_adopts_its_current_node(inspector: NodeInspectorView) -> None:
    model = InspectorModel()
    inspector.setModel(model)
    old_selection = inspector.selectionModel()
    assert old_selection is not None
    old_selection.setCurrentNode("first")

    replacement = GraphSelectionModel(model)
    replacement.setCurrentNode("second")
    inspector.setSelectionModel(replacement)
    assert text_editor(inspector).text() == "Second"
    assert inspector._inlets_form.rowCount() == 1

    old_selection.setCurrentNode(None)
    assert text_editor(inspector).text() == "Second"
    inspector.setCurrentNode("first")
    assert replacement.currentNode() == "first"
    assert inspector._inlets_form.rowCount() == 1


def test_mismatched_selection_is_rejected_without_detaching(inspector: NodeInspectorView) -> None:
    model = InspectorModel()
    inspector.setModel(model)
    original = inspector.selectionModel()
    assert original is not None
    original.setCurrentNode("first")

    with pytest.raises(ValueError, match="inspector's model"):
        inspector.setSelectionModel(GraphSelectionModel(InspectorModel()))

    assert inspector.selectionModel() is original
    original.setCurrentNode("second")
    assert text_editor(inspector).text() == "Second"


def test_detaching_model_clears_the_form_and_old_connections(inspector: NodeInspectorView) -> None:
    model = InspectorModel()
    inspector.setModel(model)
    selection = inspector.selectionModel()
    assert selection is not None
    selection.selectNode("first")

    inspector.setModel(None)
    inspector.setModel(None)
    assert inspector.model() is None
    assert inspector.selectionModel() is None
    assert inspector._inlets_form.rowCount() == 0
    assert inspector._title.text() == "- no selection -"
    assert inspector._subtitle.text() == "- info -"
    assert selection.currentNode() == "first"

    selection.setCurrentNode("second")
    model.setInletData("second", "text", "Detached", Qt.ItemDataRole.EditRole)
    inspector.setCurrentNode(None)
    assert inspector._inlets_form.rowCount() == 0

    inspector.setModel(model)
    assert inspector.selectionModel() is not selection
    inspector.setCurrentNode("second")
    assert text_editor(inspector).text() == "Detached"


def test_shared_selection_updates_the_form_and_current_input(inspector: NodeInspectorView) -> None:
    model = InspectorModel()
    selection = GraphSelectionModel(model)
    inspector.setModel(model)
    inspector.setSelectionModel(selection)
    selection.setCurrentNode("first")
    selection.setCurrentNode("second")
    assert inspector._inlets_form.rowCount() == 1
    assert text_editor(inspector).text() == "Second"

    model.setInletData("first", "text", "Ignored", Qt.ItemDataRole.EditRole)
    model.setInletData("second", "text", "Refreshed", Qt.ItemDataRole.EditRole)
    assert text_editor(inspector).text() == "Refreshed"
    text_editor(inspector).setText("Edited")
    assert model.inputs["first"]["text"] == "Ignored"
    assert model.inputs["second"]["text"] == "Edited"

    link = ("first", "out", "second", "text")
    model.connections.append(link)
    model.linksAdded.emit((link,))
    assert not text_editor(inspector).isEnabled()
    model.connections.clear()
    model.linksRemoved.emit((link,))
    assert text_editor(inspector).isEnabled()

    selection.setCurrentNode(None)
    assert inspector._inlets_form.rowCount() == 0
    assert inspector._title.text() == "- no selection -"


@pytest.mark.parametrize("reset_model", [False, True])
def test_removal_or_reset_clears_current_node(
    inspector: NodeInspectorView, reset_model: bool,
) -> None:
    model = InspectorModel()
    inspector.setModel(model)
    inspector.setCurrentNode("first")
    if reset_model:
        model._beginResetModel()
        model.inputs.clear()
        model._endResetModel()
    else:
        model.remove_node("first")
    selection = inspector.selectionModel()
    assert selection is not None and selection.currentNode() is None
    assert inspector._current_node is None
    assert inspector._inlets_form.rowCount() == 0
    assert inspector._title.text() == "- no selection -"


def test_inlet_reset_rebuilds_the_selected_node(inspector: NodeInspectorView) -> None:
    model = InspectorModel()
    inspector.setModel(model)
    inspector.setCurrentNode("first")
    model._beginResetInlets("first")
    model.inputs["first"]["extra"] = "New inlet"
    model._endResetInlets()
    assert inspector._inlets_form.rowCount() == 2
    assert text_editor(inspector, "extra").text() == "New inlet"
