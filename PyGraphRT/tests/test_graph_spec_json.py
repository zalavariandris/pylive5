import json
from types import MappingProxyType

import pytest

from pygraphrt.graph_rt import GraphRT
from pygraphrt.graph_spec import (
    GraphSpec,
    GraphSpecJSONEncoder,
    ImportSpec,
    ModuleRef,
    ModuleSpec,
    NodeRef,
    NodeSpec,
    OperatorRef,
    OperatorSpec,
    serialize,
    snapshot,
    snapshot_script_module,
)
from pygraphrt.script_module_rt import ScriptModuleRT


@pytest.mark.parametrize("explicit", [False, True])
def test_spec_json_preserves_definitions_references_and_literals(explicit):
    operator = OperatorRef("tools", "combine")
    source = 'def combine(*args, **kwargs):\n    return "hello \\"world\\""\n'
    spec = GraphSpec(
        modules=MappingProxyType({
            ModuleRef("tools"): ModuleSpec({
                operator: OperatorSpec(
                    imports=(ImportSpec("math", "sqrt", "root"),),
                    source=source,
                ),
            }),
        }),
        nodes={
            NodeRef("source"): NodeSpec(operator),
            NodeRef("result"): NodeSpec(
                operator,
                args=(NodeRef("source"), "source", 0, False, None, 1.25),
                kwargs=MappingProxyType({"text": 'quoted "text"\nárvíz', "value": NodeRef("source")}),
            ),
        },
        output=NodeRef("result"),
    )

    serialized = serialize(spec, explicit=explicit)
    assert isinstance(serialized, str)
    data = json.loads(serialized)
    assert data["modules"] == {
        "tools": {
            "operators": {
                "tools.combine": {
                    "imports": [{"path": "math", "module": "sqrt", "alias": "root"}],
                    "source": source,
                },
            },
        },
    }
    expected_source = {"operator": "tools.combine"}
    if explicit:
        expected_source.update(args=[], kwargs={})
    assert data["nodes"] == {
        "source": expected_source,
        "result": {
            "operator": "tools.combine",
            "args": ["source", "source", 0, False, None, 1.25],
            "kwargs": {"text": 'quoted "text"\nárvíz', "value": "source"},
        },
    }
    assert data["output"] == "result"
    # Encoding must preserve the reference types and containers in the snapshot.
    assert next(iter(spec.modules)) == ModuleRef("tools")
    assert spec.nodes[NodeRef("result")].args[0] == NodeRef("source")


def test_empty_spec_and_unassigned_operator_serialize_as_null():
    assert json.loads(serialize(GraphSpec({}, {}, None))) == {
        "modules": {}, "nodes": {}, "output": None,
    }
    spec = GraphSpec({}, {NodeRef("unassigned"): NodeSpec(None)}, None)
    assert json.loads(serialize(spec))["nodes"] == {
        "unassigned": {"operator": None},
    }


def test_same_operator_name_in_different_modules_stays_qualified():
    spec = GraphSpec(
        modules={},
        nodes={
            NodeRef("left"): NodeSpec(OperatorRef("left", "value")),
            NodeRef("right"): NodeSpec(OperatorRef("right", "value")),
        },
        output=NodeRef("right"),
    )
    assert json.loads(serialize(spec))["nodes"] == {
        "left": {"operator": "left.value"},
        "right": {"operator": "right.value"},
    }


def test_runtime_serialization_captures_links_and_output_without_execution():
    graph = GraphRT()

    @graph.node(2)
    def source(value):
        raise AssertionError("Serialization must not execute operators")

    @graph.node(source, other=source)
    def result(value, other):
        raise AssertionError("Serialization must not execute operators")

    graph.output = result
    spec = snapshot(graph)
    assert spec.output == NodeRef("result")
    assert spec.nodes[NodeRef("result")].args == (NodeRef("source"),)
    assert spec.nodes[NodeRef("result")].kwargs == {"other": NodeRef("source")}
    assert json.loads(serialize(graph, explicit=True)) == {
        "modules": {},
        "nodes": {
            "source": {"operator": "local.source", "args": [2], "kwargs": {}},
            "result": {
                "operator": "local.result",
                "args": ["source"],
                "kwargs": {"other": "source"},
            },
        },
        "output": "result",
    }

    source.set_inputs(99)
    assert json.loads(serialize(spec))["nodes"]["source"]["args"] == [2]
    assert json.loads(serialize(graph))["nodes"]["source"]["args"] == [99]


def test_script_module_snapshot_encodes_source():
    source = "def value():\n    return 42\n"
    module = ScriptModuleRT("tools", source)
    data = json.loads(json.dumps(snapshot_script_module(module), cls=GraphSpecJSONEncoder))
    assert data == {"script": source}


def test_unsupported_literal_raises_instead_of_stringifying():
    spec = GraphSpec(
        {}, {NodeRef("node"): NodeSpec(OperatorRef("local", "value"), args=(object(),))}, None,
    )
    with pytest.raises(TypeError, match="not JSON serializable"):
        serialize(spec)
