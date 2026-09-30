"""Outgoing connections stay synchronized with stored node inputs."""

import pytest

from pygraphrt import GraphDefinitionRT, NodeRef


def test_create_and_update_connections_preserve_consumers() -> None:
    graph = GraphDefinitionRT()
    first = graph._create_node()
    second = graph._create_node()
    target = graph._create_node(args=(first, first), kwargs={"other": first})
    consumer = graph._create_node(args=(target,))

    assert graph._out_links[first] == {target: {0, 1, "other"}}
    assert graph.successors(first) == {target}

    target.set_inputs(second, other=first)
    assert graph._out_links[first] == {target: {"other"}}
    assert graph._out_links[second] == {target: {0}}
    assert graph._out_links[target] == {consumer: {0}}

    target.set_inputs(42)
    assert graph._out_links[first] == {}
    assert graph._out_links[second] == {}
    assert graph._out_links[target] == {consumer: {0}}
    assert graph._out_links[consumer] == {}


def test_delete_reindexes_remaining_inlets_before_notifications() -> None:
    graph = GraphDefinitionRT()
    upstream = graph._create_node()
    removed = graph._create_node(args=(upstream,))
    other = graph._create_node()
    target = graph._create_node(
        args=(removed, other, removed, other),
        kwargs={"gone": removed, "kept": other},
    )
    descendant = graph._create_node(args=(target,))
    events: list[tuple[str, list[NodeRef], bool, set[int | str]]] = []

    def record(event: str, nodes: list[NodeRef]) -> None:
        events.append((
            event,
            nodes,
            removed in graph.nodes(),
            graph._out_links[other][target].copy(),
        ))

    graph.nodes_removed.connect(lambda nodes: record("removed", nodes))
    graph.nodes_changed.connect(lambda nodes: record("changed", nodes))
    graph._delete_node(removed)

    args, kwargs = target.get_inputs()
    assert args == (other, other)
    assert dict(kwargs) == {"kept": other}
    assert removed not in graph._out_links
    assert graph.successors(upstream) == set()
    assert graph._out_links[other] == {target: {0, 1, "kept"}}
    assert graph.descendants(other) == {other, target, descendant}
    assert events == [
        ("removed", [removed], False, {0, 1, "kept"}),
        ("changed", [target], False, {0, 1, "kept"}),
    ]

@pytest.mark.parametrize("update", [False, True])
def test_stored_inputs_do_not_alias_caller_containers(update: bool) -> None:
    graph = GraphDefinitionRT()
    source = graph._create_node()
    other = graph._create_node()
    args = [source]
    kwargs = {"value": source}
    if update:
        target = graph._create_node()
        graph._update_node(target, args=args, kwargs=kwargs)
    else:
        target = graph._create_node(args=args, kwargs=kwargs)

    args[0] = other
    kwargs["value"] = other
    stored_args, stored_kwargs = target.get_inputs()
    assert stored_args == (source,)
    assert dict(stored_kwargs) == {"value": source}
    assert graph._out_links[source] == {target: {0, "value"}}
    assert graph.successors(other) == set()


def test_traversal_handles_diamonds_and_cycles() -> None:
    graph = GraphDefinitionRT()
    root = graph._create_node()
    left = graph._create_node(args=(root,))
    right = graph._create_node(kwargs={"value": root})
    leaf = graph._create_node(args=(left, right))
    unrelated = graph._create_node()

    graph.successors(root).clear()
    assert graph.successors(root) == {left, right}
    assert graph.descendants(root) == {root, left, right, leaf}
    assert graph.descendants(leaf) == {leaf}
    assert graph.descendants(unrelated) == {unrelated}

    root.set_inputs(leaf)
    assert graph.descendants(leaf) == {root, left, right, leaf}


def test_deleting_self_reference_and_cycle_cleans_both_directions() -> None:
    graph = GraphDefinitionRT()
    removed = graph._create_node()
    survivor = graph._create_node(args=(removed,))
    removed.set_inputs(removed, survivor)

    assert graph.successors(removed) == {removed, survivor}
    graph._delete_node(removed)
    assert graph._out_links == {survivor: {}}
    assert survivor.get_inputs() == ((), {})

    replacement = graph._create_node()
    assert replacement.get_name() == removed.get_name()
    assert graph.successors(replacement) == set()
    assert graph.descendants(replacement) == {replacement}


def test_signal_handlers_see_new_connections() -> None:
    graph = GraphDefinitionRT()
    first = graph._create_node()
    second = graph._create_node()
    snapshots: list[tuple[set[NodeRef], set[NodeRef]]] = []

    def record(nodes: list[NodeRef]) -> None:
        snapshots.append((graph.successors(first), graph.successors(second)))

    graph.nodes_added.connect(record)
    graph.nodes_changed.connect(record)
    target = graph._create_node(args=(first,))
    target.set_inputs(second)
    assert snapshots == [({target}, set()), (set(), {target})]


def test_queries_reject_deleted_nodes() -> None:
    graph = GraphDefinitionRT()
    node = graph._create_node()
    graph._delete_node(node)
    with pytest.raises(KeyError):
        graph.successors(node)
    with pytest.raises(KeyError):
        graph.descendants(node)
