"""Handle-based nodes retain live signature metadata in the async editor."""

from inspect import Parameter
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from pytestqt.qtbot import QtBot
from qtpy.QtCore import QStringListModel, Qt
from qtpy.QtGui import QTextDocument
from qtpy.QtWidgets import QDoubleSpinBox, QLineEdit, QSpinBox

from GraphCook.examples.qt_integration.async_eager_qdageditor import (
    AsyncEagerGraphModel,
    Window,
)
from graphcook.core.cache import MemoryCache
from graphcook.eager_observable_engine import (
    OPERATOR_ATTRIBUTE,
    NodeId,
    OperatorHandle,
    OperatorSignature,
    _execute_graph,
    _execute_provider,
)
from graphcook.observable_graph import ObservableGraph
from qdageditor5.core.inspector_roles import InspectorRoles
from qdageditor5.views.node_inspector_view import NodeInspectorView


def signatures(script: str) -> dict[OperatorHandle, OperatorSignature]:
    return {
        handle: OperatorSignature.from_func(function, revision=0)
        for handle, function in _execute_provider(script).items()
    }


def test_node_stores_handle_and_exposes_signature_metadata(qtbot: QtBot) -> None:
    registry = signatures('def source(count: int, title="Hello", optional: str = None): pass')
    graph = ObservableGraph[NodeId]()
    model = AsyncEagerGraphModel(graph, registry.get)
    handle = OperatorHandle("source")
    node = model.addNode(handle)

    assert graph.attributes(node) == {OPERATOR_ATTRIBUTE: handle}
    assert model.operatorSignature(node) is registry[handle]
    assert list(model.inlets(node)) == ["count", "title", "optional"]
    assert model.inletData(node, "count", InspectorRoles.DataTypeRole) is int
    assert model.inletData(node, "count", InspectorRoles.DefaultValueRole) is Parameter.empty
    assert model.inletData(node, "title", InspectorRoles.DefaultValueRole) == "Hello"
    assert model.inletData(node, "optional", Qt.ItemDataRole.EditRole) is None

    view = NodeInspectorView()
    qtbot.addWidget(view)
    view.setModel(model)
    view.setCurrentNode(node)
    assert isinstance(view._editors["count"], QSpinBox)
    assert isinstance(view._editors["title"], QLineEdit)
    assert isinstance(view._editors["optional"], QLineEdit)
    assert view._editors["title"].text() == "Hello"
    assert graph.attributes(node) == {OPERATOR_ATTRIBUTE: handle}

    view._editors["count"].setValue(7)
    assert graph.attributes(node)["count"] == 7
    assert graph.attributes(node)[OPERATOR_ATTRIBUTE] is handle


@pytest.mark.asyncio
async def test_script_submission_refreshes_existing_inspector(qtbot: QtBot) -> None:
    old_signatures = signatures('def source(value: str = "old", removed: int = 1): pass')
    script = 'def source(value: int = 42, added: float = 1.5): pass'
    new_signatures = signatures(script)
    graph = ObservableGraph[NodeId]()
    document = QTextDocument(script)
    window = SimpleNamespace(
        _config_graph=graph,
        _operator_signatures=old_signatures,
        script_editor=SimpleNamespace(document=lambda: document),
        worker=SimpleNamespace(submit=AsyncMock(return_value=new_signatures)),
        operator_list_model=QStringListModel(),
    )
    model = AsyncEagerGraphModel(graph, lambda handle: Window.operator_signature(window, handle))
    window.model = model
    handle = OperatorHandle("source")
    node = model.addNode(handle)
    view = NodeInspectorView()
    qtbot.addWidget(view)
    view.setModel(model)
    view.setCurrentNode(node)
    assert isinstance(view._editors["value"], QLineEdit)

    changes: list[Any] = []
    graph.listen(changes.append)
    await Window.submit_execute_script.__wrapped__(window)

    assert model.operatorSignature(node) is new_signatures[handle]
    assert list(view._editors) == ["value", "added"]
    assert isinstance(view._editors["value"], QSpinBox)
    assert view._editors["value"].value() == 42
    assert isinstance(view._editors["added"], QDoubleSpinBox)
    assert view._editors["added"].value() == 1.5
    assert window.operator_list_model.stringList() == ["source"]
    assert graph.attributes(node) == {OPERATOR_ATTRIBUTE: handle}
    assert changes == []


def test_missing_operator_preserves_inputs_links_and_recovers(qtbot: QtBot) -> None:
    registry = signatures('def source(value: str): pass')
    original = dict(registry)
    graph = ObservableGraph[NodeId]()
    model = AsyncEagerGraphModel(graph, registry.get)
    handle = OperatorHandle("source")
    node = model.addNode(handle)
    upstream = model.addNode(OperatorHandle("upstream"))
    graph.set(node, "extra", 7)
    graph.add_link(upstream, node, "linked")
    view = NodeInspectorView()
    qtbot.addWidget(view)
    view.setModel(model)
    view.setCurrentNode(node)

    registry.clear()
    model.refreshOperatorSignatures({handle})
    assert model.operatorSignature(node) is None
    assert list(view._editors) == ["extra", "linked"]
    assert isinstance(view._editors["extra"], QSpinBox)
    assert not view._editors["linked"].isEnabled()
    assert graph.attributes(node)[OPERATOR_ATTRIBUTE] is handle

    registry.update(original)
    model.refreshOperatorSignatures({handle})
    assert list(view._editors) == ["value", "extra", "linked"]
    assert isinstance(view._editors["value"], QLineEdit)
    assert graph.attributes(node)["extra"] == 7


def test_refresh_keeps_unaffected_inspector_editor(qtbot: QtBot) -> None:
    registry = signatures('def first(value: str): pass\ndef second(count: int): pass')
    graph = ObservableGraph[NodeId]()
    model = AsyncEagerGraphModel(graph, registry.get)
    node = model.addNode(OperatorHandle("first"))
    model.addNode(OperatorHandle("second"))
    view = NodeInspectorView()
    qtbot.addWidget(view)
    view.setModel(model)
    view.setCurrentNode(node)
    editor = view._editors["value"]

    model.refreshOperatorSignatures({OperatorHandle("second")})
    assert view._editors["value"] is editor


@pytest.mark.asyncio
async def test_execution_snapshot_uses_stored_handles(qtbot: QtBot) -> None:
    script = 'def source(value: int = 5): return value * 2'
    registry = signatures(script)
    graph = ObservableGraph[NodeId]()
    model = AsyncEagerGraphModel(graph, registry.get)
    handle = OperatorHandle("source")
    node = model.addNode(handle)
    graph.set(node, "value", 9)
    submit = AsyncMock(return_value={})
    window = SimpleNamespace(
        model=model,
        selection=SimpleNamespace(currentNode=lambda: node),
        worker=SimpleNamespace(submit=submit),
    )

    await Window.submit_execute_graph.__wrapped__(window)

    message, snapshot = submit.call_args.args
    assert message == "execute_graph"
    assert snapshot.attributes(node)[OPERATOR_ATTRIBUTE] is handle
    result = _execute_graph(
        snapshot,
        _execute_provider(script),
        cache=MemoryCache(),
        callback=lambda node_id, status: None,
    )
    assert result[node] == 18
