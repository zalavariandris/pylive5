# REVIEW: OUTDATED means an obsolete expectation/setup; REMOVE is a removal
# candidate; SIMPLIFY targets unnecessary restrictions, not the core behavior.
# Unmarked tests remain useful. These comments do not alter pytest behavior.
# OUTDATED documentation below: decorators already replace values by name.
"""Decorator contract: references follow names; redefinition replaces values.

These specifications intentionally require behavior beyond the current
implementation, which rejects duplicate operator names.
"""

from pygraphrt.errors import GraphExecutionError
from pygraphrt.inline_module import InlineModuleRT
import pytest
import pygraphrt as rt


# REVIEW SIMPLIFY: cache variants add no coverage to tests that never execute
# nodes. Reserve the cache matrix for execution/invalidation scenarios.
@pytest.fixture
def graph() -> rt.GraphDefinitionRT:
    graph = rt.GraphDefinitionRT()
    return graph

class Test_InlineOperatorCRUD():
    # REVIEW UNNECESSARY / REMOVE: uncollected placeholder (_test_ prefix),
    # missing arguments, and obsolete _set_operator/_delete_operator methods.
    # Working CRUD coverage exists in unit_tests/test_inline_module.
    def _test_create(self):
        im = InlineModuleRT()

        im._create_operator()
        im._update_operator()
        im._set_operator()
        im._delete_operator()


class Test_OperatorRebinding():
    # REVIEW UNNECESSARY / REMOVE: reference equality is also asserted by
    # test_op_redefinition_rebinds_existing_references_without_creating_nodes.
    def test_rebind(self, graph: rt.GraphDefinitionRT) -> None:
        @graph.op()
        def greet() -> str:
            return "hello"

        A = greet

        @graph.op()
        def greet() -> str:
            return "goodbye"

        B = greet

        assert A==B

        

    def test_op_redefinition_updates_all_users_and_preserves_connections(
        self, graph: rt.GraphDefinitionRT,
    ) -> None:
        E = rt.GraphExecutorRT(graph)
        
        @graph.node()
        def source() -> int:
            return 3

        @graph.op()
        def transform(value: int) -> int:
            return value + 1

        saved_operator = transform
        first = graph.node(source)(transform, name="first")
        second = graph.node(value=10)(transform, name="second")

        @graph.node(first, second)
        def total(left: int, right: int) -> int:
            return left + right

        previous_nodes = graph.nodes()
        previous_operators = graph.operators()
        previous_inputs = {node: node.get_inputs() for node in previous_nodes}
        assert E.execute(total) == 15

        @graph.op()
        def transform(value: int) -> int:
            return value * 2

        assert transform == saved_operator
        assert graph.nodes() == previous_nodes
        assert graph.operators() == previous_operators
        assert {node: node.get_inputs() for node in graph.nodes()} == previous_inputs
        assert first.get_operator() == saved_operator
        assert second.get_operator() == saved_operator
        assert E.execute(first) == 6
        assert E.execute(second) == 20
        assert E.execute(total) == 26

    # fine for now.
    def test_incompatible_op_redefinition_reports_argument_error_without_rewiring(
        self, graph: rt.GraphDefinitionRT,
    ) -> None:
        E = rt.GraphExecutorRT(graph)
        @graph.op()
        def transform(value: int) -> int:
            return value + 1

        node = graph.node(value=3)(transform, name="result")
        previous_inputs = node.get_inputs()
        assert E.execute(node) == 4

        # The contract allows validation at registration or at execution.
        with pytest.raises(GraphExecutionError):
            @graph.op()
            def transform(value: int, extra: int) -> int:
                return value + extra

            E.execute(node)

        assert graph.nodes() == [node]
        assert node.get_inputs() == previous_inputs


class Test_OperatorDecorator_Creates_Behaviour():
    # REVIEW OUTDATED / REMOVE: expects a fresh reference on redefinition,
    # contradicting the implemented op() rebinding behavior and tests above.
    def test_create_operator(self, graph: rt.GraphDefinitionRT) -> None:
        @graph.op()
        def add(a: int, b: int) -> int:
            return a + b

        A = add

        @graph.op()
        def add(a: int, b: int) -> int:
            return a + b

        B = add

        assert A != B


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

    