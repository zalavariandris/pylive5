"""Exercise the actual inspector class without unrelated graph-layout imports."""

from __future__ import annotations

import ast
import builtins
import inspect
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from pytestqt.qtbot import QtBot
from qtpy.QtCore import QSignalBlocker
from qtpy.QtWidgets import QFormLayout, QFrame, QLabel, QLineEdit, QSpinBox, QWidget

from graphcook.eager_engine import EagerEngine, EagerEngineChange


def inspector_type() -> type[QFrame]:
    """Compile the production class, avoiding the optional grandalf dependency."""
    path = Path(__file__).parents[1] / "examples/qt_integration/eager_qdageditor.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    definition = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "InspectorView"
    )
    namespace: dict[str, Any] = {
        "builtins": builtins,
        "inspect": inspect,
        "QSignalBlocker": QSignalBlocker,
        "QFormLayout": QFormLayout,
        "QFrame": QFrame,
        "QLabel": QLabel,
        "QLineEdit": QLineEdit,
        "QSpinBox": QSpinBox,
        "QWidget": QWidget,
    }
    exec(compile(ast.Module(body=[definition], type_ignores=[]), str(path), "exec"), namespace)
    return namespace["InspectorView"]


def test_inspector_refreshes_nested_add_update_remove_without_feedback(qtbot: QtBot) -> None:
    engine = EagerEngine('def greet(greeting: str = "Hello"): return greeting')
    try:
        node = engine.create_node("greet")
        inspector = inspector_type()(engine)
        qtbot.addWidget(inspector)
        inspector.setCurrentNode(node)
        editor = inspector._editors["greeting"]
        assert isinstance(editor, QLineEdit)
        assert editor.placeholderText() == "Hello"
        events: list[EagerEngineChange] = []
        engine.listen(events.append)

        engine.set(node, greeting="Hey")
        assert editor.text() == "Hey"
        assert sum("nodes" in event for event in events) == 1
        events.clear()

        engine.set(node, greeting="Hi")
        assert editor.text() == "Hi"
        assert inspector._editors["greeting"] is editor
        assert sum("nodes" in event for event in events) == 1
        events.clear()

        engine.unset(node, "greeting")
        assert editor.text() == ""
        assert editor.placeholderText() == "Hello"
        assert "greeting" not in engine.attributes(node)
        assert sum("nodes" in event for event in events) == 1

        editor.setText("User edit")
        assert engine.attributes(node)["greeting"] == "User edit"
        engine.delete(node)
        assert inspector._current_node is None
        assert inspector._editors == {}
    finally:
        engine.close()


def test_graph_model_does_not_refresh_data_for_a_deleted_node() -> None:
    path = Path(__file__).parents[1] / "examples/qt_integration/eager_qdageditor.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    model = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "EagerGraphModel")
    handler = next(node for node in model.body if isinstance(node, ast.FunctionDef) and node.name == "_handle_engine_change")
    namespace: dict[str, Any] = {}
    exec(compile(ast.Module(body=[handler], type_ignores=[]), str(path), "exec"), namespace)
    engine = EagerEngine('def source(): return 1')
    refreshed: list[object] = []
    probe = SimpleNamespace(
        _engine=engine,
        mapFromSource=lambda node: node,
        nodesDataChanged=SimpleNamespace(emit=lambda nodes, roles: refreshed.extend(nodes)),
    )
    try:
        node = engine.create_node("source")
        engine.listen(lambda change: namespace["_handle_engine_change"](probe, change))
        engine.delete(node)
        assert refreshed == []
    finally:
        engine.close()
