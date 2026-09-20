import pytest

from pyflow5.pygraphrt_model import PyFlowRTModel
from pygraphrt.graph_rt import GraphRT
from pygraphrt.local_module import LocalModuleRT


@pytest.fixture
def incomplete_hello_world_graph():
    graph = GraphRT()

    @graph.node()
    def the_name():
        return "World"

    @graph.node()
    def the_greeting():
        return "Hello"

    @graph.node(name=the_name)
    def hello_world(name: str, greeting: str="Hello"):
        return f"{greeting}, {name}!"


    return graph

@pytest.fixture
def hello_world_model(incomplete_hello_world_graph):
    model = PyFlowRTModel(incomplete_hello_world_graph)

    # make sure initial conditions are as expected for the incomplete graph
    assert len(list(model.nodes())) == 3
    assert len(list(model.links())) == 1
    return model

def test_add_node(hello_world_model):
    model = hello_world_model
    original_count = len(model.nodes())

    module = LocalModuleRT()

    @module.op()
    def new_operator():
        return "New node"

    
    model.addNode(new_operator)

    assert len(list(model.nodes())) == original_count + 1

def test_remove_node(hello_world_model):
    model = hello_world_model

    model.removeNodes(["hello_world"])

    assert set(model.nodes()) == {"the_name", "the_greeting"}
    assert list(model.links()) == []

def test_add_link(hello_world_model):
    model = hello_world_model

    model.addLink("the_greeting", "out", "hello_world", "greeting")

def test_remove_link(hello_world_model):
    model = hello_world_model

    original_link_count = len(set(model.links()))
    model.removeLinks([("the_name", "out", "hello_world", "name")])

    assert len(list(model.links())) == original_link_count - 1

def test_linking_to_nonexistent_inlet_raises_value_error(hello_world_model):
    model = hello_world_model
    original_links = set(model.links())

    with pytest.raises(ValueError):
        model.addLink("the_name", "out", "hello_world", "nonexistent_inlet")

    assert set(model.links()) == original_links

def test_removing_nodes_remove_links(hello_world_model):
    model = hello_world_model

    original_link_count = len(set(model.links()))
    model.removeNodes(["the_name"])

    assert set(model.nodes()) == {"the_greeting", "hello_world"}
    assert len(list(model.links())) == original_link_count - 1

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
