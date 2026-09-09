from pygraphrt import GraphRT
from scriptgraph import ScriptGraph


def test_adapter_keeps_live_graph_identity():
    graph = GraphRT()
    adapter = ScriptGraph(graph)

    @graph.node(value=2)
    def number(value):
        return value

    graph.output = number
    assert adapter.graph is graph
    assert adapter.graph.execute() == 2

    number.set_inputs(value=5)
    assert adapter.graph.execute() == 5
