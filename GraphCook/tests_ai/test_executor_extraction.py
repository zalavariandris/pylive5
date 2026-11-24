"""Execution remains observable through the facade and usable independently."""

from collections.abc import Iterator
from contextlib import contextmanager

from graphcook.core.changes import ObservableValue
from graphcook.eager_observable_engine import (
    DirtyStatus,
    EagerEngine,
    EagerEngineChange,
    ExecutorChange,
    FailedStatus,
    NodeId,
    OperatorHandle,
    SucceededStatus,
    _EngineExecutor,
)
from graphcook.observable_graph import ObservableGraph


@contextmanager
def engine_for(script: str) -> Iterator[EagerEngine]:
    engine = EagerEngine(script)
    try:
        yield engine
    finally:
        engine.close()


def test_executor_starts_once_and_works_without_engine() -> None:
    script = ObservableValue('def source(value: int = 3): return value')
    graph = ObservableGraph[NodeId]()
    node = NodeId("source")
    graph.add_node(node, __operator__=OperatorHandle("source"))
    executor = _EngineExecutor(script, graph)
    events: list[ExecutorChange] = []
    executor.listen(events.append)
    try:
        executor.start()
        executor.start()
        assert sum("provider_status" in event for event in events) == 1
        assert set(executor.operators()) == {OperatorHandle("source")}
        signature = executor.operator_signature(OperatorHandle("source"))
        assert signature is not None
        assert signature.inlets["value"].annotation is int
        assert executor.evaluate_node(node)[node] == 3
        graph.update(node, value=4)
        assert isinstance(executor.nodes_status(node), DirtyStatus)
        assert executor.evaluate_node(node)[node] == 4
    finally:
        executor.close()


def test_facade_forwards_sparse_changes_and_reads_executor_metadata() -> None:
    with engine_for('def source(value: int = 3): return value') as engine:
        events: list[EagerEngineChange] = []
        engine.listen(events.append)
        node = engine.create_node("source")
        assert isinstance(engine.nodes_status(node), DirtyStatus)
        assert set(engine.operators()) == {OperatorHandle("source")}
        assert engine.attributes(node)["__operator__"].inlets["value"].default == 3
        assert any(set(event) == {"nodes_status"} for event in events)
        assert any(set(event) == {"nodes"} for event in events)
        events.clear()
        engine.set_script('def source(value: str = "new"): return value')
        assert sum("script" in event for event in events) == 1
        assert sum("provider_status" in event for event in events) == 1
        assert engine.attributes(node)["__operator__"].inlets["value"].annotation is str
        assert engine.evaluate_node(node)[node] == "new"

        target = engine.create_node("source")
        events.clear()
        engine.add_link(node, target, "value")
        assert any(set(event) == {"links"} for event in events)
        assert all("graph" not in event for event in events)
        events.clear()
        engine.remove_link(node, target, "value")
        assert any(set(event) == {"links"} for event in events)


def test_attribute_and_script_changes_execute_effect_once() -> None:
    script = (
        'count = 0\n'
        'def source(value: int = 1):\n'
        '    global count\n'
        '    count += 1\n'
        '    return value, count\n'
    )
    with engine_for(script) as engine:
        node = engine.create_node("source")
        engine.effect(node)
        engine.effect(node)
        assert engine.evaluate_node(node)[node] == (1, 1)
        engine.update(node, value=2)
        assert engine.evaluate_node(node)[node] == (2, 2)
        engine.set_script(script + '\n# edited\n')
        assert engine.evaluate_node(node)[node] == (2, 1)
        engine.remove_effect(node)
        engine.update(node, value=3)
        assert isinstance(engine.nodes_status(node), DirtyStatus)
        assert engine.evaluate_node(node)[node] == (3, 2)


def test_link_changes_invalidate_downstream_effects() -> None:
    with engine_for('def source(): return 7\ndef target(value: int = 5): return value * 2') as engine:
        source = engine.create_node("source")
        target = engine.create_node("target")
        engine.effect(target)
        engine.add_link(source, target, "value")
        status = engine.nodes_status(target)
        assert isinstance(status, SucceededStatus) and status.value == 14
        engine.remove_link(source, target, "value")
        status = engine.nodes_status(target)
        assert isinstance(status, SucceededStatus) and status.value == 10


def test_deleting_effect_clears_runtime_state_and_notifies_removal() -> None:
    with engine_for('def source(): return 7\ndef target(value: int = 5): return value') as engine:
        source = engine.create_node("source")
        target = engine.create_node("target")
        engine.add_link(source, target, "value")
        engine.effect(source)
        engine.effect(target)
        engine.evaluate_node(target)
        events: list[EagerEngineChange] = []
        engine.listen(events.append)
        engine.delete(source)
        assert source not in engine.nodes()
        status = engine.nodes_status(target)
        assert isinstance(status, SucceededStatus) and status.value == 5
        assert any(source in event.get("nodes_status", {}).get("removed", {}) for event in events)
        assert source not in engine._executor._nodes_status
        assert source not in engine._executor._cache
        assert source not in engine._executor._effects
        engine.set_script('def source(): return 9\ndef target(value: int = 6): return value')
        assert engine.evaluate_node(target)[target] == 6


def test_operator_index_tracks_operator_reassignment() -> None:
    with engine_for('def first(): return 1\ndef second(): return 2') as engine:
        node = engine.create_node("first")
        engine.effect(node)
        engine.update(node, __operator__=OperatorHandle("second"))
        assert engine.evaluate_node(node)[node] == 2
        engine.set_script('def first(): return 10\ndef second(): return 20')
        status = engine.nodes_status(node)
        assert isinstance(status, SucceededStatus) and status.value == 20


def test_dirty_listener_cannot_read_stale_cache() -> None:
    with engine_for('def source(value: int = 1): return value') as engine:
        node = engine.create_node("source")
        assert engine.evaluate_node(node)[node] == 1
        results: list[object] = []

        def on_change(change: EagerEngineChange) -> None:
            update = change.get("nodes_status", {}).get("updated", {}).get(node)
            if update is not None and isinstance(update["new"], DirtyStatus):
                results.append(engine.evaluate_node(node)[node])

        engine.listen(on_change)
        engine.update(node, value=2)
        assert results == [2]


def test_provider_and_operator_failures_still_reach_facade() -> None:
    with engine_for('def source(): raise ValueError("broken")') as engine:
        node = engine.create_node("source")
        assert engine.evaluate_node(node) == {}
        assert isinstance(engine.nodes_status(node), FailedStatus)
        events: list[EagerEngineChange] = []
        engine.listen(events.append)
        engine.set_script('def source(:')
        assert list(engine.operators()) == []
        assert any(
            isinstance(event["provider_status"]["new"], FailedStatus)
            for event in events if "provider_status" in event
        )
        engine.set_script('def source(): return 8')
        assert engine.evaluate_node(node)[node] == 8


def test_close_unsubscribes_facade_and_executor_idempotently() -> None:
    with engine_for('def source(): return 1') as engine:
        events: list[EagerEngineChange] = []
        engine.listen(events.append)
        node = engine.create_node("source")
        engine.evaluate_node(node)
        events.clear()
        engine.close()
        engine.close()
        engine.update(node, extra=2)
        engine.set_script('def source(): return 3')
        assert events == []
        assert engine._graph_config._listeners == []
        assert engine._script_config._listeners == []
        assert engine._executor._listeners == []
