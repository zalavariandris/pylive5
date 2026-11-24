"""Regression coverage for the model-backed inspector with real Qt widgets."""

from __future__ import annotations

import ast
import inspect
from collections.abc import Callable, Iterator
from enum import IntEnum
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pytestqt.qtbot import QtBot
from qtpy.QtCore import Property, QObject, QSignalBlocker, Signal, Qt
from qtpy.QtGui import QContextMenuEvent
from qtpy.QtWidgets import QAbstractSpinBox, QDoubleSpinBox, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu, QSpinBox, QStackedLayout, QVBoxLayout, QWidget

from graphcook.eager_observable_engine import EagerEngine
from qdageditor5.models.abstract_dag_model import AbstractDAGModel


@pytest.fixture(scope="module")
def inspector_classes() -> SimpleNamespace:
    """Load the production classes without the example's unrelated layout imports."""
    path = Path(__file__).parents[1] / "examples/qt_integration/eager_qdageditor.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = {
        "EagerGraphModel", "InspectorRoles", "GraphInspectorView",
        "GraphInspectorDelegate", "EagerEditorWrapper",
    }
    definitions = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name in names]
    namespace = dict(globals())
    exec(compile(ast.Module(body=definitions, type_ignores=[]), str(path), "exec"), namespace)
    return SimpleNamespace(**{name: namespace[name] for name in names})


@pytest.fixture
def make_engine() -> Iterator[Callable[[str], EagerEngine]]:
    engines: list[EagerEngine] = []

    def create(script: str) -> EagerEngine:
        engine = EagerEngine(script)
        engines.append(engine)
        return engine

    yield create
    for engine in engines:
        engine.close()


def test_external_values_refresh_without_feedback(
    qtbot: QtBot, inspector_classes: SimpleNamespace, make_engine: Callable[[str], EagerEngine],
) -> None:
    engine = make_engine('def source(text: str, count: int, fraction: float, other): pass')
    node = engine.create_node("source", text="Initial", count=3, fraction=1.5, other=None)
    model = inspector_classes.EagerGraphModel(engine)
    view = inspector_classes.GraphInspectorView()
    qtbot.addWidget(view)
    view.setModel(model)
    view.setCurrentNode(node)
    editors = dict(view._editors)
    assert editors["text"]._widget.text() == "Initial"
    assert editors["count"]._widget.value() == 3
    assert editors["fraction"]._widget.value() == 1.5
    assert editors["other"]._widget.text() == "None"
    changes: list[dict[str, Any]] = []
    engine.listen(changes.append)

    engine.update(node, text="Updated", count=4, fraction=2.5, other=False)
    assert editors["text"]._widget.text() == "Updated"
    assert editors["count"]._widget.value() == 4
    assert editors["fraction"]._widget.value() == 2.5
    assert editors["other"]._widget.text() == "False"
    assert sum("nodes" in change for change in changes) == 1
    assert view._editors == editors

    for inlet in editors:
        engine.unset(node, inlet)
        assert editors[inlet]._widget.text() == ""
        assert editors[inlet].getValue() is inspect.Parameter.empty
        assert inlet not in engine.attributes(node)
    assert view._editors == editors
    assert sum("nodes" in change for change in changes) == 5


def test_selection_changes_keep_model_notifications_and_target_current_node(
    qtbot: QtBot, inspector_classes: SimpleNamespace, make_engine: Callable[[str], EagerEngine],
) -> None:
    engine = make_engine('def source(text: str): pass')
    first = engine.create_node("source", text="First")
    second = engine.create_node("source", text="Second")
    model = inspector_classes.EagerGraphModel(engine)
    view = inspector_classes.GraphInspectorView()
    qtbot.addWidget(view)
    view.setModel(model)
    view.setCurrentNode(first)
    view.setCurrentNode(second)
    engine.update(first, text="Ignored")
    assert view._editors["text"]._widget.text() == "Second"
    engine.update(second, text="Refreshed")
    assert view._editors["text"]._widget.text() == "Refreshed"

    notifications: list[tuple[Any, ...]] = []
    model.inletDataChanged.connect(lambda *args: notifications.append(args))
    view._editors["text"]._widget.setText("Edited")
    assert engine.attributes(second)["text"] == "Edited"
    assert engine.attributes(first)["text"] == "Ignored"
    assert len(notifications) == 1
    assert notifications[0] == (
        second, ("text",), [Qt.ItemDataRole.EditRole, Qt.ItemDataRole.DisplayRole],
    )

    view.setCurrentNode(None)
    view.setCurrentNode(first)
    engine.update(first, text="Still listening")
    assert view._editors["text"]._widget.text() == "Still listening"


def test_deleting_current_node_clears_form(
    qtbot: QtBot, inspector_classes: SimpleNamespace, make_engine: Callable[[str], EagerEngine],
) -> None:
    engine = make_engine('def source(text: str): pass')
    first = engine.create_node("source", text="First")
    second = engine.create_node("source", text="Second")
    model = inspector_classes.EagerGraphModel(engine)
    view = inspector_classes.GraphInspectorView()
    qtbot.addWidget(view)
    view.setModel(model)
    view.setCurrentNode(second)
    engine.delete(first)
    assert view._current_node == second
    engine.delete(second)
    assert view._current_node is None
    assert view._editors == {}
    assert view._form.rowCount() == 0


def test_extra_inputs_appear_and_disappear_on_external_changes(
    qtbot: QtBot, inspector_classes: SimpleNamespace, make_engine: Callable[[str], EagerEngine],
) -> None:
    engine = make_engine('def source(text: str): pass')
    node = engine.create_node("source", text="Initial", extra=7)
    model = inspector_classes.EagerGraphModel(engine)
    view = inspector_classes.GraphInspectorView()
    qtbot.addWidget(view)
    view.setModel(model)
    view.setCurrentNode(node)
    assert list(view._editors) == ["text", "extra"]
    assert view._editors["extra"]._widget.value() == 7
    engine.update(node, another="New input")
    assert list(view._editors) == ["text", "extra", "another"]
    assert view._editors["another"]._widget.text() == "New input"
    engine.unset(node, "extra")
    assert list(view._editors) == ["text", "another"]
    engine.update(node, another="Updated")
    assert view._editors["another"]._widget.text() == "Updated"


def test_inlets_include_unique_declared_stored_and_linked_names_without_signature(
    qtbot: QtBot, inspector_classes: SimpleNamespace, make_engine: Callable[[str], EagerEngine],
) -> None:
    engine = make_engine('def source(text: str): pass')
    source = engine.create_node("source")
    target = engine.create_node("source", text="Initial", extra=8)
    engine.add_link(source, target, "extra")
    engine.add_link(source, target, "linked")
    model = inspector_classes.EagerGraphModel(engine)
    assert list(model.inlets(target)) == ["text", "extra", "linked"]
    engine.set_script("")
    assert list(model.inlets(target)) == ["text", "extra", "linked"]
    view = inspector_classes.GraphInspectorView()
    qtbot.addWidget(view)
    view.setModel(model)
    view.setCurrentNode(target)
    assert view._editors["text"]._widget.text() == "Initial"
    for inlet in ("extra", "linked"):
        editor = view._editors[inlet]
        assert editor._stack.currentWidget() is editor._linked_page
        assert editor._linked_chip.text() == "Linked"


def test_replacing_or_detaching_model_clears_old_connections(
    qtbot: QtBot, inspector_classes: SimpleNamespace, make_engine: Callable[[str], EagerEngine],
) -> None:
    first_engine = make_engine('def source(text: str): pass')
    second_engine = make_engine('def source(text: str): pass')
    first = first_engine.create_node("source", text="First")
    second = second_engine.create_node("source", text="Second")
    first_model = inspector_classes.EagerGraphModel(first_engine)
    second_model = inspector_classes.EagerGraphModel(second_engine)
    view = inspector_classes.GraphInspectorView()
    qtbot.addWidget(view)
    view.setModel(first_model)
    view.setCurrentNode(first)
    view.setModel(second_model)
    assert view._current_node is None
    assert view._form.rowCount() == 0
    view.setCurrentNode(second)
    first_engine.delete(first)
    assert view._current_node == second
    second_engine.update(second, text="Updated")
    assert view._editors["text"]._widget.text() == "Updated"
    view.setModel(None)
    view.setModel(None)
    second_engine.update(second, text="Detached")
    assert view._current_node is None
    assert view._form.rowCount() == 0
