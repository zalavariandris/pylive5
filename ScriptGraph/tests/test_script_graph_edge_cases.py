import pytest

from pygraphrt import GraphRT
from scriptgraph import ScriptGraph, UnsupportedScriptError


pytestmark = pytest.mark.xfail(
    raises=NotImplementedError, strict=True, reason="ScriptGraph design stubs"
)


def test_empty_script():
    document = ScriptGraph(GraphRT())
    assert document.spec.nodes == {}
    assert document.spec.output is None
    assert document.to_source() == ""


def test_preserves_windows_newlines_and_missing_final_newline():
    source = "# heading\r\ndef number():\r\n    return 2\r\n\r\nvalue = number()"
    document = ScriptGraph(GraphRT())
    document.update_source(source)
    assert document.to_source() == source


def test_parsing_does_not_import_or_execute_functions():
    source = (
        "import nonexistent_scriptgraph_dependency\n"
        "def fail():\n    raise RuntimeError('must not run')\n"
        "value = fail()\n"
    )
    spec = ScriptGraph.parse(source)
    assert "value" in spec.nodes


def test_literal_string_is_not_a_node_reference():
    source = "def echo(value):\n    return value\nfirst = echo('hello')\nsecond = echo('first')\n"
    spec = ScriptGraph.parse(source)
    assert spec.nodes["second"].args == ("first",)


def test_invalid_source_edit_retains_previous_document():
    source = "def number():\n    return 2\nvalue = number()\n"
    graph = GraphRT()
    document = ScriptGraph(graph)
    document.update_source(source)
    previous = document.spec
    with pytest.raises(SyntaxError):
        document.update_source("def number(:")
    assert document.to_source() == source
    assert document.spec == previous
    assert document.graph is graph


def test_rejects_top_level_control_flow():
    with pytest.raises(UnsupportedScriptError):
        ScriptGraph.parse("if True:\n    value = 2\n")


def test_rejects_unknown_node_reference():
    with pytest.raises(UnsupportedScriptError):
        ScriptGraph.parse("def echo(x):\n    return x\nresult = echo(missing)\n")


def test_rejects_duplicate_node_names():
    with pytest.raises(UnsupportedScriptError):
        ScriptGraph.parse("def number():\n    return 2\nvalue = number()\nvalue = number()\n")


def test_rejects_nested_node_calls():
    with pytest.raises(UnsupportedScriptError):
        ScriptGraph.parse("def echo(x):\n    return x\nvalue = echo(echo(2))\n")
