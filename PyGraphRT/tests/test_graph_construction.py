import pytest
import pygraphrt as rt
from textwrap import dedent

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


def test_nodes_sharing_operator_have_unique_names():
    graph = rt.GraphRT()

    @graph.node()
    def identity(value):
        return value

    node_duplicates = [
        graph.node(val)(identity.get_operator()) 
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

def test_generated_node_names_avoid_explicit_names():
    graph = rt.GraphRT()

    @graph._local_module.op()
    def identity(value):
        return value

    explicit = graph.node(10)(identity, name="identity_0")
    first = graph.node(20)(identity)
    second = graph.node(30)(identity)
    assert explicit.get_name() == "identity_0"
    assert first.get_name() == "identity"
    assert second.get_name() == "identity_1"
    assert len(graph.nodes()) == 3

if __name__ == "__main__":
    pytest.main([__file__, "-v"])