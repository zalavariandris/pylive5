"""Contextual activity reflects computation, with safe execution lifetimes."""

from collections.abc import Callable

import pytest
from qtpy.QtCore import QCoreApplication

from pygraphrt2 import Engine, Graph, NodeRef, contextual
from pygraphrt2.execution_plan import (
    ContextKey, NodeExecutionError, NodeOutput, NodeStateSnapshot, execute,
)
from PyGraphRT2.tests_ai.controlled_backend import ControlledBackend


def test_contextual_notifications_skip_both_caches_and_use_current_callback() -> None:
    events: list[tuple[ContextKey, bool]] = []
    calls: list[int] = []

    def source() -> Callable[[int], None]:
        @contextual
        def compute(frame: int) -> None:
            calls.append(frame)
        return compute

    def render(video: Callable[[int], None], frame: int) -> tuple[None, None]:
        return video(frame), video(frame)

    def report(key: ContextKey, running: bool) -> None:
        events.append((key, running))

    render_plan = {
        "render": NodeStateSnapshot(render, [NodeOutput("source"), 1]),
    }
    result = execute(
        {"source": NodeStateSnapshot(source), **render_plan},
        on_context_state_changed=report,
    )
    assert events == [(("source", 1), True), (("source", 1), False)]
    assert calls == [1]
    assert result.outputs["render"] == (None, None)

    events.clear()
    execute(
        render_plan,
        initial_outputs={"source": result.outputs["source"]},
        initial_contextual_outputs=result.contextual_outputs,
        on_context_state_changed=report,
    )
    assert calls == [1]
    assert events == []

    new_events: list[tuple[ContextKey, bool]] = []
    execute(
        {"render": NodeStateSnapshot(render, [NodeOutput("source"), 2])},
        initial_outputs={"source": result.outputs["source"]},
        initial_contextual_outputs=result.contextual_outputs,
        on_context_state_changed=lambda key, running: new_events.append((key, running)),
    )
    assert calls == [1, 2]
    assert events == []
    assert new_events == [(("source", 2), True), (("source", 2), False)]


def test_contextual_failure_finishes_nested_calls_and_restores_runtime() -> None:
    events: list[tuple[ContextKey, bool]] = []

    def source() -> Callable[[int], int]:
        @contextual
        def compute(frame: int) -> int:
            raise ValueError("bad frame")
        return compute

    def blur(video: Callable[[int], int]) -> Callable[[int], int]:
        @contextual
        def compute(frame: int) -> int:
            return video(frame)
        return compute

    outputs = execute({
        "source": NodeStateSnapshot(source),
        "blur": NodeStateSnapshot(blur, [NodeOutput("source")]),
    }).outputs
    with pytest.raises(NodeExecutionError) as failure:
        execute(
            {"render": NodeStateSnapshot(lambda video: video(3), [NodeOutput("blur")])},
            initial_outputs=outputs,
            on_context_state_changed=lambda key, running: events.append((key, running)),
        )
    assert failure.value.node_name == "source"
    assert isinstance(failure.value.error, ValueError)
    assert events == [
        (("blur", 3), True), (("source", 3), True),
        (("source", 3), False), (("blur", 3), False),
    ]
    with pytest.raises(RuntimeError, match="active execution"):
        outputs["blur"](3)


@pytest.mark.parametrize("action", ["edit", "close"])
def test_contextual_activity_counts_nested_calls_and_ignores_stale_events(
    qapp: object, action: str,
) -> None:
    graph = Graph()
    backend = ControlledBackend(graph)
    engine = Engine(graph=graph, backend=backend)
    engine.set_auto_execute(False)
    source = engine.add_node(lambda: None, name="source")
    target = engine.add_node(lambda value: value, args=(source,), name="target")
    engine._cache.save(source, None)
    notifications: list[frozenset[NodeRef]] = []
    engine.execution_pending_changed.connect(lambda: notifications.append(engine.pending_nodes()))
    try:
        engine.execute_nodes(target)
        notify = backend.context_callbacks[-1]
        assert notify is not None
        notify((source.name(), 1), True)
        notify((source.name(), 2), True)
        notify((source.name(), 2), False)
        QCoreApplication.processEvents()
        assert source in engine.pending_nodes()
        notify((source.name(), 1), False)
        QCoreApplication.processEvents()
        assert source not in engine.pending_nodes()

        notify((source.name(), 3), True)
        QCoreApplication.processEvents()
        assert source in engine.pending_nodes()
        # These events are queued before invalidation but delivered afterward.
        notify((source.name(), 3), False)
        notify((source.name(), 4), True)
        if action == "close":
            engine.close()
        else:
            graph._update_node(target, lambda value: value, args=(source,))
        assert not engine.pending_nodes()
        notifications.clear()
        QCoreApplication.processEvents()
        assert not engine.pending_nodes()
        assert notifications == []

        if action == "edit":
            engine.execute_nodes(target)
            current_notify = backend.context_callbacks[-1]
            assert current_notify is not None
            current_notify((source.name(), 5), True)
            notify((source.name(), 4), False)
            QCoreApplication.processEvents()
            assert source in engine.pending_nodes()
            current_notify((source.name(), 5), False)
            QCoreApplication.processEvents()
            assert source not in engine.pending_nodes()
    finally:
        engine.close()
