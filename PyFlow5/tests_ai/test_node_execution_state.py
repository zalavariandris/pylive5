"""The graph model owns node status while the engine reports pending work."""

from collections.abc import Callable, Iterator
from threading import Event, get_ident
from typing import Any

import pytest
from pytestqt.qtbot import QtBot
from qtpy.QtCore import QCoreApplication

from pygraphrt2 import Engine, NodeRef, ScriptOperatorRef
from pyflow5.core.node_execution_state import NodeExecutionState
from pyflow5.models.pygraphrt_graphmodel import PyGraphRTGraphModel
from PyGraphRT2.tests_ai.controlled_backend import ControlledBackend
from pygraphrt2.execution_plan import ExecutionResult, NodeExecutionError, evaluate


@pytest.fixture
def controlled(
    qapp: object, monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[Engine, ControlledBackend, PyGraphRTGraphModel]]:
    monkeypatch.setattr("pygraphrt2.engine.ThreadedBackend", ControlledBackend)
    engine = Engine()
    engine.set_auto_execute(False)
    model = PyGraphRTGraphModel(engine)
    try:
        yield engine, engine._backend, model
    finally:
        model.close()
        engine.close()


def test_execution_marks_only_uncached_dependencies_and_returns_to_idle(
    controlled: tuple[Engine, ControlledBackend, PyGraphRTGraphModel],
) -> None:
    engine, backend, model = controlled
    source = engine._graph._create_node(lambda: 1, name="source")
    target = engine._graph._create_node(lambda value: value + 1, args=(source,), name="target")
    unrelated = engine._graph._create_node(lambda: 3, name="unrelated")
    changes: list[dict[NodeRef, NodeExecutionState]] = []
    model.nodesDataChanged.connect(
        lambda names, roles: changes.append({
            model.mapToSource(name): model.nodeData(name, model.StateRole) for name in names
        })
    )

    assert model.nodeData(target.name(), model.StateRole) is NodeExecutionState.IDLE
    engine.execute_nodes(target)
    assert changes == [{source: NodeExecutionState.EXECUTING, target: NodeExecutionState.EXECUTING}]
    assert model.nodeData(unrelated.name(), model.StateRole) is NodeExecutionState.IDLE
    backend.executions[-1].set_result(ExecutionResult({"source": 1, "target": 2}))
    QCoreApplication.processEvents()
    assert changes[-1] == {source: NodeExecutionState.IDLE, target: NodeExecutionState.IDLE}

    engine._graph._update_node(target, lambda value: value * 2, args=(source,))
    engine.execute_nodes(target)
    assert model.nodeData(source.name(), model.StateRole) is NodeExecutionState.IDLE
    assert model.nodeData(target.name(), model.StateRole) is NodeExecutionState.EXECUTING
    backend.executions[-1].set_result(ExecutionResult({"source": 1, "target": 2}))
    QCoreApplication.processEvents()
    changes.clear()
    engine.execute_nodes(target)
    assert changes == []  # A fully cached request never turns yellow.


def test_failure_marks_only_failed_node_and_retry_clears_error(
    controlled: tuple[Engine, ControlledBackend, PyGraphRTGraphModel],
) -> None:
    engine, backend, model = controlled
    source = engine._graph._create_node(lambda: 1, name="source")
    target = engine._graph._create_node(lambda value: value, args=(source,), name="target")
    engine.execute_nodes(target)
    error = ValueError("bad input")
    backend.executions[-1].set_exception(NodeExecutionError("source", error))
    QCoreApplication.processEvents()
    assert model.nodeData(source.name(), model.StateRole) is NodeExecutionState.ERROR
    assert model._node_error(source) is error
    assert model.nodeData(target.name(), model.StateRole) is NodeExecutionState.IDLE

    engine.execute_nodes(target)
    assert model.nodeData(source.name(), model.StateRole) is NodeExecutionState.EXECUTING
    assert model._node_error(source) is None
    backend.executions[-1].set_result(ExecutionResult({"source": 1, "target": 1}))
    QCoreApplication.processEvents()
    assert model.nodeData(source.name(), model.StateRole) is NodeExecutionState.IDLE
    assert model._node_error(source) is None


@pytest.mark.parametrize("fails", [False, True])
def test_registry_loading_and_recovery(
    controlled: tuple[Engine, ControlledBackend, PyGraphRTGraphModel], fails: bool,
) -> None:
    engine, backend, model = controlled
    node = engine._graph._create_node(ScriptOperatorRef(engine._registry, "answer"))
    assert model.nodeData(node.name(), model.StateRole) is NodeExecutionState.IDLE
    engine.evaluate_registry()
    engine.execute_nodes(node)
    assert model.nodeData(node.name(), model.StateRole) is NodeExecutionState.EXECUTING
    assert model._node_error(node) is None
    if fails:
        error = SyntaxError("broken script")
        backend.evaluations[-1].set_exception(error)
        QCoreApplication.processEvents()
        assert model.nodeData(node.name(), model.StateRole) is NodeExecutionState.ERROR
        assert model._node_error(node) is error
        engine.evaluate_registry()
        engine.execute_nodes(node)
        assert model.nodeData(node.name(), model.StateRole) is NodeExecutionState.EXECUTING

    backend.evaluations[-1].set_result(evaluate("def answer(): return 42"))
    QCoreApplication.processEvents()
    assert model.nodeData(node.name(), model.StateRole) is NodeExecutionState.EXECUTING
    backend.executions[-1].set_result(ExecutionResult({node.name(): 42}))
    QCoreApplication.processEvents()
    assert model.nodeData(node.name(), model.StateRole) is NodeExecutionState.IDLE


def test_missing_operator_is_an_error_only_after_evaluation(
    controlled: tuple[Engine, ControlledBackend, PyGraphRTGraphModel],
) -> None:
    engine, backend, model = controlled
    node = engine._graph._create_node(ScriptOperatorRef(engine._registry, "missing"))
    engine.evaluate_registry()
    backend.evaluations[-1].set_result({})
    QCoreApplication.processEvents()
    assert model.nodeData(node.name(), model.StateRole) is NodeExecutionState.ERROR
    assert "missing" in str(model._node_error(node))


@pytest.mark.parametrize("evaluation", [False, True])
@pytest.mark.parametrize("action", ["cancel", "close", "edit", "remove"])
def test_abandoned_work_does_not_leave_nodes_executing(
    controlled: tuple[Engine, ControlledBackend, PyGraphRTGraphModel], evaluation: bool, action: str,
) -> None:
    engine, backend, model = controlled
    operator = ScriptOperatorRef(engine._registry, "answer") if evaluation else lambda: 42
    node = engine._graph._create_node(operator)
    if evaluation:
        engine.evaluate_registry()
        future = backend.evaluations[-1]
    else:
        engine.execute_nodes(node)
        future = backend.executions[-1]
    assert model.nodeData(node.name(), model.StateRole) is NodeExecutionState.EXECUTING
    if action == "cancel":
        future.cancel()
    elif action == "close":
        engine.close()
    elif action == "edit":
        engine.set_script("def answer(): return 99")
    else:
        engine._graph._delete_node(node)
    QCoreApplication.processEvents()
    if action == "remove":
        assert node.name() not in model._node_states
        assert node not in engine.pending_nodes()
    else:
        assert model.nodeData(node.name(), model.StateRole) is NodeExecutionState.IDLE


@pytest.mark.parametrize("fails", [False, True])
@pytest.mark.parametrize("evaluation", [False, True])
def test_stale_completion_cannot_replace_current_state(
    controlled: tuple[Engine, ControlledBackend, PyGraphRTGraphModel], fails: bool, evaluation: bool,
) -> None:
    engine, backend, model = controlled
    node = engine._graph._create_node(
        ScriptOperatorRef(engine._registry, "answer") if evaluation else lambda: 42,
    )
    if evaluation:
        start: Callable[[], None] = engine.evaluate_registry
        futures = backend.evaluations
    else:
        start = lambda: engine.execute_nodes(node)
        futures = backend.executions
    start()
    old = futures[-1]
    old.set_running_or_notify_cancel()
    start()
    if fails:
        old.set_exception(ValueError("stale failure"))
    else:
        old.set_result({} if evaluation else ExecutionResult({}))
    QCoreApplication.processEvents()
    assert model.nodeData(node.name(), model.StateRole) is NodeExecutionState.EXECUTING
    futures[-1].cancel()
    QCoreApplication.processEvents()
    assert model.nodeData(node.name(), model.StateRole) is NodeExecutionState.IDLE


def test_preparation_failure_sets_error_and_edit_clears_it(
    controlled: tuple[Engine, ControlledBackend, PyGraphRTGraphModel],
) -> None:
    engine, _, model = controlled
    node = engine._graph._create_node(lambda value: value)
    engine._graph._update_node(node, lambda value: value, args=(node,))
    engine.execute_nodes(node)
    assert model.nodeData(node.name(), model.StateRole) is NodeExecutionState.ERROR
    engine._graph._update_node(node, lambda: 42)
    assert model.nodeData(node.name(), model.StateRole) is NodeExecutionState.IDLE


def test_real_worker_publishes_states_on_gui_thread(qtbot: QtBot) -> None:
    engine = Engine()
    engine.set_auto_execute(False)
    release = Event()
    entered = Event()

    def slow() -> int:
        entered.set()
        if not release.wait(3):
            raise TimeoutError("test did not release worker")
        return get_ident()

    node = engine._graph._create_node(slow)
    model = PyGraphRTGraphModel(engine)
    threads: list[int] = []
    model.nodesDataChanged.connect(lambda *_: threads.append(get_ident()))
    try:
        engine.execute_nodes(node)
        qtbot.waitUntil(entered.is_set)
        assert model.nodeData(node.name(), model.StateRole) is NodeExecutionState.EXECUTING
        with qtbot.waitSignal(engine.nodes_executed) as completed:
            release.set()
        assert completed.args[0][node] != get_ident()
        assert len(threads) >= 2 and all(thread == get_ident() for thread in threads)
        assert model.nodeData(node.name(), model.StateRole) is NodeExecutionState.IDLE
    finally:
        release.set()
        model.close()
        engine.close()


def test_state_observer_can_supersede_a_completion(
    controlled: tuple[Engine, ControlledBackend, PyGraphRTGraphModel],
) -> None:
    engine, backend, model = controlled
    node = engine._graph._create_node(lambda: 42)
    outputs: list[dict[NodeRef, Any]] = []
    engine.nodes_executed.connect(outputs.append)
    engine.execute_nodes(node)

    def rerun(nodes: tuple[str, ...], roles: tuple[int, ...]) -> None:
        if model.nodeData(node.name(), model.StateRole) is NodeExecutionState.IDLE and len(backend.executions) == 1:
            engine._graph._update_node(node, lambda: 99)
            engine.execute_nodes(node)

    model.nodesDataChanged.connect(rerun)
    backend.executions[-1].set_result(ExecutionResult({node.name(): 42}))
    QCoreApplication.processEvents()
    assert model.nodeData(node.name(), model.StateRole) is NodeExecutionState.EXECUTING
    assert outputs == []
    backend.executions[-1].set_result(ExecutionResult({node.name(): 99}))
    QCoreApplication.processEvents()
    assert outputs == [{node: 99}]


def test_state_observer_can_close_before_evaluation_is_submitted(
    controlled: tuple[Engine, ControlledBackend, PyGraphRTGraphModel],
) -> None:
    engine, backend, model = controlled
    engine._graph._create_node(ScriptOperatorRef(engine._registry, "answer"))
    model.nodesDataChanged.connect(lambda *_: engine.close())
    engine.evaluate_registry()
    assert backend.evaluations == []


@pytest.mark.parametrize("fails", [False, True])
def test_model_attached_during_execution_initializes_and_observes_result(
    controlled: tuple[Engine, ControlledBackend, PyGraphRTGraphModel], fails: bool,
) -> None:
    engine, backend, _ = controlled
    node = engine._graph._create_node(lambda: 42)
    engine.execute_nodes(node)
    model = PyGraphRTGraphModel(engine)
    try:
        assert model.nodeData(node.name(), model.StateRole) is NodeExecutionState.EXECUTING
        if fails:
            error = ValueError("bad input")
            backend.executions[-1].set_exception(NodeExecutionError(node.name(), error))
        else:
            backend.executions[-1].set_result(ExecutionResult({node.name(): 42}))
        QCoreApplication.processEvents()
        expected = NodeExecutionState.ERROR if fails else NodeExecutionState.IDLE
        assert model.nodeData(node.name(), model.StateRole) is expected
        assert model.nodeData(node.name(), model.OutputRole) == (None if fails else 42)
        assert model.nodeData(node.name(), model.ErrorRole) is (error if fails else None)
    finally:
        model.close()


@pytest.mark.parametrize("through_model", [False, True])
def test_removing_and_recreating_node_discards_its_presentation_history(
    controlled: tuple[Engine, ControlledBackend, PyGraphRTGraphModel], through_model: bool,
) -> None:
    engine, backend, model = controlled
    engine._registry._apply_functions(evaluate("def answer(): return 42"), "VALID")
    operator = engine.get_operator_by_name("answer")
    assert operator is not None
    model.addNode(operator)
    node = model.mapToSource("answer")
    assert node is not None
    engine.execute_nodes(node)
    backend.executions[-1].set_exception(NodeExecutionError("answer", ValueError("bad input")))
    QCoreApplication.processEvents()
    assert model.nodeData("answer", model.StateRole) is NodeExecutionState.ERROR
    if through_model:
        model.removeNodes(["answer"])
        model.addNode(operator)
    else:
        engine._graph._delete_node(node)
        engine._graph._create_node(operator, name="answer")
    assert model.nodeData("answer", model.StateRole) is NodeExecutionState.IDLE
    assert model.nodeData("answer", model.OutputRole) is None
