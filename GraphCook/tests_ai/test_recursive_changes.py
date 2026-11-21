"""Tagged patches and graph notifications can update an independent replica."""

import pytest

from graphcook.core.changes import Change, ObservableValue, ValueChange, apply_change
from graphcook.eager_engine import EagerEngine, EagerEngineChange
from graphcook.graph_index import GraphAttributeIndex
from graphcook.observable_graph import GraphChange, ObservableGraph


def test_nested_value_set_and_mapping_updates_leave_input_unchanged() -> None:
    original = {
        "node": {"greeting": "Hello", "tags": {"old"}, "obsolete": None},
        "untouched": [1, 2],
    }
    change: Change = {
        "kind": "map",
        "updated": {
            "node": {
                "kind": "map",
                "added": {"enabled": False},
                "removed": {"obsolete": None},
                "updated": {
                    "greeting": {"kind": "value", "old": "Hello", "new": "Hey"},
                    "tags": {"kind": "set", "removed": {"old"}, "added": {"new"}},
                },
            },
        },
    }
    result = apply_change(original, change)
    assert result == {
        "node": {"greeting": "Hey", "tags": {"new"}, "enabled": False},
        "untouched": [1, 2],
    }
    assert original["node"] == {"greeting": "Hello", "tags": {"old"}, "obsolete": None}


@pytest.mark.parametrize(
    ("target", "change", "error"),
    [
        (1, {"kind": "map"}, TypeError),
        ({}, {"kind": "set"}, TypeError),
        ({"a": 1}, {"kind": "map", "added": {"a": 2}}, ValueError),
        ({}, {"kind": "map", "removed": {"a": 1}}, KeyError),
        ({}, {"kind": "map", "updated": {"a": {"kind": "value", "old": 1, "new": 2}}}, KeyError),
        ({"a": 1}, {"kind": "map", "removed": {"a": 1}, "updated": {"a": {"kind": "value", "old": 1, "new": 2}}}, ValueError),
        ({1}, {"kind": "set", "added": {1}}, ValueError),
        ({1}, {"kind": "set", "removed": {2}}, ValueError),
        ({1}, {"kind": "set", "added": {1}, "removed": {1}}, ValueError),
    ],
)
def test_invalid_patch_is_rejected(target: object, change: Change, error: type[Exception]) -> None:
    with pytest.raises(error):
        apply_change(target, change)


def test_failed_nested_patch_does_not_partially_mutate_input() -> None:
    target = {"a": {"x": 1}, "b": 2}
    with pytest.raises(TypeError):
        apply_change(target, {
            "kind": "map",
            "updated": {
                "a": {"kind": "map", "removed": {"x": 1}},
                "b": {"kind": "set", "added": {3}},
            },
        })
    assert target == {"a": {"x": 1}, "b": 2}


def test_empty_tagged_changes_and_none_replacement() -> None:
    assert apply_change({"a": 1}, {"kind": "map"}) == {"a": 1}
    assert apply_change(frozenset({1}), {"kind": "set"}) == frozenset({1})
    value = ObservableValue[str | None]("before")
    events: list[ValueChange[str | None]] = []
    value.listen(events.append)
    value.set(None)
    assert events == [{"kind": "value", "old": "before", "new": None}]
    assert apply_change("before", events[0]) is None


def test_graph_events_replay_membership_attributes_and_links() -> None:
    graph = ObservableGraph[str]()
    events: list[GraphChange[str]] = []
    graph.listen(events.append)
    replica_nodes: object = {}
    replica_links: object = set()

    def replay() -> None:
        nonlocal replica_nodes, replica_links
        change = events[-1]
        if "nodes" in change:
            replica_nodes = apply_change(replica_nodes, change["nodes"])
        if "links" in change:
            replica_links = apply_change(replica_links, change["links"])
        assert replica_nodes == {node: dict(graph.attributes(node)) for node in graph.nodes()}
        assert replica_links == set(graph.links())

    graph.add_node("a", greeting="Hello", untouched=42)
    replay()
    graph.add_node("b")
    replay()
    graph.add_link("a", "b", "value")
    replay()
    graph.set("a", greeting="Hey", enabled=False)
    assert events[-1]["nodes"]["updated"]["a"] == {
        "kind": "map",
        "added": {"enabled": False},
        "updated": {"greeting": {"kind": "value", "old": "Hello", "new": "Hey"}},
    }
    replay()
    graph.unset("a", "greeting")
    assert events[-1]["nodes"]["updated"]["a"] == {
        "kind": "map", "removed": {"greeting": "Hey"},
    }
    replay()
    graph.remove_node("a")
    assert events[-1]["nodes"]["removed"]["a"] == {"untouched": 42, "enabled": False}
    replay()


def test_index_handles_nested_attribute_changes() -> None:
    graph = ObservableGraph[str]()
    index = GraphAttributeIndex(graph, "kind", str)
    graph.listen(index.update)
    graph.add_node("a", kind="one")
    graph.set("a", unrelated=1)
    assert index.nodes_with("one") == frozenset({"a"})
    graph.set("a", kind="two")
    assert index.nodes_with("one") == frozenset()
    assert index.nodes_with("two") == frozenset({"a"})
    graph.unset("a", "kind")
    assert index.value_of("a") is None
    graph.set("a", kind="three")
    graph.remove_node("a")
    assert index.nodes_with("three") == frozenset()
    index.update({})


def test_engine_invalidates_cache_for_nested_attribute_changes() -> None:
    engine = EagerEngine('def greet(greeting: str = "Hello"): return greeting')
    try:
        events: list[EagerEngineChange] = []
        engine.listen(events.append)
        node = engine.create_node("greet")
        assert events[0]["nodes_status"]["kind"] == "map"
        assert node in events[0]["nodes_status"]["added"]
        assert engine.evaluate_node(node)[node] == "Hello"
        engine.set(node, greeting="Hey")
        assert engine.evaluate_node(node)[node] == "Hey"
        engine.unset(node, "greeting")
        assert engine.evaluate_node(node)[node] == "Hello"
        engine.set_script('def greet(greeting: str = "Hi"): return greeting')
        assert engine.evaluate_node(node)[node] == "Hi"
        assert any(event.get("script", {}).get("kind") == "value" for event in events)
    finally:
        engine.close()
