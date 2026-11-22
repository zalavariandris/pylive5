"""Signature failures follow the same recovery path as provider execution errors."""

import pytest

from graphcook.eager_engine import (
    DirtyStatus,
    EagerEngine,
    EagerEngineChange,
    FailedStatus,
    OperatorHandle,
    SucceededStatus,
)


@pytest.mark.parametrize("effect", [False, True])
@pytest.mark.parametrize(
    ("script", "error_type"),
    [
        ('def source(value: Missing = 2): return value', NameError),
        ('def source(value=2): return value\nsource.__signature__ = "invalid"', (TypeError, ValueError)),
    ],
)
def test_signature_failure_clears_stale_state_and_recovers(
    script: str, error_type: type[Exception] | tuple[type[Exception], ...], effect: bool,
) -> None:
    engine = EagerEngine('def source(value: int = 1): return value')
    handle = OperatorHandle("source")
    try:
        node = engine.create_node("source")
        if effect:
            engine.effect(node)
        assert engine.evaluate_node(node)[node] == 1
        events: list[EagerEngineChange] = []
        engine.listen(events.append)

        engine.set_script(script)

        assert engine.script() == script
        assert list(engine.operators()) == []
        assert engine.operator_signature(handle) is None
        provider_events = [event for event in events if "provider_status" in event]
        assert len(provider_events) == 1
        failure = provider_events[0]["provider_status"]["new"]
        assert isinstance(failure, FailedStatus)
        assert isinstance(failure.reason, error_type)
        assert set(provider_events[0]["operators"]["removed"]) == {handle}
        assert any(event.get("script", {}).get("new") == script for event in events)
        assert isinstance(engine.nodes_status(node), FailedStatus if effect else DirtyStatus)
        # A previously cached success must not survive the failed provider update.
        assert engine.evaluate_node(node) == {}
        assert isinstance(engine.nodes_status(node), FailedStatus)

        events.clear()
        engine.set_script('def source(value: int = 9): return value')

        assert list(engine.operators()) == [handle]
        signature = engine.operator_signature(handle)
        assert signature is not None
        assert signature.inlets["value"].default == 9
        assert engine.evaluate_node(node)[node] == 9
        provider_events = [event for event in events if "provider_status" in event]
        assert len(provider_events) == 1
        assert isinstance(provider_events[0]["provider_status"]["old"], FailedStatus)
        assert isinstance(provider_events[0]["provider_status"]["new"], SucceededStatus)
        assert set(provider_events[0]["operators"]["added"]) == {handle}
    finally:
        engine.close()


def test_initial_signature_failure_does_not_expose_partial_operator_list() -> None:
    engine = EagerEngine(
        'def valid(): return 1\n'
        'def invalid(value: Missing): return value'
    )
    try:
        assert list(engine.operators()) == []
        assert engine.operator_signature(OperatorHandle("valid")) is None
        assert engine.operator_signature(OperatorHandle("invalid")) is None
        engine.set_script('def valid(): return 2')
        node = engine.create_node("valid")
        assert engine.evaluate_node(node)[node] == 2
    finally:
        engine.close()
