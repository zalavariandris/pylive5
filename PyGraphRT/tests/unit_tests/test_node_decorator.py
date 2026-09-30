# REVIEW: OUTDATED means an obsolete expectation/setup; REMOVE is a removal
# candidate; SIMPLIFY targets unnecessary restrictions, not the core behavior.
# Unmarked tests remain useful. These comments do not alter pytest behavior.
# OUTDATED documentation below: decorators already replace values by name.
"""Decorator contract: references follow names; redefinition replaces values.

These specifications intentionally require behavior beyond the current
implementation, which rejects duplicate operator names.
"""

import pytest
import pygraphrt as rt


# REVIEW SIMPLIFY: cache variants add no coverage to tests that never execute
# nodes. Reserve the cache matrix for execution/invalidation scenarios.
@pytest.fixture
def graph() -> rt.GraphDefinitionRT:
    graph = rt.GraphDefinitionRT()
    return graph

@pytest.mark.xfail(
    strict=True,
    raises=(AssertionError, AttributeError),
    reason="Rebinding nodes is not supported, currently @node creates new nodes instead",
)
class Test_NodeDecorator_Rebind_Behaviour():
    """node decorator behaves as a dictionary set_item"""
    # REVIEW UNNECESSARY / REMOVE: equality is covered by the next test, which
    # also verifies that saved references execute the updated function.
    def test_node_equality(self, graph: rt.GraphDefinitionRT) -> None:
        @graph.node()
        def hello() -> int:
            return "hello"

        A = hello

        @graph.node()
        def hello() -> int:
            return "hello"

        B = hello

        assert A == B


    def test_node_redefinition_without_inputs_removes_old_connections(
        self, graph: rt.GraphDefinitionRT,
    ) -> None:
        E = rt.GraphExecutorRT(graph)
        @graph.node()
        def source() -> int:
            return 2

        @graph.node(source, extra=source)
        def result(value: int, extra: int) -> int:
            return value + extra

        saved_ref = result
        assert E.execute(saved_ref) == 4

        @graph.node()
        def result() -> int:
            return 42

        assert result == saved_ref
        assert saved_ref.get_inputs() == ((), {})
        assert graph.ancestors(saved_ref) == {saved_ref}
        assert set(graph.nodes()) == {source, saved_ref}
        assert E.execute(saved_ref) == 42


    def test_existing_dependents_follow_a_redefined_node(self, graph: rt.GraphDefinitionRT) -> None:
        E = rt.GraphExecutorRT(graph)
        @graph.node()
        def source() -> int:
            return 2

        @graph.node(source, right=source)
        def result(left: int, right: int) -> int:
            return left + right

        previous_inputs = result.get_inputs()
        assert E.execute(result) == 4

        @graph.node()
        def source() -> int:
            return 5

        assert result.get_inputs() == previous_inputs
        assert graph.ancestors(result) == {source, result}
        assert set(graph.nodes()) == {source, result}
        assert E.execute(result) == 10

    def test_operator_ref_node_rebinds_by_name(self, graph: rt.GraphDefinitionRT) -> None:
        E = rt.GraphExecutorRT(graph)
        @graph.op()
        def double(value: int) -> int:
            return value * 2

        first_node = graph.node(value=3)(double)
        assert E.execute(first_node) == 6

        second_node = graph.node(value=10)(double)

        assert first_node == second_node
        assert first_node.get_name() == "double"
        assert graph.nodes() == [first_node]
        assert graph.operators() == [double]
        assert first_node.get_operator() == double
        assert first_node.get_inputs() == ((), {"value": 10})
        assert E.execute(first_node) == 20
        assert E.execute(second_node) == 20


class Test_NodeDecorator_Creates_Behaviour():
    """node decorator behaves as a list add_item"""
    # REVIEW OUTDATED / REMOVE: node() rebinds by name, so A and B are equal.
    # _create_node() is the separate API for allocating distinct nodes.
    def test_unique_nodes(self, graph: rt.GraphDefinitionRT) -> None:
        @graph.node()
        def hello() -> int:
            return "hello"

        A = hello

        @graph.node()
        def hello() -> int:
            return "hello"

        B = hello

        assert A != B
        assert len(graph.nodes()) == 2
        assert set(graph.nodes()) == {A, B}

    