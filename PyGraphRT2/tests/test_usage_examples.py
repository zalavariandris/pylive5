from pygraphrt2.graph import Graph, NodeRef

def test_graph_usage():
    """
    Show how to use the graph processing at runtime
    """
    G = Graph()

    @G.node()
    def the_name():
        return "Mása"

    @G.node()
    def the_greeting():
        return "Hey"

    @G.node(the_name)
    def hello(name:str, greeting:str="Hello"):
        return f"{greeting} {name}!"

    @G.effect(the_name)
    def greet_effect(name:str):
        print(f"Greeting {name}")

    # Inspect the graph structure
    assert set(list(G.nodes())) == {the_name, the_greeting, hello}
    assert G.in_links(hello) == {the_name: {0}}
    assert G.out_links(the_name) == {hello: {0}}

    # Graph is mutable at runtime
    G._create_node...
    G._update_node...
    G._remove_node...

    # Inspect graph mutations
    assert G.nodes_added ...
    assert G.nodes_removed ...
    assert G.nodes_changed ...

    # Evaluate the graph
    result = G.execute(hello)
    assert result == "Hello Mása"

from pygraphrt2.graph import Graph, NodeRef
from pygraphrt2.engine import Engine
from pygraphrt2.backend import Backend

