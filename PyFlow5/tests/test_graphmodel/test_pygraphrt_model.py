from textwrap import dedent

import pytest

from pyflow5.pygraphrt_model import PyFlowRTModel
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

        module = ScriptModuleRT("mathy", dedent("""\
            def mult(a, b):
                return a * b
        """))
        operator = module.operators()[0] # get the mult operator

    return graph, operator


def test_node_inlets_use_its_own_operator(graph_and_operator):
    graph, operator = graph_and_operator
    node = graph.node()(operator)
    model = PyFlowRTModel(graph)

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

    model = PyFlowRTModel(graph)
    expected = [
        (one.get_name(), "out", node.get_name(), "a"),
        (one.get_name(), "out", node.get_name(), "b"),
    ]

    assert list(model.links()) == expected
    assert list(model.inLinks(node.get_name(), "a")) == [expected[0]]
    assert list(model.inLinks(node.get_name(), "b")) == [expected[1]]


@pytest.mark.parametrize("references", [False, True], ids=["literal", "linked"])
def test_inlets_include_extra_inputs(graph_and_operator, references):
    graph, operator = graph_and_operator

    @graph.node()
    def source():
        return 1

    value = source if references else 1
    node = graph.node(value, value, value, extra=value)(operator)
    model = PyFlowRTModel(graph)
    name = node.get_name()
    assert list(model.inlets(name)) == ["a", "b", "3", "extra"]
    expected = [(source.get_name(), "out", name, inlet)
                for inlet in ("a", "b", "3", "extra")] if references else []
    assert list(model.links()) == expected
    for inlet in model.inlets(name):
        assert list(model.inLinks(name, inlet)) == [link for link in expected if link[3] == inlet]


def test_duplicate_positional_and_keyword_binding_keeps_both_links(graph_and_operator):
    graph, operator = graph_and_operator
    first = graph.node()(lambda: 1)
    second = graph.node()(lambda: 2)
    node = graph.node(first, a=second)(operator)
    model = PyFlowRTModel(graph)
    assert list(model.inlets(node.get_name())) == ["a", "b"]
    assert list(model.inLinks(node.get_name(), "a")) == [
        (first.get_name(), "out", node.get_name(), "a"),
        (second.get_name(), "out", node.get_name(), "a"),
    ]


def test_inlets_follow_signature_changes_and_missing_operator():
    from pygraphrt.abstract_module_rt import OperatorRef
    module = ScriptModuleRT("tools", "def target(a, b): return a + b")
    graph = GraphRT()
    source = graph.node()(lambda: 1)
    node = graph.node(source, source, extra=source)(OperatorRef(module, "target"))
    model = PyFlowRTModel(graph)
    for script, expected in [
        ("def target(a): return a", ["a", "2", "extra"]),
        ("def target(:", ["1", "2", "extra"]),
        ("def target(a, b, c): return a", ["a", "b", "c", "extra"]),
    ]:
        module.set_script(script)
        assert list(model.inlets(node.get_name())) == expected
        for link in model.links():
            assert link[3] in expected
            assert link in list(model.inLinks(node.get_name(), link[3]))


def test_extra_positional_inlet_does_not_collide_with_numeric_keyword():
    graph = GraphRT()
    source = graph.node()(lambda: 1)
    node = graph.node(source, **{"1": source})(lambda: None)
    model = PyFlowRTModel(graph)
    assert list(model.inlets(node.get_name())) == ["#1", "1"]
    assert {link[3] for link in model.links()} == {"#1", "1"}
