"""Stable bindings survive unavailable functions, while explicit edits replace them."""

from collections.abc import Iterator
from typing import Callable

import pytest

from pygraphrt2 import (
    Engine, Graph, GraphDeserializer, GraphSerializer, InlineScriptModule,
    OperatorUnavailableError, ScriptOperatorRef,
)
from pygraphrt2.inline_executor import ExecutionFailure


SOURCE = "def answer(value: int = 7) -> int:\n    return value\n"


@pytest.fixture
def engine(qapp: object) -> Iterator[Engine]:
    engine = Engine()
    engine.registry.set_script(SOURCE)
    engine.evaluate_registry()
    try:
        yield engine
    finally:
        engine.close()


@pytest.mark.parametrize("source", ["", "def answer(:", "raise ValueError('broken')"])
def test_reference_and_node_recover_after_removal_or_script_failure(
    engine: Engine, source: str,
) -> None:
    operator = engine.registry.get_operator_by_name("answer")
    original_hash = hash(operator)
    node = engine.graph._create_node(operator, kwargs={"value": 9})
    errors: list[ExecutionFailure] = []
    outputs: list[dict] = []
    engine.execution_failed.connect(errors.append)
    engine.nodes_executed.connect(outputs.append)
    engine.nodes_invalidated.connect(lambda nodes: engine.execute_nodes(node))

    assert operator.is_available()
    assert operator() == 7
    engine.registry.set_script(source)
    engine.evaluate_registry()

    assert not operator.is_available()
    assert hash(operator) == original_hash
    assert node.resolve().operator is operator
    assert node.resolve().kwargs == {"value": 9}
    assert engine.node_operator(node) is operator
    assert operator.get_parameters() == {}
    assert operator.get_line_number() is None
    assert len(errors) == 1
    assert errors[0].node == node
    assert isinstance(errors[0].error, OperatorUnavailableError)
    assert errors[0].error.operator is operator
    assert outputs == []
    with pytest.raises(OperatorUnavailableError, match="answer") as caught:
        operator.resolve()
    if source:
        assert caught.value.__cause__ is engine.registry.get_state()

    engine.registry.set_script(SOURCE.replace("return value", "return value * 2"))
    engine.evaluate_registry()
    assert node.resolve().operator is operator
    assert operator.is_available()
    assert operator == engine.registry.get_operator_by_name("answer")
    assert outputs[-1][node] == 18
    assert len(errors) == 1


def test_input_edits_preserve_an_unavailable_binding(engine: Engine) -> None:
    operator = engine.registry.get_operator_by_name("answer")
    node = engine.graph._create_node(operator)
    engine.registry.set_script("")
    engine.evaluate_registry()
    engine.graph._update_node(node, node.resolve().operator, (), {"value": 12})
    assert engine.node_operator(node) is operator
    assert not operator.is_available()

    engine.registry.set_script(SOURCE)
    engine.evaluate_registry()
    assert node() == 12


@pytest.mark.parametrize("replacement", [None, lambda: 42])
def test_direct_assignment_removes_the_old_script_binding(
    engine: Engine, replacement: Callable[[], int] | None,
) -> None:
    operator = engine.registry.get_operator_by_name("answer")
    node = engine.graph._create_node(operator)
    engine.registry.set_script("")
    engine.evaluate_registry()
    engine.graph._update_node(node, replacement)
    assert engine.node_operator(node) is None

    engine.registry.set_script(SOURCE)
    engine.evaluate_registry()
    assert node.resolve().operator is replacement
    assert engine.node_operator(node) is None


def test_direct_rebinding_to_a_missing_function_recovers_that_function(engine: Engine) -> None:
    node = engine.graph._create_node(engine.registry.get_operator_by_name("answer"))
    replacement = ScriptOperatorRef(engine.registry, "other")
    engine.graph._update_node(node, replacement)
    assert engine.node_operator(node) is replacement
    assert not replacement.is_available()

    engine.registry.set_script(SOURCE + "\ndef other(): return 42\n")
    engine.evaluate_registry()
    assert node.resolve().operator is replacement
    assert node() == 42


def test_loaded_missing_binding_is_indexed_and_none_stays_unbound(qapp: object) -> None:
    registry = InlineScriptModule()
    graph = Graph()
    graph._create_node(ScriptOperatorRef(registry, "answer"), name="bound")
    graph._create_node(name="unbound")
    restored_registry, restored_graph = GraphDeserializer().fromdict(
        GraphSerializer(graph, registry).todict()
    )
    engine = Engine(restored_graph, restored_registry)
    try:
        bound, unbound = restored_graph.nodes()
        operator = bound.resolve().operator
        assert isinstance(operator, ScriptOperatorRef)
        assert engine.node_operator(bound) is operator
        assert not operator.is_available()
        assert engine.node_operator(unbound) is None
        restored_registry.set_script(SOURCE)
        engine.evaluate_registry()
        assert bound() == 7
        assert unbound.resolve().operator is None
        restored_graph._delete_node(bound)
        assert engine.node_operator(bound) is None
    finally:
        engine.close()


@pytest.mark.parametrize("source", [None, 42, {}])
def test_invalid_source_data_is_not_treated_as_an_editable_script_error(source: object) -> None:
    with pytest.raises(ValueError, match="source string"):
        GraphDeserializer().fromdict({"version": 4, "script": {"source": source}})
