import pytest
import pygraphrt as rt
from textwrap import dedent

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