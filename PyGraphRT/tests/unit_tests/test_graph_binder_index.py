"""Relationship queries stay current without resolving operator references."""

import pytest

import pygraphrt as rt


@pytest.mark.parametrize("create_before_binder", [True, False])
def test_tracks_existing_and_new_nodes(create_before_binder: bool) -> None:
    graph = rt.GraphDefinitionRT()
    module = rt.ScriptModuleRT()
    operator = rt.OperatorRef(module, "missing")
    if create_before_binder:
        node = graph._create_node(operator)
    binder = rt._GraphModuleMapper(graph)
    if not create_before_binder:
        node = graph._create_node(operator)

    assert binder.operator_for_node(node) == operator
    assert binder.nodes_for_operator(operator) == {node}
    assert binder.nodes_for_module(module) == {node}


def test_rebinding_and_deletion_preserve_other_users() -> None:
    graph = rt.GraphDefinitionRT()
    binder = rt._GraphModuleMapper(graph)
    module = rt.ScriptModuleRT()
    other_module = rt.ScriptModuleRT()
    old_operator = rt.OperatorRef(module, "missing")
    new_operator = rt.OperatorRef(other_module, "missing")
    first = graph._create_node(old_operator)
    second = graph._create_node(old_operator)

    graph._update_node(first, new_operator)
    assert binder.operator_for_node(first) == new_operator
    assert binder.nodes_for_operator(old_operator) == {second}
    assert binder.nodes_for_operator(new_operator) == {first}
    assert binder.nodes_for_module(module) == {second}
    assert binder.nodes_for_module(other_module) == {first}

    graph._delete_node(first)
    assert binder.operator_for_node(first) is None
    assert binder.nodes_for_operator(new_operator) == set()
    assert binder.nodes_for_module(other_module) == set()
    assert binder.nodes_for_operator(old_operator) == {second}


def test_input_changes_preserve_bindings() -> None:
    graph = rt.GraphDefinitionRT()
    binder = rt._GraphModuleMapper(graph)
    operator = rt.OperatorRef(graph.inline(), "missing")
    source = graph._create_node(operator)
    dependent = graph._create_node(operator, args=(source,))

    dependent.set_inputs(source, 42)
    assert binder.nodes_for_operator(operator) == {source, dependent}
    graph._delete_node(source)
    assert binder.operator_for_node(dependent) == operator
    assert binder.nodes_for_operator(operator) == {dependent}


def test_operatorless_node_can_be_bound_and_removed() -> None:
    graph = rt.GraphDefinitionRT()
    binder = rt._GraphModuleMapper(graph)
    node = graph._create_node()
    assert binder.operator_for_node(node) is None
    graph._delete_node(node)
    assert binder.operator_for_node(node) is None

    node = graph._create_node()
    operator = rt.OperatorRef(graph.inline(), "missing")
    graph._update_node(node, operator)
    assert binder.operator_for_node(node) == operator
    assert binder.nodes_for_operator(operator) == {node}


def test_queries_return_independent_sets() -> None:
    graph = rt.GraphDefinitionRT()
    binder = rt._GraphModuleMapper(graph)
    operator = rt.OperatorRef(graph.inline(), "first")
    other_operator = rt.OperatorRef(graph.inline(), "second")
    first = graph._create_node(operator)
    second = graph._create_node(other_operator)

    operators = [operator, other_operator, operator]
    assert binder.nodes_for_operators(iter(operators)) == {first, second}
    binder.nodes_for_operator(operator).clear()
    binder.nodes_for_operators(operators).clear()
    binder.nodes_for_module(graph.inline()).clear()
    assert binder.nodes_for_operator(operator) == {first}
    assert binder.nodes_for_module(graph.inline()) == {first, second}
    assert binder.nodes_for_operators([]) == set()
    assert binder.nodes_for_operator(rt.OperatorRef(graph.inline(), "unused")) == set()
    assert binder.nodes_for_module(rt.ScriptModuleRT()) == set()
