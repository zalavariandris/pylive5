"""Exercise effect execution and the public event-based result contract."""

from collections.abc import Callable, Iterator
from textwrap import dedent

import pytest

from graphcook.eager_engine import (
    DirtyStatus,
    EagerEngine,
    EagerEngineChange,
    FailedStatus,
    NodeId,
    NodeState,
    RunningStatus,
    SucceededStatus,
)


@pytest.fixture
def make_engine() -> Iterator[Callable[[str], EagerEngine]]:
    engines: list[EagerEngine] = []

    def make(script: str) -> EagerEngine:
        engine = EagerEngine(dedent(script))
        engines.append(engine)
        return engine

    yield make
    for engine in engines:
        engine.close()


def state_events(events: list[EagerEngineChange]) -> list[tuple[NodeId, NodeState]]:
    states: list[tuple[NodeId, NodeState]] = []
    for event in events:
        if event.graph is None:
            continue
        for node, attributes in event.graph.attributes.items():
            change = attributes.changed.get("state")
            if change is not None:
                assert isinstance(change.new, (DirtyStatus, RunningStatus, SucceededStatus, FailedStatus))
                states.append((node, change.new))
    return states


def test_multiple_targets_share_dependencies_and_replay_cached_results(
    make_engine: Callable[[str], EagerEngine],
) -> None:
    engine = make_engine("""
        count = 0
        def source():
            global count
            count += 1
            return count
        def double(value): return value * 2
        def triple(value): return value * 3
    """)
    source = engine.node("source")
    left = engine.node("double", value=source)
    right = engine.node("triple")
    engine.add_link(source, right, "value")
    events: list[EagerEngineChange] = []
    engine.listen(events.append)

    engine.evaluate(left, right, left)

    assert state_events(events) == [
        (source, RunningStatus()), (source, SucceededStatus(value=1)),
        (left, RunningStatus()), (left, SucceededStatus(value=2)),
        (right, RunningStatus()), (right, SucceededStatus(value=3)),
    ]
    events.clear()
    engine.evaluate(right, left, right)
    assert state_events(events) == [
        (right, SucceededStatus(value=3)),
        (left, SucceededStatus(value=2)),
    ]
    assert "state" not in engine.attributes(left)


def test_effects_run_after_all_dirty_notifications(
    make_engine: Callable[[str], EagerEngine],
) -> None:
    engine = make_engine("""
        count = 0
        def source():
            global count
            count += 1
            return count
        def target(value): return value * 2
        def unrelated(): raise AssertionError('Unrequested node ran')
    """)
    source = engine.node("source")
    left = engine.node("target", value=source)
    right = engine.node("target", value=source)
    engine.node("unrelated")
    engine.effect(left)
    engine.effect(right)
    engine.evaluate(left, right)
    events: list[EagerEngineChange] = []
    engine.listen(events.append)

    engine.invalidate([source])

    states = state_events(events)
    assert {node for node, state in states[:3] if isinstance(state, DirtyStatus)} == {
        source, left, right,
    }
    assert states[3:] == [
        (source, RunningStatus()), (source, SucceededStatus(value=2)),
        (left, RunningStatus()), (left, SucceededStatus(value=4)),
        (right, RunningStatus()), (right, SucceededStatus(value=4)),
    ]


def test_no_effects_do_not_evaluate_and_empty_targets_are_rejected(
    make_engine: Callable[[str], EagerEngine],
) -> None:
    engine = make_engine("def source(): raise AssertionError('Should not run')")
    source = engine.node("source")
    events: list[EagerEngineChange] = []
    engine.listen(events.append)
    engine.invalidate([source])
    assert state_events(events) == [(source, DirtyStatus())]
    with pytest.raises(ValueError, match="At least one node"):
        engine.evaluate()


def test_success_result_is_cached_before_observers_are_notified(
    make_engine: Callable[[str], EagerEngine],
) -> None:
    engine = make_engine("""
        count = 0
        def source():
            global count
            count += 1
            return count
    """)
    source = engine.node("source")
    results: list[object] = []

    def request_cached_result(event: EagerEngineChange) -> None:
        for node, state in state_events([event]):
            if isinstance(state, SucceededStatus):
                results.append(state.value)
                if len(results) == 1:
                    engine.evaluate(node)

    engine.listen(request_cached_result)
    engine.evaluate(source)
    assert results == [1, 1]


def test_removed_link_does_not_use_old_node_reference(
    make_engine: Callable[[str], EagerEngine],
) -> None:
    engine = make_engine("def source(): return 7\ndef target(value=5): return value * 2")
    source = engine.node("source")
    target = engine.node("target", value=source)
    engine.effect(target)
    engine.evaluate(target)
    events: list[EagerEngineChange] = []
    engine.listen(events.append)

    engine.remove_link(source, target, "value")

    assert state_events(events)[-1] == (target, SucceededStatus(value=10))


def test_deleted_effect_is_not_evaluated_or_reported_dirty(
    make_engine: Callable[[str], EagerEngine],
) -> None:
    engine = make_engine("def source(): return 7")
    source = engine.node("source")
    engine.effect(source)
    engine.effect(source)
    events: list[EagerEngineChange] = []
    engine.listen(events.append)
    engine.delete(source)
    engine.invalidate([source])
    assert state_events(events) == []
    assert any(event.graph and source in event.graph.nodes.removed for event in events)


def test_script_edits_refresh_effects_and_invalid_edits_preserve_working_script(
    make_engine: Callable[[str], EagerEngine],
) -> None:
    original = "def source(): return 7"
    engine = make_engine(original)
    source = engine.node("source")
    engine.effect(source)
    events: list[EagerEngineChange] = []
    engine.listen(events.append)
    changed = "def source(): return 9"
    engine.set_script(changed)
    assert engine.script() == changed
    assert events[0].script is not None
    assert (events[0].script.old, events[0].script.new) == (original, changed)
    assert state_events(events) == [
        (source, DirtyStatus()), (source, RunningStatus()),
        (source, SucceededStatus(value=9)),
    ]

    for invalid, exception in [
        ("def source(:", SyntaxError),
        ("raise RuntimeError('Broken script')", RuntimeError),
    ]:
        events.clear()
        with pytest.raises(exception):
            engine.set_script(invalid)
        assert engine.script() == changed
        assert events == []
        engine.invalidate([source])
        assert state_events(events)[-1] == (source, SucceededStatus(value=9))


def test_none_is_a_successful_value_and_replays_from_cache(
    make_engine: Callable[[str], EagerEngine],
) -> None:
    engine = make_engine("def source(): return None")
    source = engine.node("source")
    events: list[EagerEngineChange] = []
    engine.listen(events.append)
    engine.evaluate(source)
    engine.evaluate(source)
    assert state_events(events) == [
        (source, RunningStatus()),
        (source, SucceededStatus(value=None)),
        (source, SucceededStatus(value=None)),
    ]


def test_operator_failure_preserves_exception_and_emits_failed_state(
    make_engine: Callable[[str], EagerEngine],
) -> None:
    engine = make_engine("def source(): raise ValueError('Operator failed')")
    source = engine.node("source")
    events: list[EagerEngineChange] = []
    engine.listen(events.append)
    with pytest.raises(ValueError, match="Operator failed") as raised:
        engine.evaluate(source)
    assert state_events(events) == [
        (source, RunningStatus()),
        (source, FailedStatus(reason=raised.value)),
    ]


def test_unrelated_unresolved_operator_does_not_block_requested_node(
    make_engine: Callable[[str], EagerEngine],
) -> None:
    engine = make_engine("def source(): return 7")
    source = engine.node("source")
    engine.node("missing_operator")
    events: list[EagerEngineChange] = []
    engine.listen(events.append)
    engine.evaluate(source)
    assert state_events(events)[-1] == (source, SucceededStatus(value=7))


@pytest.mark.parametrize("cycle", [False, True])
def test_preparation_errors_are_reported_to_requested_nodes(
    make_engine: Callable[[str], EagerEngine], cycle: bool,
) -> None:
    engine = make_engine("def target(value): return value")
    node = engine.node("target" if cycle else "missing_operator")
    if cycle:
        engine.add_link(node, node, "value")
    events: list[EagerEngineChange] = []
    engine.listen(events.append)
    with pytest.raises(ValueError) as raised:
        engine.evaluate(node)
    assert state_events(events) == [(node, FailedStatus(reason=raised.value))]
