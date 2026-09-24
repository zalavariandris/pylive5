from pygraphrt.graph_rt import NodeNameCollisionError
import pytest
import pygraphrt as rt
from textwrap import dedent

from PyGraphRT.tests.test_graph_serialization import graph

def test_node_decorator():
    G = rt.GraphRT()
    
    @G.node(a=1, b=2)
    def n1(a:int, b:int) -> int:
        return a + b

    result = G.execute(n1)
    assert result == 3, "Decorator should create a node that computes 1 + 2 = 3"

def test_node_decorator_with_inputs():
    G = rt.GraphRT()

    @G.node()
    def one() -> int:
        return 1

    @G.node()
    def two() -> int:
        return 2

    @G.node(a=one, b=two)
    def n1(a:int, b:int) -> int:
        return a + b

    result = G.execute(n1)
    assert result == 3, "Node should compute 1 + 2 = 3"

def test_nodes_sharing_operators_are_unique():
    # todo: I think this test is redundant now. 
    #   NodeRef creation equality (is tested with CRUDtests), and execution should be tested seperatelly
    graph = rt.GraphRT()

    @graph.node()
    def identity(value):
        return value

    node_duplicates = [
        graph._create_node(identity.get_operator(), [val])
        for val in range(3)
    ]

    assert len(graph.nodes()) == 4
    actual_names = [node.get_name() for node in graph.nodes()]
    # make sure the names are unique
    assert len(actual_names) == len(set(actual_names)), "Node names should be unique, got: {actual_names}"

    
    assert all(node.get_operator() is identity.get_operator() for node in node_duplicates)

    # check the execution results of the duplicated nodes
    assert [
        graph.execute(node) 
        for node in node_duplicates
    ] == [0, 1, 2]

@pytest.mark.xfail(reason="Specifying names are deprecated. At some point we might add it back")
def test_generated_node_names_avoid_explicit_names():
    # todo: consider manually specifying ndoe names especially for the UI.
    #   keeping a unique name accross the nodes makes the Serialization human readable, which is desired.
    graph = rt.GraphRT()

    @graph._inline_module.op()
    def identity(value):
        return value

    explicit = graph.node(10)(identity, name="identity_0")
    first = graph.node(20)(identity)
    second = graph.node(30)(identity)
    assert explicit.get_name() == "identity_0"
    assert first.get_name() == "identity"
    assert second.get_name() == "identity_1"
    assert len(graph.nodes()) == 3

class Test_NodeAndOperatorDecorators_REGRESSION_TESTS:
    def test_duplicated_operator_raises_value_error(self):
        graph = rt.GraphRT()
        
        @graph.op()
        def identity(value):
            return value

        with pytest.raises(ValueError):
            @graph.op()
            def identity(value):
                return value

    def test_duplicated_node_names_raises_value_error(self):
        graph = rt.GraphRT()

        @graph.op()
        def identity(value):
            return value

        n1 = graph.node(10)(identity, name="SAME")
        
        with pytest.raises(NodeNameCollisionError):
            n2 = graph.node(20)(identity, name="SAME")

    def test_unique_node_name_generation_with_identical_op(self):
        graph = rt.GraphRT()

        @graph.op()
        def identity(value):
            return value

        n1 = graph.node(10)(identity)
        n2 = graph.node(20)(identity)

        assert n1.get_name() != n2.get_name()

    @pytest.mark.xfail(reason="Creating nodes using identical functions directly raises several questions. See comments below.")
    def test_unique_node_name_generation_with_identical_func_uses_the_same_operator(self):
        # todo: this behaviour needs more attention.
        #       basically createing nodes using functions directly could raise several questions:
        #       - how to serialize it? especially when the funciton has dependencies.
        #       - how this could be any useful other than a s shorthand to create nodes quickly.
        # this is quite an edge case, cause decorators are nott supposed to be used this way.
        # using the same function, to create nodes will create duplicate operators within the inline module, 
        # using the same name. for now this will raise a ValueError, cause operators must have unique names.
        # on the other hand, inline functions are currently just a fancy way to define operators within the graph.
        # its not used by the application, and not serialized.
        
        graph = rt.GraphRT()

        def identity(value):
            return value

        n1 = graph.node(10)(identity)
        n2 = graph.node(20)(identity)

    def test_node_decorator_on_fail_should_not_add_operator(self):
        graph = rt.GraphRT()

        @graph.op()
        def identity(value):
            return value

        assert len(graph.inline().operators()) == 1

        try:
            # Attempt to create a node with a duplicate name, which should raise an error
            graph.node(10)(identity, name="SAME")
            graph.node(20)(identity, name="SAME")
        except NodeNameCollisionError:
            pass

        # Ensure that the operator was not added to the graph due to the error
        assert len(graph.nodes()) == 1
        assert len(graph.inline().operators()) == 1

    def test_node_decorator_with_same_function(self):
        graph = rt.GraphRT()

        def hello():
            return "hello"

        graph.node(hello)
        graph.node(hello)
 



if __name__ == "__main__":
    pytest.main([__file__, "-v"])
