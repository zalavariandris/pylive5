import copy
import json
import math
from pathlib import Path

import pytest

from pygraphrt import GraphRT, OperatorRef



@pytest.fixture
def graph():
    graph = GraphRT(definitions="def op(*args, **kwargs): return args, kwargs")
    operator = OperatorRef(graph.definitions(), "op")
    source = graph.node(42)(operator, name="source")
    graph.node(source, "source", 42, "42", True, None, 1.5,
               nested={"type": "node", "name": "source", (1, 2): [3, (4, 5)]},
               path=Path("images/test.png"))(operator, name="target")
    return graph


def test_runtime_round_trip_preserves_values_and_forward_references(graph):
    data = graph.todict()
    assert isinstance(data["definitions"], str)
    assert "nodes" not in data
    records = data["graph"]["nodes"]
    assert all("position" not in record for record in records.values())
    data["graph"]["nodes"] = dict(reversed(list(records.items())))
    original = copy.deepcopy(data)
    loaded = GraphRT.fromdict(copy.deepcopy(data))
    assert data == original
    nodes = {node.get_name(): node for node in loaded.nodes()}
    args, kwargs = nodes["target"].get_inputs()
    assert args[0] == nodes["source"]
    assert args[1:] == ("source", 42, "42", True, None, 1.5)
    assert [type(value) for value in args[1:]] == [str, int, str, bool, type(None), float]
    assert kwargs["nested"] == {"type": "node", "name": "source", (1, 2): [3, (4, 5)]}
    assert kwargs["path"] == Path("images/test.png")
    assert loaded.execute(nodes["target"]) == graph.execute(graph.nodes()[1])
    assert loaded.todict() == data


def test_explicit_empty_inputs():
    graph = GraphRT(definitions="def one(): return 1")
    graph.node()(OperatorRef(graph.definitions(), "one"))
    compact = graph.todict()["graph"]["nodes"]["one"]
    assert "args" not in compact and "kwargs" not in compact
    explicit = graph.todict(explicit=True)["graph"]["nodes"]["one"]
    assert explicit["args"] == [] and explicit["kwargs"] == {}


def test_runtime_ignores_presentation_metadata(graph):
    data = graph.todict()
    data["graph"]["nodes"]["target"]["position"] = "not a runtime concern"
    assert GraphRT.fromdict(data).todict() == graph.todict()


def test_imports_and_definitions_disambiguate_operator_names(tmp_path):
    path = tmp_path / "tools.py"
    path.write_text("def op(): return 42", encoding="utf-8")
    graph = GraphRT(definitions="def op(value): return value * 2")
    module = graph.add_import(str(path))
    source = graph.node()(OperatorRef(module, "op"), name="source")
    graph.node(source)(OperatorRef(graph.definitions(), "op"), name="target")
    assert graph.todict()["imports"] == {"tools": str(path)}
    loaded = GraphRT.fromdict(graph.todict())
    assert loaded.execute(loaded.nodes()[1]) == 84
    assert loaded.nodes()[0].get_operator().module is loaded.imports()[0]
    assert loaded.nodes()[1].get_operator().module is loaded.definitions()


def test_unused_imports_survive(tmp_path):
    path = tmp_path / "unused.py"
    path.write_text("def unused(): return 1", encoding="utf-8")
    graph = GraphRT()
    graph.add_import(str(path))
    loaded = GraphRT.fromdict(graph.todict())
    assert len(loaded.imports()) == 1
    assert loaded.imports()[0].path() == str(path)
    assert loaded.nodes() == []


@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan")])
def test_nonfinite_floats_use_json_tags(value):
    graph = GraphRT(definitions="def op(value): return value")
    graph.node(value)(OperatorRef(graph.definitions(), "op"))
    encoded = json.dumps(graph.todict(), allow_nan=False)
    loaded = GraphRT.fromdict(json.loads(encoded))
    restored = loaded.nodes()[0].get_inputs()[0][0]
    assert math.isnan(restored) if math.isnan(value) else restored == value


@pytest.mark.parametrize("damage", ["version", "definitions", "imports", "node", "module", "reference", "args", "value"])
def test_malformed_runtime_data_is_rejected(graph, damage):
    data = graph.todict()
    record = data["graph"]["nodes"]["target"]
    if damage == "version":
        data["version"] = 99
    elif damage == "definitions":
        data["definitions"] = {}
    elif damage == "imports":
        data["imports"] = []
    elif damage == "node":
        data["graph"]["nodes"]["target"] = None
    elif damage == "module":
        record["operator"]["module"] = "unknown"
    elif damage == "reference":
        record["args"][0]["name"] = "unknown"
    elif damage == "args":
        record["args"] = "bad"
    else:
        record["args"] = [{"type": "unknown"}]
    with pytest.raises(ValueError):
        GraphRT.fromdict(data)


def test_invalid_source_and_missing_operator_stay_editable():
    graph = GraphRT(definitions="def op(:")
    graph.node()(OperatorRef(graph.definitions(), "op"))
    loaded = GraphRT.fromdict(graph.todict())
    assert loaded.definitions().get_script() == "def op(:"
    assert loaded.nodes()[0].get_operator().get_value() is None
    loaded.definitions().set_script("def op(): return 7")
    assert loaded.execute(loaded.nodes()[0]) == 7


def test_opaque_values_and_inline_functions_fail_explicitly(graph):
    graph.nodes()[0].set_inputs(object())
    with pytest.raises(TypeError, match="Cannot save input"):
        graph.todict()
    inline = GraphRT()

    @inline.node()
    def op():
        return 1

    with pytest.raises(ValueError, match="script module"):
        inline.todict()


def test_fromdict_constructs_subclass(graph):
    class CustomGraph(GraphRT):
        pass

    assert isinstance(CustomGraph.fromdict(graph.todict()), CustomGraph)


def test_import_alias_survives_round_trip(tmp_path):
    path = tmp_path / "tools.py"
    path.write_text("def op(): return 3", encoding="utf-8")
    graph = GraphRT()
    module = graph.add_import(str(path))
    module.set_name("renamed")
    graph.node()(OperatorRef(module, "op"))
    loaded = GraphRT.fromdict(graph.todict())
    assert loaded.imports()[0].get_name() == "renamed"
    assert loaded.execute(loaded.nodes()[0]) == 3


@pytest.mark.parametrize("name", ["definitions", "duplicate"])
def test_ambiguous_import_names_fail_explicitly(name):
    graph = GraphRT()
    graph.add_import("first.py", source="").set_name(name)
    graph.add_import("second.py", source="").set_name(name)
    with pytest.raises(ValueError, match="must be unique"):
        graph.todict()
