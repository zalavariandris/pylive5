"""Decorator contract: references follow names; redefinition replaces values.

These specifications intentionally require behavior beyond the current
implementation, which rejects duplicate operator names.
"""

from pygraphrt.inline_module import InlineModuleRT
import pytest
import pygraphrt as rt


@pytest.fixture(
    params=[rt.DummyCache, rt.MemoryCache, rt.HistoryMemoryCache],
    ids=["uncached", "memory", "history"],
)
def graph(request: pytest.FixtureRequest) -> rt.GraphRT:
    graph = rt.GraphRT()
    graph.cache = request.param()
    return graph


class Test_InlineOperatorCRUD():
    def _test_create(self):
        im = InlineModuleRT()

        im._create_operator()
        im._update_operator()
        im._set_operator()
        im._delete_operator()


class Test_OperatorRebinding():
    def test_rebind(self, graph: rt.GraphRT) -> None:
        @graph.op()
        def greet() -> str:
            return "hello"

        A = greet

        @graph.op()
        def greet() -> str:
            return "goodbye"

        B = greet

        assert A==B

    def test_op_redefinition_rebinds_existing_references_without_creating_nodes(
        self,
        graph: rt.GraphRT,
    ) -> None:
        @graph.op()
        def greet() -> str:
            return "hello"

        saved_ref = greet
        previous_data = greet.get_value()
        refs = {saved_ref}
        assert previous_data is not None
        assert previous_data() == "hello"
        assert graph.nodes() == []

        @graph.op()
        def greet() -> str:
            return "goodbye"

        assert greet == saved_ref
        assert greet in refs
        assert graph.operators() == [saved_ref]
        assert graph.nodes() == []
        current_data = saved_ref.get_value()
        assert current_data is not None
        assert current_data is greet.get_value()
        assert current_data is not previous_data
        assert current_data() == "goodbye"
        assert previous_data() == "hello"

    def test_op_redefinition_updates_all_users_and_preserves_connections(
        self, graph: rt.GraphRT,
    ) -> None:
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
        assert graph.execute(total) == 15

        @graph.op()
        def transform(value: int) -> int:
            return value * 2

        assert transform == saved_operator
        assert graph.nodes() == previous_nodes
        assert graph.operators() == previous_operators
        assert {node: node.get_inputs() for node in graph.nodes()} == previous_inputs
        assert first.get_operator() == saved_operator
        assert second.get_operator() == saved_operator
        assert graph.execute(first) == 6
        assert graph.execute(second) == 20
        assert graph.execute(total) == 26

    def test_incompatible_op_redefinition_reports_argument_error_without_rewiring(
        self, graph: rt.GraphRT,
    ) -> None:
        @graph.op()
        def transform(value: int) -> int:
            return value + 1

        node = graph.node(value=3)(transform, name="result")
        previous_inputs = node.get_inputs()
        assert graph.execute(node) == 4

        # The contract allows validation at registration or at execution.
        with pytest.raises(TypeError):
            @graph.op()
            def transform(value: int, extra: int) -> int:
                return value + extra

            graph.execute(node)

        assert graph.nodes() == [node]
        assert node.get_inputs() == previous_inputs


class Test_OperatorDecorator_Creates_Behaviour():
    def test_create_operator(self, graph: rt.GraphRT) -> None:
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
    def test_node_equality(self, graph: rt.GraphRT) -> None:
        @graph.node()
        def hello() -> int:
            return "hello"

        A = hello

        @graph.node()
        def hello() -> int:
            return "hello"

        B = hello

        assert A == B

    def test_node_redefinition_rebinds_existing_references(self, graph: rt.GraphRT) -> None:
        @graph.node()
        def hello() -> str:
            return "boom"

        saved_ref = hello
        previous_data = hello.get_value()
        refs = {saved_ref}
        assert graph.execute(saved_ref) == "boom"

        @graph.node()
        def hello() -> str:
            return "boom2"

        assert hello == saved_ref
        assert hello in refs
        assert graph.nodes() == [saved_ref]
        assert saved_ref.get_value() is hello.get_value()
        assert saved_ref.get_value() is not previous_data
        assert graph.execute(saved_ref) == "boom2"
        assert graph.execute(hello) == "boom2"


    def test_node_redefinition_replaces_declared_connections(self, graph: rt.GraphRT) -> None:
        @graph.node()
        def old_source() -> int:
            return 2

        @graph.node()
        def new_source() -> int:
            return 5

        @graph.node(old_source, offset=10)
        def result(value: int, offset: int) -> int:
            return value + offset

        saved_ref = result
        previous_data = result.get_value()
        assert previous_data is not None
        assert graph.execute(result) == 12

        @graph.node(value=new_source, factor=3)
        def result(value: int, factor: int) -> int:
            return value * factor

        assert result == saved_ref
        assert saved_ref.get_inputs() == ((), {"value": new_source, "factor": 3})
        assert previous_data.get_inputs() == ((old_source,), {"offset": 10})
        assert graph.ancestors(saved_ref) == {saved_ref, new_source}
        assert set(graph.nodes()) == {old_source, new_source, saved_ref}
        assert graph.execute(saved_ref) == 15


    def test_node_redefinition_without_inputs_removes_old_connections(
        self, graph: rt.GraphRT,
    ) -> None:
        @graph.node()
        def source() -> int:
            return 2

        @graph.node(source, extra=source)
        def result(value: int, extra: int) -> int:
            return value + extra

        saved_ref = result
        assert graph.execute(saved_ref) == 4

        @graph.node()
        def result() -> int:
            return 42

        assert result == saved_ref
        assert saved_ref.get_inputs() == ((), {})
        assert graph.ancestors(saved_ref) == {saved_ref}
        assert set(graph.nodes()) == {source, saved_ref}
        assert graph.execute(saved_ref) == 42


    def test_existing_dependents_follow_a_redefined_node(self, graph: rt.GraphRT) -> None:
        @graph.node()
        def source() -> int:
            return 2

        @graph.node(source, right=source)
        def result(left: int, right: int) -> int:
            return left + right

        previous_inputs = result.get_inputs()
        assert graph.execute(result) == 4

        @graph.node()
        def source() -> int:
            return 5

        assert result.get_inputs() == previous_inputs
        assert graph.ancestors(result) == {source, result}
        assert set(graph.nodes()) == {source, result}
        assert graph.execute(result) == 10

    def test_operator_ref_node_rebinds_by_name(self, graph: rt.GraphRT) -> None:
        @graph.op()
        def double(value: int) -> int:
            return value * 2

        first_node = graph.node(value=3)(double)
        assert graph.execute(first_node) == 6

        second_node = graph.node(value=10)(double)

        assert first_node == second_node
        assert first_node.get_name() == "double"
        assert graph.nodes() == [first_node]
        assert graph.operators() == [double]
        assert first_node.get_operator() == double
        assert first_node.get_inputs() == ((), {"value": 10})
        assert graph.execute(first_node) == 20
        assert graph.execute(second_node) == 20

class Test_NodeDecorator_Creates_Behaviour():
    """node decorator behaves as a list add_item"""
    def test_unique_nodes(self, graph: rt.GraphRT) -> None:
        @graph.node()
        def hello() -> int:
            return "hello"

        A = hello

        @graph.node()
        def hello() -> int:
            return "hello"

        B = hello

        assert A != B

    