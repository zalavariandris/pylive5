import pytest
import pygraphrt as rt
from textwrap import dedent

def test_operator_decorator():
    # todo: consider moving this to the InlineModule tests
    graph = rt.GraphRT()
    
    @graph.op()
    def add(a:int, b:int) -> int:
        return a + b

    @graph.op()
    def mult(a:int, b:int) -> int:
        return a * b

    add_node2 = graph._create_node(add, [1,1])
    add_node3 = graph._create_node(add, [3,5])
    mult_node = graph._create_node(mult, [add_node2, add_node3])

    result = graph.execute(mult_node)
    assert result == 16, "Decorator should create an operator that computes (1 + 1) * (3 + 5) = 48"

def test_simple_graph_execution():
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