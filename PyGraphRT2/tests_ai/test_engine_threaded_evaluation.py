"""Thread handoff, evaluation dependencies, and superseded engine requests."""

from collections.abc import Callable, Iterator
from concurrent.futures import Future
from threading import get_ident
from typing import Any

import pytest
from pytestqt.qtbot import QtBot
from qtpy.QtCore import QCoreApplication

from pygraphrt2 import Engine, Graph, NodeRef, ScriptOperatorRef
from pygraphrt2.execution_plan import (
    RequestKey, RequestStateCallback, ExecutionResult, NodeStateSnapshot, evaluate, execute,
)
from pygraphrt2.threaded_backend import ThreadedBackend


SOURCE = "def answer(value: int = 7) -> int:\n    return value\n"
Functions = dict[str, Callable[..., Any]]


class ControlledBackend(ThreadedBackend):
    """Allow tests to complete requests in any order without timing sleeps."""

    def __init__(self, graph: Graph) -> None:
        self.graph = graph
        self.evaluations: list[Future[Functions]] = []
        self.plans: list[dict[str, NodeStateSnapshot]] = []
        self.executions: list[Future[ExecutionResult]] = []
        self.closed = False

    def evaluate(self, source: str, *, name: str = "<script>") -> Future[Functions]:
        future: Future[Functions] = Future()
        self.evaluations.append(future)
        return future

    def execute_plan(
        self, plan: dict[str, NodeStateSnapshot],
        initial_outputs: dict[str, Any] | None = None,
        *,
        initial_request_outputs: dict[RequestKey, Any] | None = None,
        on_request_state_changed: RequestStateCallback | None = None,
    ) -> Future[ExecutionResult]:
        future: Future[ExecutionResult] = Future()
        self.plans.append(plan)
        self.executions.append(future)
        return future

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def controlled(
    qapp: object, monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[Engine, ControlledBackend]]:
    monkeypatch.setattr("pygraphrt2.engine.ThreadedBackend", ControlledBackend)
    engine = Engine()
    engine.set_auto_execute(False)
    engine._registry.set_script(SOURCE)
    engine._registry.evaluate()
    backend = engine._backend
    assert isinstance(backend, ControlledBackend)
    try:
        yield engine, backend
    finally:
        engine.close()


def test_worker_functions_reach_the_plan_and_notifications_run_on_gui(qtbot: QtBot) -> None:
    engine = Engine()
    engine.set_auto_execute(False)
    engine._registry.set_script(
        "import threading\n"
        "evaluation_thread = threading.get_ident()\n"
        "def answer():\n"
        "    return evaluation_thread, threading.get_ident(), 42\n"
    )
    node = engine._graph._create_node(ScriptOperatorRef(engine._registry, "answer"))
    gui_threads: list[int] = []
    available_at_notification: list[bool] = []
    engine._registry.operators_added.connect(lambda _: gui_threads.append(get_ident()))

    def on_evaluated() -> None:
        gui_threads.append(get_ident())
        available_at_notification.append(
            engine._registry.get_operator_by_name("answer").is_available()
        )

    engine.registry_evaluated.connect(on_evaluated)
    engine.nodes_executed.connect(lambda _: gui_threads.append(get_ident()))
    try:
        with qtbot.waitSignal(engine.nodes_executed, timeout=3000) as completed:
            engine.evaluate_registry()
            engine.execute_nodes(node)
        evaluation_thread, execution_thread, value = completed.args[0][node]
        assert evaluation_thread == execution_thread
        assert execution_thread != get_ident()
        assert value == 42
        assert gui_threads == [get_ident()] * 3
        assert available_at_notification == [True]
    finally:
        engine.close()


def test_requests_wait_for_functions_and_use_latest_inputs(
    controlled: tuple[Engine, ControlledBackend],
) -> None:
    engine, backend = controlled
    operator = engine._registry.get_operator_by_name("answer")
    first = engine._graph._create_node(operator, name="first")
    second = engine._graph._create_node(operator, name="second")

    engine.evaluate_registry()
    engine.execute_nodes(first)
    engine.execute_nodes(second)
    engine._graph._update_node(first, operator, kwargs={"value": 9})
    assert backend.plans == []

    functions = evaluate(SOURCE.replace("return value", "return value * 2"))
    backend.evaluations[-1].set_result(functions)
    assert backend.plans == []  # Completion is queued even for a finished future.
    QCoreApplication.processEvents()

    assert len(backend.plans) == 1
    plan = backend.plans[0]
    assert execute(plan).outputs == {first.name(): 18, second.name(): 14}
    assert all(snapshot.operator is functions["answer"] for snapshot in plan.values())

    engine._registry._apply_functions(evaluate(SOURCE), "VALID")
    assert execute(plan).outputs == {first.name(): 18, second.name(): 14}


@pytest.mark.parametrize("queued", [False, True])
@pytest.mark.parametrize("fails", [False, True])
def test_superseded_evaluations_cannot_publish_success_or_failure(
    controlled: tuple[Engine, ControlledBackend], queued: bool, fails: bool,
) -> None:
    engine, backend = controlled
    notifications: list[str] = []
    engine.registry_evaluated.connect(lambda: notifications.append("evaluated"))
    engine.registry_failed.connect(lambda _: notifications.append("failed"))
    engine.evaluate_registry()
    old = backend.evaluations[-1]
    old.set_running_or_notify_cancel()

    def finish_old() -> None:
        if fails:
            old.set_exception(ValueError("old evaluation"))
        else:
            old.set_result(evaluate(SOURCE))

    if queued:
        finish_old()
    engine.evaluate_registry()
    backend.evaluations[-1].set_result(evaluate(SOURCE.replace("return value", "return 42")))
    QCoreApplication.processEvents()
    if not queued:
        finish_old()
        QCoreApplication.processEvents()

    assert engine._registry.get_operator_by_name("answer")() == 42
    assert notifications == ["evaluated"]


@pytest.mark.parametrize("fails", [False, True])
def test_starting_evaluation_immediately_supersedes_execution(
    controlled: tuple[Engine, ControlledBackend], fails: bool,
) -> None:
    engine, backend = controlled
    node = engine._graph._create_node(engine._registry.get_operator_by_name("answer"))
    outputs: list[dict[NodeRef, Any]] = []
    errors: list[Exception] = []
    engine.nodes_executed.connect(outputs.append)
    engine.execution_failed.connect(errors.append)
    engine.execute_nodes(node)
    old = backend.executions[-1]
    old.set_running_or_notify_cancel()

    engine.evaluate_registry()
    engine.execute_nodes(node)
    if fails:
        old.set_exception(ValueError("old execution"))
    else:
        old.set_result(ExecutionResult({node.name(): 7}))
    QCoreApplication.processEvents()
    assert outputs == []
    assert errors == []

    backend.evaluations[-1].set_result(evaluate(SOURCE.replace("return value", "return 42")))
    QCoreApplication.processEvents()
    backend.executions[-1].set_result(execute(backend.plans[-1]))
    QCoreApplication.processEvents()
    assert outputs == [{node: 42}]


def test_new_request_discards_an_execution_completion_already_queued(
    controlled: tuple[Engine, ControlledBackend],
) -> None:
    engine, backend = controlled
    node = engine._graph._create_node(engine._registry.get_operator_by_name("answer"))
    outputs: list[dict[NodeRef, Any]] = []
    engine.nodes_executed.connect(outputs.append)
    engine.execute_nodes(node)
    backend.executions[-1].set_result(ExecutionResult({node.name(): 7}))
    engine.execute_nodes(node)
    backend.executions[-1].set_result(ExecutionResult({node.name(): 42}))
    QCoreApplication.processEvents()
    assert outputs == [{node: 42}]


def test_failure_clears_functions_and_pending_work_then_restoration_is_batched(
    controlled: tuple[Engine, ControlledBackend],
) -> None:
    engine, backend = controlled
    operator = engine._registry.get_operator_by_name("answer")
    first = engine._graph._create_node(operator, name="first")
    second = engine._graph._create_node(operator, name="second")
    errors: list[Exception] = []
    engine.registry_failed.connect(errors.append)
    engine.subscribe(first, lambda _: None)
    engine.subscribe(second, lambda _: None)
    engine.set_auto_execute(True)
    engine.execute_nodes(first, second)
    error = SyntaxError("broken script")
    backend.evaluations[-1].set_exception(error)
    QCoreApplication.processEvents()

    assert errors == [error]
    assert engine._registry.get_state() is error
    assert not operator.is_available()
    assert backend.plans == []

    engine.evaluate_registry()
    backend.evaluations[-1].set_result(evaluate(SOURCE))
    QCoreApplication.processEvents()
    assert len(backend.plans) == 1
    assert execute(backend.plans[0]).outputs == {first.name(): 7, second.name(): 7}


def test_deleted_pending_target_is_not_prepared(
    controlled: tuple[Engine, ControlledBackend],
) -> None:
    engine, backend = controlled
    node = engine._graph._create_node(engine._registry.get_operator_by_name("answer"))
    engine.evaluate_registry()
    engine.execute_nodes(node)
    engine._graph._delete_node(node)
    backend.evaluations[-1].set_result(evaluate(SOURCE))
    QCoreApplication.processEvents()
    assert backend.plans == []


def test_evaluated_observer_can_start_a_new_evaluation_before_execution(
    controlled: tuple[Engine, ControlledBackend],
) -> None:
    engine, backend = controlled
    node = engine._graph._create_node(engine._registry.get_operator_by_name("answer"))

    def on_evaluated() -> None:
        if len(backend.evaluations) == 1:
            engine.evaluate_registry()

    engine.registry_evaluated.connect(on_evaluated)
    engine.evaluate_registry()
    engine.execute_nodes(node)
    backend.evaluations[-1].set_result(evaluate(SOURCE))
    QCoreApplication.processEvents()
    assert len(backend.evaluations) == 2
    assert backend.plans == []
    backend.evaluations[-1].set_result(evaluate(SOURCE.replace("return value", "return 42")))
    QCoreApplication.processEvents()
    assert execute(backend.plans[-1]).outputs == {node.name(): 42}


def test_new_evaluation_and_close_cancel_queued_work(
    controlled: tuple[Engine, ControlledBackend],
) -> None:
    engine, backend = controlled
    node = engine._graph._create_node(engine._registry.get_operator_by_name("answer"))
    engine.execute_nodes(node)
    execution = backend.executions[-1]
    engine.evaluate_registry()
    assert execution.cancelled()
    evaluation = backend.evaluations[-1]
    engine.evaluate_registry()
    assert evaluation.cancelled()
    engine.close()
    assert backend.evaluations[-1].cancelled()
    assert backend.closed
    QCoreApplication.processEvents()


@pytest.mark.parametrize("close", [False, True])
def test_source_edit_or_close_discards_running_evaluation(
    controlled: tuple[Engine, ControlledBackend], close: bool,
) -> None:
    engine, backend = controlled
    notifications: list[bool] = []
    engine.registry_evaluated.connect(lambda: notifications.append(True))
    engine.evaluate_registry()
    future = backend.evaluations[-1]
    future.set_running_or_notify_cancel()
    if close:
        engine.close()
    else:
        engine._registry.set_script(SOURCE.replace("return value", "return 99"))
    future.set_result(evaluate(SOURCE.replace("return value", "return 42")))
    QCoreApplication.processEvents()
    assert notifications == []
    assert engine._registry.get_operator_by_name("answer")() == 7
