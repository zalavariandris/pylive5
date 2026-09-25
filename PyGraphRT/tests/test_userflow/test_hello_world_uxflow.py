import pytest
from pygraphrt.graph_rt import GraphRT
from pygraphrt.abstract_module_rt import OperatorRef, ParameterData

def test_hello_world_uxflow():
    graph = GraphRT()
    hello_world_op = OperatorRef("hello_world")
    graph.add_operator(hello_world_op)
    result = graph.execute()
    assert result == "Hello, World!"