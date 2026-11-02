"""Registry removal clears callables while retaining bindings for restoration."""

from collections.abc import Callable, Iterator

import pytest
from pytestqt.qtbot import QtBot

from pygraphrt2 import Engine, NodeRef


SOURCE = "def answer(value=7, *, offset=0): return value + offset\n"


@pytest.fixture
def engine(qapp: object) -> Iterator[Engine]:
    engine = Engine()
    engine.set_auto_execute(False)
    engine._registry.set_script(SOURCE)
    engine._registry.evaluate()
    try:
        yield engine
    finally:
        engine.close()


def test_removal_and_restoration_preserve_bindings_inputs_and_notifications(
    engine: Engine, qtbot: QtBot,
) -> None:
    operator = engine._registry.get_operator_by_name("answer")
    first = engine._graph._create_node(operator, args=(9,), kwargs={"offset": 2})
    second = engine._graph._create_node(operator, args=(first,))
    changed: list[list[NodeRef]] = []
    invalidated: list[list[NodeRef]] = []
    engine._graph.nodes_changed.connect(changed.append)
    engine.nodes_invalidated.connect(invalidated.append)

    engine._registry.set_script("")
    engine._registry.evaluate()

    for node in (first, second):
        assert node.resolve().operator is None
        assert engine.node_operator(node) is operator
    assert first.resolve().args == (9,)
    assert first.resolve().kwargs == {"offset": 2}
    assert second.resolve().args == (first,)
    assert engine._graph.successors(first) == {second}
    assert {node for batch in changed for node in batch} == {first, second}
    assert any(set(batch) == {first, second} for batch in invalidated)

    changed.clear()
    invalidated.clear()
    engine._registry.set_script(SOURCE.replace("value + offset", "value * 2 + offset"))
    engine._registry.evaluate()

    for node in (first, second):
        assert node.resolve().operator is operator
        assert engine.node_operator(node) is operator
    assert {node for batch in changed for node in batch} == {first, second}
    assert any(set(batch) == {first, second} for batch in invalidated)
    outputs: list[dict[NodeRef, object]] = []
    engine.nodes_executed.connect(outputs.append)
    with qtbot.waitSignal(engine.nodes_executed):
        engine.execute_nodes(second)
    assert outputs[-1][first] == 20
    assert outputs[-1][second] == 40


@pytest.mark.parametrize("replacement", [None, lambda: 42])
def test_explicit_replacement_prevents_restoration(
    engine: Engine, replacement: Callable[[], int] | None,
) -> None:
    node = engine._graph._create_node(engine._registry.get_operator_by_name("answer"))
    engine._registry.set_script("")
    engine._registry.evaluate()

    engine._graph._update_node(node, replacement)
    assert engine.node_operator(node) is None

    engine._registry.set_script(SOURCE)
    engine._registry.evaluate()
    assert node.resolve().operator is replacement


def test_deleted_node_is_not_restored(engine: Engine) -> None:
    node = engine._graph._create_node(engine._registry.get_operator_by_name("answer"))
    engine._registry.set_script("")
    engine._registry.evaluate()
    engine._graph._delete_node(node)

    engine._registry.set_script(SOURCE)
    engine._registry.evaluate()
    assert engine.node_operator(node) is None
    assert engine._graph.nodes() == []
