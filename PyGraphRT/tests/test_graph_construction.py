import pytest
import pygraphrt as rt
from textwrap import dedent


def test_nodes_sharing_operator_have_unique_names():
    graph = rt.GraphRT()

    @graph.module().op()
    def identity(value):
        return value

    nodes = [graph.node(value)(identity) for value in range(3)]
    assert [node.get_name() for node in nodes] == ["identity", "identity_0", "identity_1"]
    assert len(graph.nodes()) == 3
    assert all(node.get_operator() is identity for node in nodes)
    assert [graph.execute(node) for node in nodes] == [0, 1, 2]

    changes = []
    graph.node_inputs_changed.connect(changes.append)
    graph.remove_node(nodes[1])
    nodes[2].set_inputs(42)
    assert changes[-1] == "identity_1"
    assert graph.get_node("identity_1") is nodes[2]
    assert graph.execute(nodes[2]) == 42


def test_generated_node_names_avoid_explicit_names():
    graph = rt.GraphRT()

    @graph.module().op()
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
    
    @graph.module().op()
    def add(a:int, b:int) -> int:
        return a + b

    @graph.module().op()
    def mult(a:int, b:int) -> int:
        return a * b

    add_node2 = graph.node(1,1)(add)
    add_node3 = graph.node(3,5)(add)
    mult_node = graph.node(add_node2, add_node3)(mult)

    result = graph.execute(mult_node)
    assert result == 16, "Decorator should create an operator that computes (1 + 1) * (3 + 5) = 48"

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
