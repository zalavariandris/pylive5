"""Inspector editors contain explicit node inputs, never operator defaults."""

from collections.abc import Callable, Iterator
from typing import cast

import pytest
from pytestqt.qtbot import QtBot
from qtpy.QtWidgets import QLabel, QLineEdit, QSpinBox

from graphcook.eager_engine import EagerEngine, EagerEngineChange, SucceededStatus
from GraphCook.examples.eager_qdageditor import InspectorView, OutputViewer


@pytest.fixture
def make_engine() -> Iterator[Callable[[str], EagerEngine]]:
    engines: list[EagerEngine] = []

    def make(script: str) -> EagerEngine:
        engine = EagerEngine(script)
        engines.append(engine)
        return engine

    yield make
    for engine in engines:
        engine.close()


def test_defaults_are_not_assigned_to_editor_properties(
    qtbot: QtBot, make_engine: Callable[[str], EagerEngine],
) -> None:
    engine = make_engine('def greet(name: str = "Hello", count: int = -200): return name * count')
    node = engine.node('greet')
    events: list[EagerEngineChange] = []
    engine.listen(events.append)
    inspector = InspectorView(engine)
    qtbot.addWidget(inspector)
    inspector.setCurrentNode(node)
    assert isinstance(inspector._editors['name'], QLineEdit)
    assert isinstance(inspector._editors['count'], QSpinBox)
    name = cast(QLineEdit, inspector._editors['name'])
    count = cast(QSpinBox, inspector._editors['count'])
    assert name.text() == ''
    assert count.text() == ''
    assert name.metaObject().userProperty().read(name) != 'Hello'
    assert count.metaObject().userProperty().read(count) != -200
    assert name.toolTip() == count.toolTip() == ''
    assert events == []
    assert set(engine.attributes(node)) == {'__operator__'}


def test_edits_update_attributes_evaluate_effect_and_preserve_editor(
    qtbot: QtBot, make_engine: Callable[[str], EagerEngine],
) -> None:
    engine = make_engine('def greet(name: str = "Hello", count: int = 2): return name * count')
    node = engine.node('greet', name='Custom', count=3)
    inspector = InspectorView(engine)
    viewer = OutputViewer(engine)
    qtbot.addWidget(inspector)
    qtbot.addWidget(viewer)
    inspector.setCurrentNode(node)
    viewer.setCurrentNode(node)
    name = cast(QLineEdit, inspector._editors['name'])
    count = cast(QSpinBox, inspector._editors['count'])
    assert name.text() == 'Custom'
    assert count.value() == 3
    events: list[EagerEngineChange] = []
    engine.listen(events.append)
    name.setText('A')
    count.setValue(4)
    assert engine.attributes(node)['name'] == 'A'
    assert engine.attributes(node)['count'] == 4
    results = [
        delta.new.value
        for event in events if event.graph is not None
        for attrs in event.graph.attributes.values()
        for delta in attrs.updated.values() if isinstance(delta.new, SucceededStatus)
    ]
    assert results == ['AAA', 'AAAA']
    assert inspector._editors['name'] is name
    assert inspector._editors['count'] is count


def test_external_set_and_unset_refresh_without_feedback(
    qtbot: QtBot, make_engine: Callable[[str], EagerEngine],
) -> None:
    engine = make_engine('def source(value: int = 1000): return value')
    node = engine.node('source')
    inspector = InspectorView(engine)
    qtbot.addWidget(inspector)
    inspector.setCurrentNode(node)
    events: list[EagerEngineChange] = []
    engine.listen(events.append)
    engine.set(node, value=0)
    assert cast(QSpinBox, inspector._editors['value']).value() == 0
    assert len(events) == 2  # One attribute event and one dirty event.
    events.clear()
    engine.unset(node, 'value')
    editor = cast(QSpinBox, inspector._editors['value'])
    assert editor.text() == ''
    assert editor.metaObject().userProperty().read(editor) != 1000
    assert 'value' not in engine.attributes(node)
    assert len(events) == 2


def test_false_empty_none_and_missing_remain_distinct(
    qtbot: QtBot, make_engine: Callable[[str], EagerEngine],
) -> None:
    engine = make_engine('def source(required: int, text: str = "Default", flag=False, value=None): pass')
    node = engine.node('source', text='', flag=False, value=None)
    inspector = InspectorView(engine)
    qtbot.addWidget(inspector)
    inspector.setCurrentNode(node)
    assert cast(QLineEdit, inspector._editors['text']).text() == ''
    assert cast(QLabel, inspector._editors['flag']).text() == 'False'
    assert cast(QLabel, inspector._editors['value']).text() == 'None'
    assert cast(QSpinBox, inspector._editors['required']).text() == ''
    assert 'required' not in engine.attributes(node)


def test_links_disable_literal_editor_and_disconnect_leaves_input_unset(
    qtbot: QtBot, make_engine: Callable[[str], EagerEngine],
) -> None:
    engine = make_engine('def source(): return 7\ndef target(value: int = 5): return value')
    source = engine.node('source')
    target = engine.node('target', value=source)
    inspector = InspectorView(engine)
    qtbot.addWidget(inspector)
    inspector.setCurrentNode(target)
    assert isinstance(inspector._editors['value'], QLabel)
    assert 'Connected:' in cast(QLabel, inspector._editors['value']).text()
    engine.remove_link(source, target, 'value')
    assert 'value' not in engine.attributes(target)
    assert cast(QSpinBox, inspector._editors['value']).text() == ''
    engine.add_link(source, target, 'value')
    assert isinstance(inspector._editors['value'], QLabel)


def test_script_defaults_refresh_and_selection_connections_are_replaced(
    qtbot: QtBot, make_engine: Callable[[str], EagerEngine],
) -> None:
    engine = make_engine('def source(value: int = 2): return value')
    first = engine.node('source')
    second = engine.node('source')
    inspector = InspectorView(engine)
    qtbot.addWidget(inspector)
    inspector.setCurrentNode(first)
    engine.set_script('def source(value: str = "New"): return value')
    assert cast(QLineEdit, inspector._editors['value']).text() == ''
    assert 'value' not in engine.attributes(first)
    inspector.setCurrentNode(second)
    cast(QLineEdit, inspector._editors['value']).setText('Second')
    assert 'value' not in engine.attributes(first)
    assert engine.attributes(second)['value'] == 'Second'
    engine.delete(second)
    assert inspector._current_node is None
    assert inspector._editors == {}


def test_editing_unset_input_preserves_parameter_order_and_widgets(
    qtbot: QtBot, make_engine: Callable[[str], EagerEngine],
) -> None:
    engine = make_engine('def greet(name: str = "World", greeting: str = "Hello"): return greeting + name')
    node = engine.node('greet')
    inspector = InspectorView(engine)
    qtbot.addWidget(inspector)
    inspector.setCurrentNode(node)
    editors = dict(inspector._editors)
    cast(QLineEdit, editors['greeting']).setText('Hi')
    assert list(inspector._editors) == ['name', 'greeting']
    assert inspector._editors == editors
    assert engine.attributes(node)['greeting'] == 'Hi'
    assert cast(QLineEdit, editors['greeting']).text() == 'Hi'
    assert cast(QLineEdit, editors['name']).text() == ''


def test_evaluation_uses_defaults_while_inspector_stays_unset(
    qtbot: QtBot, make_engine: Callable[[str], EagerEngine],
) -> None:
    engine = make_engine('def source(value: int = 42): return value')
    node = engine.node('source')
    inspector = InspectorView(engine)
    qtbot.addWidget(inspector)
    inspector.setCurrentNode(node)
    events: list[EagerEngineChange] = []
    engine.listen(events.append)
    engine.evaluate_node(node)
    results = [
        delta.new.value
        for event in events if event.graph is not None
        for attrs in event.graph.attributes.values()
        for delta in attrs.updated.values() if isinstance(delta.new, SucceededStatus)
    ]
    assert results == [42]
    assert cast(QSpinBox, inspector._editors['value']).text() == ''
    assert 'value' not in engine.attributes(node)
