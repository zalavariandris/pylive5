import pytest
import pygraphrt as rt
from textwrap import dedent

def test_operator_decorator():
    graph = rt.GraphRT()
    
    @graph._local_module.op()
    def add(a:int, b:int) -> int:
        return a + b

    @graph._local_module.op()
    def mult(a:int, b:int) -> int:
        return a * b

    add_node2 = graph.node(1,1)(add)
    add_node3 = graph.node(3,5)(add)
    mult_node = graph.node(add_node2, add_node3)(mult)

    assert all(
        isinstance(node, rt.OperatorRef) 
        for node in [add, mult]
    )
    assert graph.operators() == [add, mult]

