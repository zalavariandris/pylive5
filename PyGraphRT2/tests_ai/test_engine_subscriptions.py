"""Subscription delivery, cancellation, and independent execution demand."""

from collections.abc import Iterator
from concurrent.futures import Future
from threading import get_ident
from typing import Any

import pytest
from pytestqt.qtbot import QtBot
from qtpy.QtCore import QCoreApplication

from pygraphrt2 import Engine, Graph, Subscription
from pygraphrt2.execution_plan import (
    ContextKey, ContextStateCallback, ExecutionResult, NodeStateSnapshot, execute,
)
from PyGraphRT2.tests_ai.controlled_backend import ControlledBackend


class RecordingBackend(ControlledBackend):
    def __init__(self, graph: Graph) -> None:
        super().__init__(graph)
        self.plans: list[dict[str, NodeStateSnapshot]] = []
        self.initial_outputs: list[dict[str, Any]] = []

    def execute_plan(
        self, plan: dict[str, NodeStateSnapshot],
        initial_outputs: dict[str, Any] | None = None,
        *,
        initial_contextual_outputs: dict[ContextKey, Any] | None = None,
        on_context_state_changed: ContextStateCallback | None = None,
    ) -> Future[ExecutionResult]:
        self.plans.append(plan)
        self.initial_outputs.append(initial_outputs or {})
        return super().execute_plan(
            plan,
            initial_outputs,
            initial_contextual_outputs=initial_contextual_outputs,
            on_context_state_changed=on_context_state_changed,
        )

    def finish(self) -> None:
        self.executions[-1].set_result(execute(
            self.plans[-1],
            self.initial_outputs[-1],
            initial_contextual_outputs=self.initial_contextual_outputs[-1],
            on_context_state_changed=self.context_callbacks[-1],
        ))
        QCoreApplication.processEvents()


@pytest.fixture
def controlled(qapp: object) -> Iterator[tuple[Engine, RecordingBackend]]:
    graph = Graph()
    backend = RecordingBackend(graph)
    engine = Engine(graph=graph, backend=backend)
    try:
        yield engine, backend
    finally:
        engine.close()


def test_initial_delivery_is_queued_and_follows_result_publication(
    controlled: tuple[Engine, RecordingBackend],
) -> None:
    engine, backend = controlled
    node = engine.add_node(lambda: 42)
    events: list[str] = []
    engine.nodes_executed.connect(lambda _: events.append("published"))

    def received(output: int) -> None:
        assert output == 42
        assert engine._cache[node] == 42
        assert subscription.active
        events.append("callback")

    subscription = engine.subscribe(node, received)
    assert backend.executions == []
    assert events == []
    assert engine.pending_nodes() == frozenset({node})
    QCoreApplication.processEvents()
    backend.finish()
    assert events == ["published", "callback"]
    assert engine.pending_nodes() == frozenset()


def test_duplicate_callbacks_have_independent_idempotent_handles(
    controlled: tuple[Engine, RecordingBackend],
) -> None:
    engine, backend = controlled
    node = engine.add_node(lambda: 1)
    received: list[int] = []
    first = engine.subscribe(node, received.append)
    second = engine.subscribe(node, received.append)
    second.unsubscribe()
    second.unsubscribe()
    assert first.active and not second.active
    QCoreApplication.processEvents()
    backend.finish()
    assert received == [1]
    first.unsubscribe()
    assert node not in engine._subscriptions
    engine._graph._update_node(node, lambda: 2)
    QCoreApplication.processEvents()
    assert len(backend.executions) == 1


def test_cached_none_is_delivered_only_to_the_new_subscriber(
    controlled: tuple[Engine, RecordingBackend],
) -> None:
    engine, backend = controlled
    calls: list[bool] = []

    def operation() -> None:
        calls.append(True)

    node = engine.add_node(operation)
    first: list[None] = []
    second: list[None] = []
    engine.subscribe(node, first.append)
    QCoreApplication.processEvents()
    backend.finish()
    engine.subscribe(node, second.append)
    QCoreApplication.processEvents()
    assert backend.plans[-1] == {}
    backend.finish()
    assert first == second == [None]
    assert calls == [True]


@pytest.mark.parametrize("output", [None, False, 0, "", [1, 2], {"answer": 42}])
def test_fresh_and_cached_delivery_preserve_the_output_object(
    controlled: tuple[Engine, RecordingBackend], output: object,
) -> None:
    engine, backend = controlled
    node = engine.add_node(lambda: output)
    received: list[object] = []
    first = engine.subscribe(node, received.append)
    QCoreApplication.processEvents()
    backend.finish()
    first.unsubscribe()
    engine.subscribe(node, received.append)
    QCoreApplication.processEvents()
    assert backend.plans[-1] == {}
    backend.finish()
    assert len(received) == 2
    assert all(result is output for result in received)


@pytest.mark.parametrize("edit", ["subscribed", "unwatched", "delete"])
def test_superseding_work_preserves_every_unfinished_subscription(
    controlled: tuple[Engine, RecordingBackend], edit: str,
) -> None:
    engine, backend = controlled
    first = engine.add_node(lambda: 1, name="first")
    second = engine.add_node(lambda: 2, name="second")
    received: list[int] = []
    engine.subscribe(first, received.append)
    if edit == "subscribed":
        engine.subscribe(second, received.append)
    QCoreApplication.processEvents()
    stale = backend.executions[-1]
    stale.set_running_or_notify_cancel()
    if edit == "delete":
        engine.remove_node(second)
    else:
        engine._graph._update_node(second, lambda: 3)
    QCoreApplication.processEvents()
    assert "first" in backend.plans[-1]
    stale.set_result(ExecutionResult({"first": -1}))
    QCoreApplication.processEvents()
    assert received == []
    backend.finish()
    assert 1 in received
    assert engine._cache[first] == 1
    if edit == "subscribed":
        assert 3 in received
        assert engine._cache[second] == 3


def test_subscribing_does_not_discard_unrelated_manual_execution(
    controlled: tuple[Engine, RecordingBackend],
) -> None:
    engine, backend = controlled
    manual = engine.add_node(lambda: 1, name="manual")
    automatic = engine.add_node(lambda: 2, name="automatic")
    engine.execute_nodes(manual)
    engine.subscribe(automatic, lambda _: None)
    QCoreApplication.processEvents()
    backend.finish()
    assert engine._cache[manual] == 1
    assert engine._cache[automatic] == 2


@pytest.mark.parametrize("action", ["unsubscribe", "delete"])
def test_removed_subscription_demand_is_not_run_after_evaluation(
    controlled: tuple[Engine, RecordingBackend], action: str,
) -> None:
    engine, backend = controlled
    node = engine.add_node(lambda: 1)
    received: list[int] = []
    failures: list[Exception] = []
    engine.execution_failed.connect(failures.append)
    engine.evaluate_registry()
    subscription = engine.subscribe(node, received.append)
    if action == "delete":
        engine.execute_nodes(node)
        engine.remove_node(node)
    else:
        subscription.unsubscribe()
    subscription.unsubscribe()
    assert engine.pending_nodes() == frozenset()
    backend.evaluations[-1].set_result({})
    QCoreApplication.processEvents()
    assert backend.executions == []
    assert failures == received == []


def test_unsubscribing_preserves_an_explicit_deferred_request(
    controlled: tuple[Engine, RecordingBackend],
) -> None:
    engine, backend = controlled
    node = engine.add_node(lambda: 1)
    received: list[int] = []
    engine.evaluate_registry()
    engine.subscribe(node, received.append)
    engine.execute_nodes(node)
    engine.unsubscribe(node, received.append)
    backend.evaluations[-1].set_result({})
    QCoreApplication.processEvents()
    backend.finish()
    assert engine._cache[node] == 1
    assert received == []


def test_callback_can_unsubscribe_and_add_a_subscriber(
    controlled: tuple[Engine, RecordingBackend],
) -> None:
    engine, backend = controlled
    node = engine.add_node(lambda: 1)
    received: list[int] = []
    added: list[Subscription] = []

    def first_callback(output: int) -> None:
        first.unsubscribe()
        second.unsubscribe()
        added.append(engine.subscribe(node, received.append))

    first = engine.subscribe(node, first_callback)
    second = engine.subscribe(node, received.append)
    QCoreApplication.processEvents()
    backend.finish()
    assert received == []
    QCoreApplication.processEvents()
    backend.finish()
    assert received == [1]


def test_callback_exception_does_not_prevent_other_callbacks(
    controlled: tuple[Engine, RecordingBackend], caplog: pytest.LogCaptureFixture,
) -> None:
    engine, backend = controlled
    node = engine.add_node(lambda: 1)
    received: list[int] = []

    def failing_callback(output: int) -> None:
        raise ValueError("broken subscriber")

    engine.subscribe(node, failing_callback)
    engine.subscribe(node, received.append)
    QCoreApplication.processEvents()
    backend.finish()
    assert received == [1]
    assert "broken subscriber" in caplog.text


@pytest.mark.parametrize("action", ["edit", "close"])
def test_callback_mutation_stops_stale_notifications(
    controlled: tuple[Engine, RecordingBackend], action: str,
) -> None:
    engine, backend = controlled
    node = engine.add_node(lambda: 1)
    received: list[int] = []

    def mutate(output: int) -> None:
        first.unsubscribe()
        if action == "edit":
            engine._graph._update_node(node, lambda: 2)
        else:
            engine.close()

    first = engine.subscribe(node, mutate)
    engine.subscribe(node, received.append)
    QCoreApplication.processEvents()
    backend.finish()
    assert received == []
    if action == "edit":
        QCoreApplication.processEvents()
        backend.finish()
        assert received == [2]
        assert engine._cache[node] == 2


def test_cached_dependency_does_not_notify_again(
    controlled: tuple[Engine, RecordingBackend],
) -> None:
    engine, backend = controlled
    source = engine.add_node(lambda: 3, name="source")
    target = engine.add_node(lambda value: value * 2, args=(source,), name="target")
    received: list[int] = []
    engine.subscribe(source, received.append)
    engine.subscribe(target, received.append)
    QCoreApplication.processEvents()
    backend.finish()
    received.clear()
    engine._graph._update_node(target, lambda value: value * 3, args=(source,))
    QCoreApplication.processEvents()
    backend.finish()
    assert received == [9]


def test_unrelated_callback_edit_does_not_lose_an_existing_subscribers_result(
    controlled: tuple[Engine, RecordingBackend],
) -> None:
    engine, backend = controlled
    node = engine.add_node(lambda: 1)
    received: list[int] = []
    edit_enabled = False

    def edit_unrelated_node(output: int) -> None:
        if edit_enabled:
            first.unsubscribe()
            engine.add_node(lambda: 3, name="unrelated")

    first = engine.subscribe(node, edit_unrelated_node)
    engine.subscribe(node, received.append)
    QCoreApplication.processEvents()
    backend.finish()
    assert received == [1]
    edit_enabled = True
    engine._graph._update_node(node, lambda: 2)
    QCoreApplication.processEvents()
    backend.finish()
    assert received == [1]
    QCoreApplication.processEvents()
    assert backend.plans[-1] == {}
    backend.finish()
    assert received == [1, 2]


def test_subscriptions_validate_nodes_and_release_callbacks_on_close(
    controlled: tuple[Engine, RecordingBackend],
) -> None:
    engine, backend = controlled
    node = engine.add_node(lambda: 1)
    foreign = Graph()._create_node(lambda: 1)
    with pytest.raises(ValueError):
        engine.subscribe(foreign, lambda _: None)
    subscription = engine.subscribe(node, lambda _: None)
    engine.close()
    subscription.unsubscribe()
    assert not subscription.active
    assert subscription._callback is None
    assert engine._subscriptions == {}
    with pytest.raises(RuntimeError):
        engine.subscribe(node, lambda _: None)
    QCoreApplication.processEvents()
    assert backend.executions == []


def test_threaded_subscription_runs_callback_on_the_owning_thread(qtbot: QtBot) -> None:
    engine = Engine()
    owner_thread = get_ident()
    node = engine.add_node(get_ident)
    received: list[tuple[int, int]] = []
    try:
        engine.subscribe(node, lambda output: received.append((output, get_ident())))
        qtbot.waitUntil(lambda: bool(received))
        assert received == [(engine._cache[node], owner_thread)]
        assert received[0][0] != owner_thread
    finally:
        engine.close()
