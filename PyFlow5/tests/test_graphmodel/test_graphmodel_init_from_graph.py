from textwrap import dedent

from pygraphrt.inline_module import FunctionOperator
import pytest

from pyflow5.pygraphrt_model import PyFlowRTModel
from pygraphrt.graph_rt import GraphRT
from pygraphrt.script_module import ScriptModuleRT


def test_initialize_model_without_graph():
    with pytest.raises(TypeError):
        model = PyFlowRTModel()


def test_initialize_model_with_empty_graph():
    graph = GraphRT()
    model = PyFlowRTModel(graph)

    assert len(list(model.nodes())) == 0
    assert len(list(model.links())) == 0

def test_initialize_model_with_nodes_only():
    graph = GraphRT()

    @graph.node()
    def op1():
        pass

    @graph.node()
    def op2():
        pass

    model = PyFlowRTModel(graph)

    assert len(list(model.nodes())) == 2
    assert len(list(model.links())) == 0

def test_initialize_model_with_helloworld_graph():
    graph = GraphRT()
    
    @graph.node()
    def the_name():
        return "Mása"

    @graph.node()
    def the_greeting():
        return "Hello"

    @graph.node(the_name, the_greeting)
    def hello_world(name:str, greeting:str):
        return f"{greeting}, {name}"

    model = PyFlowRTModel(graph)

    assert len(list(model.nodes())) == 3
    assert len(list(model.links())) == 2

    


if __name__ == "__main__":
    pytest.main([__file__, "-v"])