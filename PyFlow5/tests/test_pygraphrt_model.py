import pytest

from pyflow5.pygraphrt_model import PyFlowRtModel
from pygraphrt.graph_rt import GraphRT
from pygraphrt.script_module_rt import ScriptModuleRT


@pytest.fixture(params=["local", "script", "script_with_local_name_collision"])
def graph_and_operator(request):
    graph = GraphRT()

    if request.param == "local":
        @graph.module().op()
        def mult(a, b):
            return a * b

        operator = mult
    else:
        if request.param == "script_with_local_name_collision":
            @graph.module().op()
            def mult(unrelated):
                return unrelated

        module = ScriptModuleRT("mathy", "def mult(a, b):\n    return a * b\n")
        graph.add_modules([module])
        operator = module.get_operator("mult")

    return graph, operator


def test_node_inlets_use_its_own_operator(graph_and_operator):
    graph, operator = graph_and_operator
    node = graph.node()(operator)
    model = PyFlowRtModel(graph)

    assert list(model.inlets(node.get_name())) == ["a", "b"]
    assert list(model.inLinks(node.get_name(), "a")) == []
    assert list(model.inLinks(node.get_name(), "b")) == []


@pytest.mark.parametrize("binding", ["positional", "keyword", "mixed"])
def test_incoming_links_use_its_own_operator(graph_and_operator, binding):
    graph, operator = graph_and_operator

    @graph.node()
    def one():
        return 1

    if binding == "positional":
        node = graph.node(one, one)(operator)
    elif binding == "keyword":
        node = graph.node(a=one, b=one)(operator)
    else:
        node = graph.node(one, b=one)(operator)

    model = PyFlowRtModel(graph)
    expected = [
        (one.get_name(), "out", node.get_name(), "a"),
        (one.get_name(), "out", node.get_name(), "b"),
    ]

    assert list(model.links()) == expected
    assert list(model.inLinks(node.get_name(), "a")) == [expected[0]]
    assert list(model.inLinks(node.get_name(), "b")) == [expected[1]]
