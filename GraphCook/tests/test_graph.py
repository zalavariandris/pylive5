import pytest
from graphcook.graph import Graph


@pytest.fixture
def hello_world(): 
    G = Graph()
    G.add_node("the_name")
    G.add_node("the_greeting")
    G.add_node("hello_world")
    G.add_node("preview")
    G.add_link("the_name", "hello_world", "name")
    G.add_link("the_greeting", "hello_world", "greeting")
    G.add_link("hello_world", "preview", "input")
    return G

def test_add_link_to_connected_inlet(hello_world):
    G = hello_world
    with pytest.raises(ValueError):
        G.add_link("the_name", "hello_world", "name")

def test_remove_node_with_links(hello_world):
    G = hello_world
    G.remove_node("hello_world")
    assert "hello_world" not in G.nodes()
    assert list(G.links()) == []

if __name__ == "__main__":
    pytest.main([__file__])