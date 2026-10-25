import json
import math
from pathlib import Path
from typing import Any

import pytest

from pygraphrt2.engine_serializer import GraphDeserializer, GraphSerializer
from pygraphrt2.graph import Graph
from pygraphrt2.inline_executor import InlineExecutor
from pygraphrt2.script_module import ScriptModule, ScriptOperatorRef


def roundtrip(graph: Graph, registry: ScriptModule) -> tuple[ScriptModule, Graph]:
    data = GraphSerializer(graph, registry).todict()
    text = json.dumps(data, allow_nan=False)
    return GraphDeserializer().fromdict(json.loads(text))


@pytest.mark.parametrize("module_name", [None, "local"])
def test_roundtrip_restores_forward_links_and_execution(module_name: str | None) -> None:
    source = (
        "def number(): return 6\n"
        "def combine(left, extra, *, right): return left + extra + right\n"
    )
    registry = ScriptModule(module_name)
    registry.set_script(source)
    registry.evaluate()
    graph = Graph()
    result = graph._create_node(name="result")
    number = graph._create_node(registry.get_operator_by_name("number"), name="number")
    graph._update_node(
        result,
        registry.get_operator_by_name("combine"),
        (number, 3),
        {"right": number},
    )

    restored_registry, restored_graph = roundtrip(graph, registry)
    restored_result, restored_number = restored_graph.nodes()

    assert restored_registry.name() == module_name
    assert restored_registry.get_source() == source
    assert restored_graph.in_links(restored_result) == {restored_number: {0, "right"}}
    assert restored_graph.out_links(restored_number) == {restored_result: {0, "right"}}
    assert restored_result.resolve().args == (restored_number, 3)
    assert restored_result.resolve().kwargs == {"right": restored_number}
    assert restored_result.resolve().operator == restored_registry.get_operator_by_name("combine")
    assert InlineExecutor(restored_graph).execute(restored_result)[restored_result] == 15


def test_roundtrip_preserves_literal_types_and_nonfinite_floats() -> None:
    values = (
        None, True, 42, 1.25, "Árvíztűrő",
        [1, (2, 3)],
        {("key", 1): [Path("assets/image.png"), {"type": "node", "name": "literal"}]},
        float("inf"), float("-inf"), float("nan"),
    )
    graph = Graph()
    graph._create_node(args=values, kwargs={"path": Path("example.py")}, name="values")

    _, restored_graph = roundtrip(graph, ScriptModule())
    state = restored_graph.nodes()[0].resolve()

    assert state.args[:-1] == values[:-1]
    assert math.isnan(state.args[-1])
    assert state.kwargs == {"path": Path("example.py")}


@pytest.mark.parametrize("explicit", [False, True])
def test_empty_nodes_and_modules_roundtrip(explicit: bool) -> None:
    registry = ScriptModule()
    graph = Graph()
    restored_registry, restored_graph = roundtrip(graph, registry)
    assert restored_registry.get_source() == ""
    assert restored_graph.nodes() == []

    graph._create_node(name="empty")
    data = GraphSerializer(graph, registry).todict(explicit=explicit)
    expected = {"operator": None, "args": [], "kwargs": {}} if explicit else {}
    assert data["graph"]["nodes"]["empty"] == expected

    _, restored_graph = GraphDeserializer().fromdict(data)
    state = restored_graph.nodes()[0].resolve()
    assert state.operator is None
    assert state.args == ()
    assert state.kwargs == {}


@pytest.mark.parametrize("source", ["def answer(:", "raise RuntimeError('broken')", ""])
def test_missing_operator_reference_survives_roundtrip_and_script_repair(source: str) -> None:
    registry = ScriptModule()
    registry.set_script(source)
    registry.evaluate()
    graph = Graph()
    graph._create_node(ScriptOperatorRef(registry, "answer"), name="answer")

    restored_registry, restored_graph = roundtrip(graph, registry)
    operator = restored_graph.nodes()[0].resolve().operator
    assert isinstance(operator, ScriptOperatorRef)
    assert operator.name() == "answer"
    assert operator.module() is restored_registry
    assert restored_registry.get_source() == source
    if source:
        assert isinstance(restored_registry.get_status(), Exception)
    with pytest.raises(KeyError, match="answer"):
        operator()

    restored_registry.set_script("def answer(): return 42\n")
    restored_registry.evaluate()
    assert operator() == 42
    assert operator in set(restored_registry.operators())


def test_roundtrip_preserves_cycles() -> None:
    graph = Graph()
    first = graph._create_node(name="first")
    second = graph._create_node(args=(first,), name="second")
    graph._update_node(first, args=(second,))

    _, restored_graph = roundtrip(graph, ScriptModule())
    restored_first, restored_second = restored_graph.nodes()
    assert restored_first.resolve().args == (restored_second,)
    assert restored_second.resolve().args == (restored_first,)


def test_operator_references_use_flat_names_and_require_the_same_module() -> None:
    registry = ScriptModule("local")
    graph = Graph()
    node = graph._create_node(ScriptOperatorRef(registry, "answer"), name="answer")
    data = GraphSerializer(graph, registry).todict()
    assert data["version"] == 4
    assert data["script"] == {"name": "local", "source": ""}
    assert data["graph"]["nodes"]["answer"]["operator"] == "answer"
    assert "modules" not in data

    other_registry = ScriptModule("local")
    graph._update_node(node, ScriptOperatorRef(other_registry, "answer"))
    with pytest.raises(ValueError, match="different script module"):
        GraphSerializer(graph, registry).todict()

    graph._update_node(node, lambda: 42)
    with pytest.raises(TypeError, match="Only script operator references"):
        GraphSerializer(graph, registry).todict()


@pytest.mark.parametrize("version", [None, 3, 4.0, True])
def test_rejects_unsupported_versions(version: Any) -> None:
    with pytest.raises(ValueError, match="expected version 4"):
        GraphDeserializer().fromdict({"version": version})


def test_rejects_invalid_operator_names() -> None:
    data = GraphSerializer(Graph(), ScriptModule()).todict()
    data["graph"]["nodes"]["invalid"] = {"operator": {"module": "local", "name": "answer"}}
    with pytest.raises(ValueError, match="Invalid operator name"):
        GraphDeserializer().fromdict(data)


def test_rejects_unknown_input_types_and_dangling_connections() -> None:
    data = GraphSerializer(Graph(), ScriptModule()).todict()
    record = {"args": [{"type": "unknown"}]}
    data["graph"]["nodes"]["invalid"] = record
    with pytest.raises(ValueError, match="Unsupported input type"):
        GraphDeserializer().fromdict(data)

    record["args"] = [{"type": "node", "name": "missing"}]
    with pytest.raises(KeyError, match="missing"):
        GraphDeserializer().fromdict(data)
