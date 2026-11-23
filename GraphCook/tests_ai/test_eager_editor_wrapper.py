"""Exercise the wrapper's Qt property, context menu, and engine integration."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest
from pytestqt.qtbot import QtBot
from qtpy.QtCore import Property, QPoint, QSignalBlocker, Qt
from qtpy.QtGui import QAction, QContextMenuEvent
from qtpy.QtWidgets import QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QLabel, QLineEdit, QMenu, QSpinBox, QWidget

from graphcook.eager_observable_engine import EagerEngine
from .test_graph_inspector_view import inspector_classes, make_engine


@pytest.mark.parametrize(
    ("editor_type", "value", "edited_value"),
    [(QLineEdit, "Hello", "Edited"), (QSpinBox, 42, 43),
     (QDoubleSpinBox, 1.5, 2.5), (QCheckBox, True, False)],
)
def test_wrapper_exposes_logical_value_through_qt_property(
    qtbot: QtBot, inspector_classes: SimpleNamespace,
    editor_type: type[QWidget], value: Any, edited_value: Any,
) -> None:
    child = editor_type()
    wrapper = inspector_classes.EagerEditorWrapper(child)
    qtbot.addWidget(wrapper)
    notifications: list[Any] = []
    wrapper.valueChanged.connect(notifications.append)
    prop = wrapper.metaObject().userProperty()

    assert prop.name() == "value"
    assert prop.write(wrapper, value)
    assert prop.read(wrapper) == value
    assert notifications == [value]
    assert child.metaObject().userProperty().write(child, edited_value)
    assert prop.read(wrapper) == edited_value
    assert notifications == [value, edited_value]

    with QSignalBlocker(wrapper):
        assert prop.write(wrapper, inspect.Parameter.empty)
    assert prop.read(wrapper) is inspect.Parameter.empty
    assert not wrapper._unset_label.isHidden()
    assert notifications == [value, edited_value]

    wrapper.showLinked(True)
    assert wrapper._stack.currentWidget() is wrapper._linked_page
    assert wrapper.isEnabled()
    # The stored value is already empty, but Disconnect must still notify.
    wrapper.setValue(inspect.Parameter.empty)
    assert notifications[-1] is inspect.Parameter.empty
    assert len(notifications) == 3


def test_unsetting_combo_box_does_not_delete_its_choices(
    qtbot: QtBot, inspector_classes: SimpleNamespace,
) -> None:
    child = QComboBox()
    child.addItems(["First", "Second"])
    wrapper = inspector_classes.EagerEditorWrapper(child)
    qtbot.addWidget(wrapper)
    wrapper.setValue("Second")
    wrapper.setValue(inspect.Parameter.empty)
    assert child.count() == 2
    assert wrapper.getValue() is inspect.Parameter.empty
    assert not wrapper._unset_label.isHidden()


@pytest.fixture
def open_menu(
    monkeypatch: pytest.MonkeyPatch, inspector_classes: SimpleNamespace,
) -> Callable[[QWidget, str, bool], None]:
    """Send an actual context event; choose the action without a blocking popup."""
    def open_on(child: QWidget, text: str, enabled: bool = True) -> None:
        menus: list[QMenu] = []

        class TestMenu(QMenu):
            def exec(self, position: QPoint) -> QAction | None:
                menus.append(self)
                action, = self.actions()
                assert action.text() == text
                assert action.isEnabled() is enabled
                return action if enabled else None

        monkeypatch.setitem(
            inspector_classes.EagerEditorWrapper.contextMenuEvent.__globals__, "QMenu", TestMenu,
        )
        event = QContextMenuEvent(
            QContextMenuEvent.Reason.Mouse, QPoint(1, 1), child.mapToGlobal(QPoint(1, 1)),
        )
        QApplication.sendEvent(child, event)
        assert len(menus) == 1

    return open_on


def test_disconnect_restores_literal_then_unset_hides_default(
    qtbot: QtBot, inspector_classes: SimpleNamespace,
    make_engine: Callable[[str], EagerEngine], open_menu: Callable[..., None],
) -> None:
    engine = make_engine('def source(): return 7\ndef target(value: int = 99): return value')
    source = engine.create_node("source")
    target = engine.create_node("target", value=42)
    model = inspector_classes.EagerGraphModel(engine)
    view = inspector_classes.GraphInspectorView()
    qtbot.addWidget(view)
    view.setModel(model)
    view.setCurrentNode(target)
    wrapper = view._editors["value"]
    engine.add_link(source, target, "value")
    assert wrapper._stack.currentWidget() is wrapper._linked_page
    events: list[dict[str, Any]] = []
    engine.listen(events.append)

    open_menu(wrapper._linked_chip, "Disconnect")
    assert list(engine.in_links(target)) == []
    assert engine.attributes(target)["value"] == 42
    assert wrapper.getValue() == 42
    assert wrapper._widget.value() == 42
    assert wrapper._stack.currentWidget() is wrapper._editor_page
    assert view._editors["value"] is wrapper
    assert sum("links" in event for event in events) == 1

    events.clear()
    # Right-clicking the spin box's internal editor must reach the wrapper.
    open_menu(wrapper._widget.findChild(QLineEdit), "Unset")
    assert "value" not in engine.attributes(target)
    assert wrapper.getValue() is inspect.Parameter.empty
    assert wrapper._widget.text() == ""
    assert sum("nodes" in event for event in events) == 1
    assert engine.evaluate_node(target)[target] == 99
    assert wrapper._widget.text() == ""
    open_menu(wrapper._widget, "Unset", False)


def test_disconnect_without_literal_leaves_input_unset(
    qtbot: QtBot, inspector_classes: SimpleNamespace,
    make_engine: Callable[[str], EagerEngine], open_menu: Callable[..., None],
) -> None:
    engine = make_engine('def source(): return 7\ndef target(value: int = 99): return value')
    source = engine.create_node("source")
    target = engine.create_node("target")
    engine.add_link(source, target, "value")
    model = inspector_classes.EagerGraphModel(engine)
    view = inspector_classes.GraphInspectorView()
    qtbot.addWidget(view)
    view.setModel(model)
    view.setCurrentNode(target)
    wrapper = view._editors["value"]
    assert wrapper.getValue() is inspect.Parameter.empty

    open_menu(wrapper._linked_chip, "Disconnect")
    assert list(engine.in_links(target)) == []
    assert wrapper.getValue() is inspect.Parameter.empty
    assert wrapper._widget.text() == ""
    assert engine.evaluate_node(target)[target] == 99


def test_link_only_inlet_appears_and_disappears_with_connection(
    qtbot: QtBot, inspector_classes: SimpleNamespace,
    make_engine: Callable[[str], EagerEngine], open_menu: Callable[..., None],
) -> None:
    engine = make_engine('def source(): return 7\ndef target(): pass')
    source = engine.create_node("source")
    target = engine.create_node("target")
    model = inspector_classes.EagerGraphModel(engine)
    view = inspector_classes.GraphInspectorView()
    qtbot.addWidget(view)
    view.setModel(model)
    view.setCurrentNode(target)
    assert view._editors == {}
    engine.add_link(source, target, "extra")
    wrapper = view._editors["extra"]
    assert wrapper._stack.currentWidget() is wrapper._linked_page
    open_menu(wrapper._linked_chip, "Disconnect")
    assert view._editors == {}
    assert list(engine.in_links(target)) == []


def test_canceling_menu_does_not_change_value(
    qtbot: QtBot, inspector_classes: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
) -> None:
    wrapper = inspector_classes.EagerEditorWrapper(QLineEdit())
    qtbot.addWidget(wrapper)
    wrapper.setValue("Keep")
    changes: list[Any] = []
    wrapper.valueChanged.connect(changes.append)
    class CanceledMenu(QMenu):
        def exec(self, position: QPoint) -> None:
            return None

    monkeypatch.setitem(
        inspector_classes.EagerEditorWrapper.contextMenuEvent.__globals__, "QMenu", CanceledMenu,
    )
    QApplication.sendEvent(wrapper, QContextMenuEvent(
        QContextMenuEvent.Reason.Keyboard, QPoint(), QPoint(),
    ))
    assert wrapper.getValue() == "Keep"
    assert changes == []


@pytest.mark.parametrize("child_type", [QWidget, QLabel])
def test_widget_without_user_property_supports_value_and_unset(
    qtbot: QtBot, inspector_classes: SimpleNamespace, open_menu: Callable[..., None],
    child_type: type[QWidget],
) -> None:
    child = child_type()
    assert not child.metaObject().userProperty().isValid()
    wrapper = inspector_classes.EagerEditorWrapper(child)
    qtbot.addWidget(wrapper)
    values: list[Any] = []
    wrapper.valueChanged.connect(values.append)
    value = {"items": [1, 2]}
    wrapper.setValue(value)
    assert wrapper.metaObject().userProperty().read(wrapper) == value
    if isinstance(child, QLabel):
        assert child.text() == str(value)
    open_menu(child, "Unset")
    assert wrapper.getValue() is inspect.Parameter.empty
    assert values == [value, inspect.Parameter.empty]
    if isinstance(child, QLabel):
        assert child.text() == ""
    wrapper.showLinked(True)
    open_menu(wrapper._linked_chip, "Disconnect")
    assert values[-1] is inspect.Parameter.empty
    assert len(values) == 3


def test_user_property_without_notification_supports_wrapper_writes(
    qtbot: QtBot, inspector_classes: SimpleNamespace,
) -> None:
    class QuietEditor(QWidget):
        def __init__(self) -> None:
            super().__init__()
            self._value = "Initial"

        def getValue(self) -> str:
            return self._value

        def setValue(self, value: str) -> None:
            self._value = value

        value = Property(str, getValue, setValue, user=True)

    child = QuietEditor()
    assert not child.metaObject().userProperty().hasNotifySignal()
    wrapper = inspector_classes.EagerEditorWrapper(child)
    qtbot.addWidget(wrapper)
    values: list[Any] = []
    wrapper.valueChanged.connect(values.append)
    wrapper.setValue("Updated")
    assert child.getValue() == wrapper.getValue() == "Updated"
    assert values == ["Updated"]
    wrapper.setValue(inspect.Parameter.empty)
    assert wrapper.getValue() is inspect.Parameter.empty
    assert child.getValue() == "Initial"
    assert values[-1] is inspect.Parameter.empty
