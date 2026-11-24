"""Empty presentation preserves editor values; the delegate owns model writes."""

from typing import Any

import pytest
from pytestqt.qtbot import QtBot
from qtpy.QtCore import QPoint, Qt
from qtpy.QtGui import QAction, QContextMenuEvent
from qtpy.QtWidgets import (
    QApplication, QDoubleSpinBox, QLineEdit, QMenu, QSpinBox, QVBoxLayout, QWidget,
)

from graphcook.eager_observable_engine import EagerEngine, NodeId, OperatorHandle
from GraphCook.examples.qt_integration.eager_qdageditor import (
    EagerEditorWrapper, EagerGraphModel, NodeInspectorView,
)


@pytest.mark.parametrize(
    ("editor_type", "value", "replacement"),
    [(QLineEdit, "kept", "changed"), (QSpinBox, 42, 43),
     (QDoubleSpinBox, 1.5, 2.5)],
)
def test_empty_presentation_preserves_value_and_does_not_notify_edits(
    qtbot: QtBot, editor_type: type[QWidget], value: Any, replacement: Any,
) -> None:
    child = editor_type()
    wrapper = EagerEditorWrapper(child)
    qtbot.addWidget(wrapper)
    wrapper.setValue(value)
    values: list[Any] = []
    empty_states: list[bool] = []
    wrapper.valueChanged.connect(values.append)
    wrapper.emptyChanged.connect(empty_states.append)

    wrapper.setEmpty(True)
    wrapper.setEmpty(True)
    assert wrapper.getValue() == value
    assert wrapper.metaObject().userProperty().read(wrapper) == value
    assert not wrapper._empty_label.isHidden()
    assert values == []
    assert empty_states == [True]

    wrapper.setValue(replacement)
    assert wrapper.isEmpty()
    assert wrapper.getValue() == replacement
    assert values == [replacement]
    # A child edit also leaves the presentation decision to the delegate.
    child.metaObject().userProperty().write(child, value)
    assert wrapper.isEmpty()
    assert values == [replacement, value]

    wrapper.setEmpty(False)
    assert wrapper.getValue() == value
    assert wrapper._empty_label.isHidden()
    assert values == [replacement, value]
    assert empty_states == [True, False]


@pytest.mark.parametrize("editor_type", [QLineEdit, QSpinBox])
def test_focusing_an_empty_editor_reveals_retained_value(
    qtbot: QtBot, editor_type: type[QWidget],
) -> None:
    host = QWidget()
    qtbot.addWidget(host)
    layout = QVBoxLayout(host)
    wrapper = EagerEditorWrapper(editor_type())
    other = QLineEdit()
    layout.addWidget(wrapper)
    layout.addWidget(other)
    value = "kept" if editor_type is QLineEdit else 42
    wrapper.setValue(value)
    wrapper.setEmpty(True)
    host.show()
    host.activateWindow()
    other.setFocus()
    qtbot.waitUntil(other.hasFocus)
    assert wrapper._empty_label.isVisible()

    qtbot.mouseClick(wrapper._wrapped, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(wrapper._empty_label.isHidden)
    assert wrapper.isEmpty()
    assert wrapper.getValue() == value

    other.setFocus()
    qtbot.waitUntil(wrapper._empty_label.isVisible)
    assert wrapper.getValue() == value


def test_unset_menu_changes_presentation_without_changing_value(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch,
) -> None:
    wrapper = EagerEditorWrapper(QLineEdit())
    qtbot.addWidget(wrapper)
    wrapper.setValue("kept")
    empty_states: list[bool] = []
    values: list[Any] = []
    wrapper.emptyChanged.connect(empty_states.append)
    wrapper.valueChanged.connect(values.append)

    def choose_unset(menu: QMenu, position: QPoint) -> QAction:
        action = next(action for action in menu.actions() if action.text() == "Unset")
        assert action.isEnabled()
        action.trigger()
        return action

    monkeypatch.setattr(QMenu, "exec", choose_unset)
    event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(), QPoint())
    QApplication.sendEvent(wrapper._wrapped, event)
    assert empty_states == [True]
    assert values == []
    assert wrapper.getValue() == "kept"
    assert wrapper.isEmpty()


def test_delegate_unsets_preserves_values_and_commits_edits(qtbot: QtBot) -> None:
    engine = EagerEngine('def source(): return "linked"\ndef target(text: str = "default"): return text')
    try:
        # Fixed IDs keep this test independent of the optional name generator.
        source = NodeId("source")
        target = NodeId("target")
        engine._graph_config.add_node(source, __operator__=OperatorHandle("source"))
        engine._graph_config.add_node(target, __operator__=OperatorHandle("target"), text="kept")
        model = EagerGraphModel(engine)
        view = NodeInspectorView()
        qtbot.addWidget(view)
        view.setModel(model)
        view.setCurrentNode(target)
        wrapper = view._editors["text"]
        assert isinstance(wrapper, EagerEditorWrapper)
        edits: list[Any] = []
        wrapper.valueChanged.connect(edits.append)

        # The delegate observes this presentation change and unsets the model.
        wrapper.setEmpty(True)
        assert "text" not in engine.attributes(target)
        assert wrapper.isEmpty()
        assert wrapper.getValue() == "kept"
        assert edits == []
        assert engine.evaluate_node(target)[target] == "default"

        wrapper._wrapped.setText("edited")
        assert engine.attributes(target)["text"] == "edited"
        assert not wrapper.isEmpty()
        assert edits == ["edited"]

        # An actual empty string remains a concrete model value.
        wrapper._wrapped.setText("")
        assert engine.attributes(target)["text"] == ""
        assert not wrapper.isEmpty()
        engine.update(target, text="external")
        assert wrapper.getValue() == "external"
        assert edits == ["edited", ""]

        engine.add_link(source, target, "text")
        assert wrapper.isLinked()
        engine.unset(target, "text")
        assert wrapper.isEmpty()
        assert wrapper.getValue() == "external"
        engine.remove_link(source, target, "text")
        assert not wrapper.isLinked()
        assert wrapper.isEmpty()
        assert wrapper.getValue() == "external"
        view.setModel(None)
    finally:
        engine.close()
