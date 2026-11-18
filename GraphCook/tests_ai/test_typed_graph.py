"""Typed payload storage must not change graph connectivity or traversal."""

from types import MappingProxyType
from typing import TypedDict
from typing_extensions import assert_type

import pytest

from graphcook.core.graph import (
    Graph, GraphProtocol, Link, MutableGraphProtocol,
    ancestors, descendants, topological_sort,
)
from graphcook.observable_graph import GraphChange, ObservableGraph


class NodeData(TypedDict):
    label: str
    inputs: dict[str, object]


def test_typed_dictionary_is_stored_and_returned_without_wrapping() -> None:
    graph = Graph[str, NodeData]()
    data: NodeData = {"label": "Source", "inputs": {"value": 3}}
    graph.add_node("source", data)
    reader: GraphProtocol[str, NodeData] = graph
    writer: MutableGraphProtocol[str, NodeData] = graph
    assert_type(reader.attributes("source"), NodeData)
    assert graph.attributes("source") is data

    replacement: NodeData = {"label": "Renamed", "inputs": {}}
    writer.set_attributes("source", replacement)
    assert graph.attributes("source") is replacement
    assert data["label"] == "Source"


def test_replacing_data_preserves_all_connections() -> None:
    graph = Graph[str, NodeData]()
    for node in ("source", "middle", "target"):
        graph.add_node(node, {"label": node, "inputs": {}})
    graph.add_link("source", "middle", "value")
    graph.add_link("middle", "target", "value")
    before = tuple(graph.links())

    graph.set_attributes("middle", {"label": "New", "inputs": {"value": 5}})
    assert tuple(graph.links()) == before
    assert ancestors(graph, "target") == {"source", "middle"}
    assert descendants(graph, "source") == {"middle", "target"}
    assert topological_sort(graph) == ("source", "middle", "target")

    graph.remove_node("middle")
    assert graph.nodes() == ("source", "target")
    assert tuple(graph.links()) == ()


@pytest.mark.parametrize("data", [None, 0, False, "", [], MappingProxyType({})])
def test_non_dictionary_data_is_rejected_without_mutation(data: object) -> None:
    graph = ObservableGraph[str]()
    graph.add_node("existing", label="Original")
    events: list[GraphChange[str]] = []
    graph.listen(events.append)
    with pytest.raises(TypeError, match="dictionary"):
        graph.add_node("new", data)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="dictionary"):
        graph.set_attributes("existing", data)  # type: ignore[arg-type]
    assert graph.nodes() == ("existing",)
    assert graph.attributes("existing") == {"label": "Original"}
    assert events == []


def test_default_dictionary_api_and_keyword_names_are_preserved() -> None:
    graph = Graph[str]()
    graph.add_node("empty")
    graph.add_node("keywords", data=1, key=2, value=3)
    empty: dict[str, object] = {}
    graph.add_node("explicit", empty)
    assert graph.attributes("empty") == {}
    assert graph.attributes("explicit") is empty
    graph.set("keywords", data=4, key=5, value=6)
    graph.set("keywords", "optional", None)
    graph.unset("keywords", "key")
    assert graph.attributes("keywords") == {"data": 4, "value": 6, "optional": None}


def test_invalid_operations_preserve_existing_nodes_and_links() -> None:
    graph = Graph[str]()
    graph.add_node("source", value=1)
    graph.add_node("target", value=2)
    graph.add_link("source", "target", "value")

    with pytest.raises(ValueError, match="already exists"):
        graph.add_node("source", value=99)
    with pytest.raises(KeyError):
        graph.set_attributes("missing", {"value": 3})
    with pytest.raises(KeyError):
        graph.attributes("missing")
    with pytest.raises(ValueError, match="already connected"):
        graph.add_link("source", "target", "value")

    assert graph.nodes() == ("source", "target")
    assert graph.attributes("source") == {"value": 1}
    assert tuple(graph.links()) == (Link("source", "target", "value"),)


def test_observable_dictionary_api_still_emits_attribute_deltas() -> None:
    graph = ObservableGraph[str]()
    graph.add_node("node", label="Old", removable=1)
    events: list[GraphChange[str]] = []
    graph.listen(events.append)

    graph.set("node", label="New", added=2)
    change = events[-1].attributes["node"]
    assert change.updated["label"].old == "Old"
    assert change.updated["label"].new == "New"
    assert change.added == {"added": 2}

    graph.unset("node", "removable")
    assert events[-1].attributes["node"].removed == {"removable": 1}

    replacement: dict[str, object] = {"label": "Replacement", "fresh": 3}
    graph.set_attributes("node", replacement)
    assert graph.attributes("node") is replacement
    change = events[-1].attributes["node"]
    assert change.removed == {"added": 2}
    assert change.added == {"fresh": 3}
    assert change.updated["label"].old == "New"
    assert change.updated["label"].new == "Replacement"
    assert len(events) == 3


def test_observable_graph_accepts_explicit_dictionary_data() -> None:
    graph = ObservableGraph[str]()
    data: dict[str, object] = {"label": "Node"}
    graph.add_node("node", data)
    assert graph.attributes("node") is data
    with pytest.raises(TypeError):
        graph.add_node("other", data, label="Ambiguous")
    assert graph.nodes() == ("node",)


def test_typed_observable_edits_preserve_identity_and_notify_after_mutation() -> None:
    graph = ObservableGraph[str, NodeData]()
    data: NodeData = {"label": "Before", "inputs": {}}
    graph.add_node("node", data)
    events: list[GraphChange[str]] = []
    snapshots: list[dict[str, object]] = []

    def on_change(event: GraphChange[str]) -> None:
        events.append(event)
        snapshots.append(dict(graph.attributes("node")))

    graph.listen(on_change)
    graph.set("node", "label", "After")
    graph.set("node", "optional", None)
    graph.unset("node", "optional")
    assert graph.attributes("node") is data
    assert len(events) == 3
    change = events[0].attributes["node"].updated["label"]
    assert (change.old, change.new) == ("Before", "After")
    assert snapshots[0]["label"] == "After"
    assert events[1].attributes["node"].added == {"optional": None}
    assert "optional" in snapshots[1]
    assert events[2].attributes["node"].removed == {"optional": None}
    assert "optional" not in snapshots[2]


@pytest.mark.parametrize("args, keywords", [
    (("label",), {}),
    (("label", "new", "extra"), {}),
    ((1, "new"), {}),
    (("label", "new"), {"other": 1}),
])
def test_invalid_attribute_edits_do_not_mutate_or_notify(
    args: tuple[object, ...], keywords: dict[str, object],
) -> None:
    graph = ObservableGraph[str]()
    graph.add_node("node", label="Before")
    events: list[GraphChange[str]] = []
    graph.listen(events.append)
    with pytest.raises(TypeError):
        graph.set("node", *args, **keywords)
    with pytest.raises(KeyError):
        graph.unset("node", "missing")
    with pytest.raises(KeyError):
        graph.set("missing", label="New")
    assert graph.attributes("node") == {"label": "Before"}
    assert events == []
