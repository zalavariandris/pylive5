"""Automatic execution catches up when resumed or given new targets."""

from collections.abc import Iterator

import pytest

from pygraphrt2 import Engine, NodeRef


SOURCE = "def answer(value: int = 7) -> int:\n    return value\n"


@pytest.fixture
def engine(qapp: object) -> Iterator[Engine]:
    engine = Engine()
    engine.set_auto_execute_targets([])
    engine.registry.set_script(SOURCE)
    try:
        yield engine
    finally:
        engine.close()


def test_resuming_evaluates_latest_script_and_refreshes_targets(engine: Engine) -> None:
    operator = engine.registry.get_operator_by_name("answer")
    node = engine.graph._create_node(operator, kwargs={"value": 9})
    engine.set_auto_execute_targets([node])
    engine.set_auto_execute(False)
    outputs: list[dict[NodeRef, object]] = []
    evaluations: list[bool] = []
    engine.nodes_executed.connect(outputs.append)
    engine.registry_evaluated.connect(lambda: evaluations.append(True))

    engine.registry.set_script(SOURCE.replace("return value", "return value * 2"))
    assert evaluations == []
    assert outputs == []

    engine.set_auto_execute(True)
    assert evaluations == [True]
    assert outputs == [{node: 18}]

    engine.set_auto_execute(True)
    assert evaluations == [True]
    assert outputs == [{node: 18}]

    engine.graph._update_node(node, operator, kwargs={"value": 10})
    assert outputs[-1] == {node: 20}


def test_resuming_refreshes_graph_edits_and_targets_changed_while_paused(
    engine: Engine,
) -> None:
    operator = engine.registry.get_operator_by_name("answer")
    node = engine.graph._create_node(operator)
    outputs: list[dict[NodeRef, object]] = []
    engine.nodes_executed.connect(outputs.append)
    engine.set_auto_execute(False)

    engine.graph._update_node(node, operator, kwargs={"value": 11})
    engine.set_auto_execute_targets([node])
    assert outputs == []

    engine.set_auto_execute(True)
    assert outputs == [{node: 11}]


def test_watching_a_previously_invalidated_node_executes_it_immediately(
    engine: Engine,
) -> None:
    operator = engine.registry.get_operator_by_name("answer")
    node = engine.graph._create_node(operator)
    outputs: list[dict[NodeRef, object]] = []
    engine.nodes_executed.connect(outputs.append)

    engine.graph._update_node(node, operator, kwargs={"value": 12})
    assert outputs == []

    engine.set_auto_execute_targets([node])
    assert outputs == [{node: 12}]

    engine.set_auto_execute_targets(iter([node, node]))
    assert outputs == [{node: 12}]


@pytest.mark.parametrize(
    ("initial", "updated", "expected"),
    [
        ([], ["first"], {"first"}),
        (["first"], ["first", "second"], {"second"}),
        (["first"], None, {"second"}),
        (None, ["first"], set()),
        (None, [], set()),
        (["first"], [], set()),
        ([], None, {"first", "second"}),
        (["first", "second"], ["second", "first"], set()),
    ],
)
def test_target_changes_execute_only_newly_included_nodes(
    engine: Engine,
    initial: list[str] | None,
    updated: list[str] | None,
    expected: set[str],
) -> None:
    operator = engine.registry.get_operator_by_name("answer")
    nodes = {
        name: engine.graph._create_node(operator, name=name)
        for name in ("first", "second")
    }
    engine.set_auto_execute_targets(
        None if initial is None else [nodes[name] for name in initial]
    )
    outputs: list[dict[NodeRef, object]] = []
    engine.nodes_executed.connect(outputs.append)

    engine.set_auto_execute_targets(
        None if updated is None else [nodes[name] for name in updated]
    )

    assert len(outputs) == (1 if expected else 0)
    if expected:
        assert {node.name() for node in outputs[0]} == expected


def test_new_targets_share_one_execution_of_their_dependency(engine: Engine) -> None:
    calls: list[str] = []

    def source() -> int:
        calls.append("source")
        return 3

    def double(value: int) -> int:
        calls.append("double")
        return value * 2

    def triple(value: int) -> int:
        calls.append("triple")
        return value * 3

    source_node = engine.graph._create_node(source)
    double_node = engine.graph._create_node(double, args=(source_node,))
    triple_node = engine.graph._create_node(triple, args=(source_node,))
    outputs: list[dict[NodeRef, object]] = []
    engine.nodes_executed.connect(outputs.append)

    engine.set_auto_execute_targets([double_node, triple_node])

    assert outputs == [{source_node: 3, double_node: 6, triple_node: 9}]
    assert calls[0] == "source"
    assert sorted(calls) == ["double", "source", "triple"]


def test_closed_engine_does_not_execute_when_configuration_changes(engine: Engine) -> None:
    node = engine.graph._create_node(engine.registry.get_operator_by_name("answer"))
    outputs: list[dict[NodeRef, object]] = []
    evaluations: list[bool] = []
    engine.nodes_executed.connect(outputs.append)
    engine.registry_evaluated.connect(lambda: evaluations.append(True))
    engine.close()

    engine.set_auto_execute_targets([node])
    engine.set_auto_execute(False)
    engine.set_auto_execute(True)

    assert outputs == []
    assert evaluations == []


@pytest.mark.parametrize("change", ["graph", "registry"])
def test_invalidation_observers_run_before_automatic_execution(
    engine: Engine, change: str,
) -> None:
    operator = engine.registry.get_operator_by_name("answer")
    node = engine.graph._create_node(operator)
    engine.set_auto_execute_targets([node])
    events: list[str] = []
    outputs: list[dict[NodeRef, object]] = []

    def on_executed(results: dict[NodeRef, object]) -> None:
        events.append("executed")
        outputs.append(results)

    engine.nodes_invalidated.connect(lambda nodes: events.append("invalidated"))
    engine.nodes_executed.connect(on_executed)

    if change == "graph":
        engine.graph._update_node(node, operator, kwargs={"value": 11})
        expected = 11
    else:
        engine.registry.set_script(SOURCE.replace("return value", "return value * 2"))
        expected = 14

    assert events == ["invalidated", "executed"]
    assert outputs == [{node: expected}]
