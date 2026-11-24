"""Single-attribute assignment and bulk updates share observable semantics."""

import pytest

from graphcook.core.graph import Graph
from graphcook.eager_observable_engine import EagerEngine
from graphcook.observable_graph import GraphChange, ObservableGraph


@pytest.mark.parametrize("graph_type", [Graph, ObservableGraph])
def test_set_and_update_preserve_other_attributes_and_links(
    graph_type: type[Graph[str]],
) -> None:
    graph = graph_type()
    graph.add_node("source")
    graph.add_node("target", greeting="Hello", untouched=42)
    graph.add_link("source", "target", "name")
    attributes = graph.attributes("target")
    links = tuple(graph.links())

    graph.set("target", "greeting", "Hey")
    graph.set("target", "optional", None)
    graph.update("target", greeting="Hi", enabled=False)

    assert attributes == {
        "greeting": "Hi", "untouched": 42, "optional": None, "enabled": False,
    }
    assert tuple(graph.links()) == links
    graph.unset("target", "optional")
    assert "optional" not in attributes


@pytest.mark.parametrize("graph_type", [Graph, ObservableGraph])
def test_attribute_names_do_not_collide_with_update_parameters(
    graph_type: type[Graph[str]],
) -> None:
    graph = graph_type()
    graph.add_node("target")
    graph.set("target", "node", "first")
    graph.update("target", node="second", name="label", value=None)
    assert graph.attributes("target") == {
        "node": "second", "name": "label", "value": None,
    }


def test_observers_receive_one_delta_after_each_mutation() -> None:
    graph = ObservableGraph[str]()
    graph.add_node("target", greeting="Hello")
    events: list[GraphChange[str]] = []
    snapshots: list[dict[str, object]] = []

    def observe(change: GraphChange[str]) -> None:
        events.append(change)
        snapshots.append(dict(graph.attributes("target")))

    graph.listen(observe)
    graph.set("target", "greeting", "Hey")
    graph.set("target", "optional", None)
    graph.update("target", greeting="Hi", enabled=False)

    assert len(events) == 3
    deltas = [event["nodes"]["updated"]["target"] for event in events]
    assert deltas[0]["updated"] == {
        "greeting": {"kind": "value", "old": "Hello", "new": "Hey"},
    }
    assert deltas[1]["added"] == {"optional": None}
    assert deltas[2]["updated"] == {
        "greeting": {"kind": "value", "old": "Hey", "new": "Hi"},
    }
    assert deltas[2]["added"] == {"enabled": False}
    assert snapshots == [
        {"greeting": "Hey"},
        {"greeting": "Hey", "optional": None},
        {"greeting": "Hi", "optional": None, "enabled": False},
    ]

    graph.update("target")
    assert len(events) == 3


def test_missing_nodes_and_invalid_calls_do_not_notify_or_mutate() -> None:
    graph = ObservableGraph[str]()
    graph.add_node("target", greeting="Hello")
    events: list[GraphChange[str]] = []
    graph.listen(events.append)

    with pytest.raises(KeyError):
        graph.set("missing", "greeting", "Hey")
    with pytest.raises(KeyError):
        graph.update("missing", greeting="Hey")
    with pytest.raises(TypeError):
        graph.set("target", greeting="Hey")  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        graph.set("target", 123, "Hey")  # type: ignore[arg-type]

    assert events == []
    assert graph.attributes("target") == {"greeting": "Hello"}


def test_engine_set_and_update_invalidate_cached_outputs() -> None:
    engine = EagerEngine(
        'def greet(greeting="Hello", name="Ada"): return f"{greeting}, {name}!"'
    )
    try:
        node = engine.create_node("greet")
        assert engine.evaluate_node(node)[node] == "Hello, Ada!"
        engine.set(node, "greeting", "Hey")
        assert engine.evaluate_node(node)[node] == "Hey, Ada!"
        engine.update(node, greeting="Hi", name="Grace")
        assert engine.evaluate_node(node)[node] == "Hi, Grace!"
    finally:
        engine.close()
