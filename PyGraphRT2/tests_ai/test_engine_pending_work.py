"""Runtime lifecycle notifications and snapshots require no presentation model."""

from collections.abc import Iterator

import pytest
from qtpy.QtCore import QCoreApplication

from pygraphrt2 import Engine, NodeRef, ScriptOperatorRef
from pygraphrt2.exceptions import ExecutionFailure
from pygraphrt2.execution_plan import ExecutionResult, evaluate
from PyGraphRT2.tests_ai.controlled_backend import ControlledBackend


@pytest.fixture
def controlled(
    qapp: object, monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[Engine, ControlledBackend]]:
    monkeypatch.setattr("pygraphrt2.engine.ThreadedBackend", ControlledBackend)
    engine = Engine()
    engine.set_auto_execute(False)
    try:
        yield engine, engine._backend
    finally:
        engine.close()


def test_snapshots_cover_evaluation_deferred_execution_and_completion(
    controlled: tuple[Engine, ControlledBackend],
) -> None:
    engine, backend = controlled
    node = engine._graph._create_node(ScriptOperatorRef(engine._registry, "answer"))
    evaluations: list[bool] = []
    executions: list[frozenset[NodeRef]] = []
    engine.evaluation_pending_changed.connect(lambda: evaluations.append(engine.evaluation_pending()))
    engine.execution_pending_changed.connect(lambda: executions.append(engine.pending_nodes()))

    engine.evaluate_registry()
    assert evaluations == [True]
    assert engine.pending_nodes() == frozenset()
    engine.execute_nodes(node)
    assert executions[-1] == frozenset({node})
    backend.evaluations[-1].set_result(evaluate("def answer(): return 42"))
    QCoreApplication.processEvents()
    assert evaluations == [True, False]
    snapshot = engine.pending_nodes()
    assert snapshot == frozenset({node})
    backend.executions[-1].set_result(ExecutionResult({node.name(): 42}))
    QCoreApplication.processEvents()
    assert executions[-1] == frozenset()
    assert snapshot == frozenset({node})  # Callers cannot mutate engine bookkeeping.


@pytest.mark.parametrize("action", ["cancel", "failure", "close", "edit"])
def test_execution_lifecycle_reports_ending_work(
    controlled: tuple[Engine, ControlledBackend], action: str,
) -> None:
    engine, backend = controlled
    node = engine._graph._create_node(lambda: 42)
    pending: list[frozenset[NodeRef]] = []
    failures: list[ExecutionFailure] = []
    engine.execution_pending_changed.connect(lambda: pending.append(engine.pending_nodes()))
    engine.execution_failed.connect(failures.append)
    engine.execute_nodes(node)
    assert pending == [frozenset({node})]
    if action == "cancel":
        backend.executions[-1].cancel()
    elif action == "failure":
        backend.executions[-1].set_exception(ValueError("backend failed"))
    elif action == "close":
        engine.close()
    else:
        engine.set_script("# edited")
    QCoreApplication.processEvents()
    assert pending[-1] == frozenset()
    assert engine.pending_nodes() == frozenset()
    if action == "failure":
        assert failures[0].targets == (node,)
        assert str(failures[0].error) == "backend failed"
    else:
        assert failures == []


def test_stale_completion_emits_no_lifecycle_or_failure_event(
    controlled: tuple[Engine, ControlledBackend],
) -> None:
    engine, backend = controlled
    node = engine._graph._create_node(lambda: 42)
    engine.execute_nodes(node)
    stale = backend.executions[-1]
    stale.set_running_or_notify_cancel()
    engine.execute_nodes(node)
    events: list[str] = []
    engine.execution_pending_changed.connect(lambda: events.append("pending"))
    engine.execution_failed.connect(lambda _: events.append("failed"))
    stale.set_exception(ValueError("old request"))
    QCoreApplication.processEvents()
    assert events == []
    assert engine.pending_nodes() == frozenset({node})
