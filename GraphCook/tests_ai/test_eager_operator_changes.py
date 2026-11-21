"""Regression checks for operator notifications and script-driven evaluation."""

import pytest

from graphcook.eager_engine import (
    EagerEngine,
    EagerEngineChange,
    EagerScriptProvider,
    FailedStatus,
    OperatorChanges,
    OperatorHandle,
    EagerProviderChange,
    ProviderFailedStatus,
    ProviderSucceededStatus,
    SucceededStatus,
)


def test_provider_reports_membership_and_implementation_changes() -> None:
    provider = EagerScriptProvider(
        "def source(): return 1\ndef removed(): return 2"
    )
    events: list[EagerProviderChange] = []
    provider.listen(events.append)

    provider.set_script("def source(): return 3\ndef added(): return 4")

    assert len(events) == 1
    assert events[0].operators == OperatorChanges(
        added=frozenset({OperatorHandle("added")}),
        removed=frozenset({OperatorHandle("removed")}),
        updated=frozenset({OperatorHandle("source")}),
    )
    assert isinstance(events[0].status, ProviderSucceededStatus)


def test_script_edit_evaluates_effect_and_dependencies_once() -> None:
    engine = EagerEngine(
        "def source(): return 1\ndef target(value): return value * 2"
    )
    try:
        source = engine.create_node("source")
        target = engine.create_node("target", value=source)
        engine.effect(target)
        engine.evaluate_node(target)
        events: list[EagerEngineChange] = []
        engine.listen(events.append)

        script = "def source(): return 3\ndef target(value): return value * 2"
        engine.set_script(script)

        successes = [
            (node, update.new.value)
            for event in events if event.graph is not None
            for node, attributes in event.graph.attributes.items()
            if (update := attributes.updated.get("status")) is not None
            and isinstance(update.new, SucceededStatus)
        ]
        assert successes == [(source, 3), (target, 6)]
        assert any(event.script is not None and event.script.new == script for event in events)

        events.clear()
        engine.set_script(script)
        assert events == []
    finally:
        engine.close()


@pytest.mark.parametrize("script", ["", "def source(:", "raise ValueError('broken')"])
def test_removed_operator_invalidates_cached_effect_and_recovers(script: str) -> None:
    engine = EagerEngine("def source(): return 1")
    try:
        source = engine.create_node("source")
        engine.effect(source)
        engine.evaluate_node(source)
        events: list[EagerEngineChange] = []
        engine.listen(events.append)

        engine.set_script(script)

        provider_events = [event.provider for event in events if event.provider is not None]
        assert len(provider_events) == 1
        assert provider_events[0].operators.removed == frozenset({OperatorHandle("source")})
        if script:
            assert isinstance(provider_events[0].status, ProviderFailedStatus)
        assert isinstance(engine.attributes(source)["__status__"], FailedStatus)

        events.clear()
        engine.set_script("def source(): return 9")

        provider_events = [event.provider for event in events if event.provider is not None]
        assert provider_events[0].operators.added == frozenset({OperatorHandle("source")})
        status = engine.attributes(source)["__status__"]
        assert isinstance(status, SucceededStatus)
        assert status.value == 9
    finally:
        engine.close()
