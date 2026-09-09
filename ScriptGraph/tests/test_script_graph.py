from textwrap import dedent

import pytest

from pygraphrt import GraphRT
from scriptgraph import NodeRef, NodeSpec, ScriptGraph


pytestmark = pytest.mark.xfail(
    raises=NotImplementedError, strict=True, reason="ScriptGraph design stubs"
)


def test_live_graph_to_script_and_back():
    graph = GraphRT()

    @graph.node(value=2)
    def number(value):
        return value

    graph.output = number
    adapter = ScriptGraph(graph)
    assert graph.execute() == 2
    number.set_inputs(value=5)

    restored = ScriptGraph(GraphRT())
    restored.update_source(adapter.to_source())
    assert restored.graph.execute() == 5


def test_simple_script_to_graph_and_back():
    source = "def two():\n    return 2\n\nvalue = two()\n__output__ = value\n"
    document = ScriptGraph(GraphRT())
    document.update_source(source)

    assert list(document.spec.operators) == ["two"]
    assert document.spec.nodes == {"value": NodeSpec("two")}
    assert document.spec.output == "value"
    assert document.to_source() == source
    assert document.graph.execute() == 2


def test_connected_script_to_graph_and_back():
    source = dedent('''\
        from math import (
            floor,
        )

        def number():
            return floor(2.5)

        def add(a, b):
            return a + b

        # Connect two calls to the same function.
        left = number()
        right = number()
        result = add(left, b=right)
        __output__ = result
    ''')
    document = ScriptGraph(GraphRT())
    document.update_source(source)

    assert document.spec.nodes == {
        "left": NodeSpec("number"),
        "right": NodeSpec("number"),
        "result": NodeSpec("add", (NodeRef("left"),), {"b": NodeRef("right")}),
    }
    assert document.to_source() == source
    restored = ScriptGraph(GraphRT())
    restored.update_source(document.to_source())
    assert restored.spec == document.spec
    assert restored.graph.execute() == 4


def test_graph_edit_changes_input_and_preserves_function_source():
    prefix = "# Keep this comment\ndef add(a, b):\n    return a + b\n\n"
    document = ScriptGraph(GraphRT())
    document.update_source(prefix + "result = add(1, 2)\n__output__ = result\n")
    document.graph.get_node("result").set_inputs(1, 5)

    assert document.to_source().startswith(prefix)
    restored = ScriptGraph(GraphRT())
    restored.update_source(document.to_source())
    assert restored.spec == document.spec
    assert restored.graph.execute() == 6


def test_source_edit_updates_graph():
    graph = GraphRT()
    document = ScriptGraph(graph)
    document.update_source("def number():\n    return 2\nvalue = number()\n")
    edited = "def number():\n    return 3\nvalue = number()\n__output__ = value\n"
    document.update_source(edited)

    assert document.to_source() == edited
    assert document.graph is graph
    assert graph.execute() == 3
