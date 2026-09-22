import pytest
import pygraphrt as rt
from textwrap import dedent

from pygraphrt.serialization import (
    serialize, deserialize, _todict
)

# hello_world_graphfixture

@pytest.fixture
def hello_world_graph():
    G = rt.GraphRT()
    @G.node()
    def the_name():
        return "Mása"

    @G.node()
    def the_greeting():
        return "Hey"

    @G.node(the_name)
    def hello_world(name:str, greeting:str="Hello"):
        return f"{greeting}, {name}!"
    return G, [the_name, the_greeting, hello_world]

class TestSerializeNodes:
    def test_empty_graph(self):
        G = rt.GraphRT()

        data = _todict(G)
        assert "nodes" in data
        assert isinstance(data["nodes"], dict)
        assert len(data["nodes"]) == 0

    def test_graph_with_nodes(self, hello_world_graph):
        G, _ = hello_world_graph

        data = _todict(G)
        assert "nodes" in data
        assert isinstance(data["nodes"], dict)
        assert len(data["nodes"]) == 3
        assert "the_name" in data["nodes"]
        assert "the_greeting" in data["nodes"]
        assert "hello_world" in data["nodes"]

    def test_node_operators(self, hello_world_graph):
        G, _ = hello_world_graph

        data = _todict(G)
        assert "operator" in data["nodes"]["the_name"]
        assert data["nodes"]["the_name"]["operator"] == "the_name"
        assert "operator" in data["nodes"]["the_greeting"]
        assert data["nodes"]["the_greeting"]["operator"] == "the_greeting"

    def test_node_inputs(self, hello_world_graph):
        G, (the_name, the_greeting, hello_world) = hello_world_graph

        data = _todict(G, explicit=False)
        args = data["nodes"]["hello_world"].get("args", [])
        kwargs = data["nodes"]["hello_world"].get("kwargs", {})
        assert "the_name" in args or "the_name" in kwargs

    def test_explicit_implicit_inputs(self, hello_world_graph):
        G = rt.GraphRT()

        @G.node()
        def hello_world(the_name, the_greeting):
            return f"{the_greeting}, {the_name}!"

        explicit_data = _todict(G, explicit=True)
        assert "args" in explicit_data["nodes"]["hello_world"]
        assert "kwargs" in explicit_data["nodes"]["hello_world"]

        implicit_data = _todict(G, explicit=False)
        assert "args" not in implicit_data["nodes"]["hello_world"]
        assert "kwargs" not in implicit_data["nodes"]["hello_world"]



if __name__ == "__main__":
    pytest.main([__file__, "-v"])