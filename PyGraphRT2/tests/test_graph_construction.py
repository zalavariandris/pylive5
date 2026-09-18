import pytest
import pygraphrt2 as rt
from textwrap import dedent


def test_nodes_sharing_operator_have_unique_names():
    graph = rt.GraphRT()

    @graph.op()
    def identity(value):
        return value

    nodes = [graph.node(value)(identity) for value in range(3)]
    assert [node.get_name() for node in nodes] == ["identity", "identity_0", "identity_1"]
    assert len(graph.nodes()) == 3
    assert all(node.get_operator() is identity for node in nodes)
    assert [graph.execute(node) for node in nodes] == [0, 1, 2]

def test_generated_node_names_avoid_explicit_names():
    graph = rt.GraphRT()

    @graph.op()
    def identity(value):
        return value

    explicit = graph.node(10)(identity, name="identity_0")
    first = graph.node(20)(identity)
    second = graph.node(30)(identity)
    assert explicit.get_name() == "identity_0"
    assert first.get_name() == "identity"
    assert second.get_name() == "identity_1"
    assert len(graph.nodes()) == 3


def test_operator_decorator():
    graph = rt.GraphRT()
    
    @graph.op()
    def add(a:int, b:int) -> int:
        return a + b

    @graph.op()
    def mult(a:int, b:int) -> int:
        return a * b

    add_node2 = graph.node(1,1)(add)
    add_node3 = graph.node(3,5)(add)
    mult_node = graph.node(add_node2, add_node3)(mult)

    assert graph.operators() == [add, mult]
    
    
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

if __name__ == "__main__":
    pytest.main([__file__, "-v"])