import copy
from typing import Any

import pytest

from pygraphrt import GraphRT


@pytest.mark.parametrize("data", [
    None,
    [],
    {},
    {"version": True},
    {"version": 1.0},
    {"version": "1"},
    {"version": 2},
    {"version": 1, "definitions": "def op(): return 1"},
    {"version": 1, "_local_": None},
    {"version": 1, "graph": []},
    {"version": 1, "graph": {}},
    {"version": 1, "graph": {"nodes": []}},
    {"version": 1, "graph": {"nodes": {}, "extra": 1}},
    {"version": 1, "graph": {"nodes": {1: {"operator": "op"}}}},
])
def test_invalid_graph_structure_is_rejected(data: Any) -> None:
    with pytest.raises(ValueError, match="Invalid graph format"):
        GraphRT.fromdict(data)


@pytest.mark.parametrize("record", [
    None,
    {},
    {"operator": None},
    {"operator": {"module": "_local_"}},
    {"operator": {"module": 1, "name": "op"}},
    {"operator": {"module": "_local_", "name": "op", "extra": 1}},
    {"operator": "op", "extra": 1},
    {"operator": "op", "args": {}},
    {"operator": "op", "kwargs": []},
    {"operator": "op", "kwargs": {1: "value"}},
    {"operator": "op", "args": [object()]},
    {"operator": "op", "args": [{"type": "unknown"}]},
    {"operator": "op", "args": [{"type": "node"}]},
    {"operator": "op", "args": [{"type": "node", "name": "op", "extra": 1}]},
    {"operator": "op", "args": [{"type": "path", "value": 42}]},
    {"operator": "op", "args": [{"type": "float", "value": 42}]},
    {"operator": "op", "args": [{"type": "tuple", "items": "bad"}]},
    {"operator": "op", "args": [{"type": "dict", "items": [["key"]]}]},
    {"operator": "op", "args": [{"type": "dict", "items": [[1, 2, 3]]}]},
    {"operator": "op", "kwargs": {"nested": [[{"type": "node", "name": 42}]]}},
])
def test_invalid_node_structure_is_rejected_before_runtime_creation(record: Any) -> None:
    class UnconstructedGraph(GraphRT):
        def __init__(self) -> None:
            pytest.fail("Malformed input must be rejected before constructing a runtime")

    data = {
        "version": 1,
        "_local_": "def op(): return 1",
        "imports": ["tools.py"],
        "graph": {"nodes": {"op": record}},
    }
    with pytest.raises(ValueError, match="Invalid graph format"):
        UnconstructedGraph.fromdict(data)


@pytest.mark.parametrize("value", [
    None, False, True, 0, 1, 1.0, "", [],
    {"type": "tuple", "items": []},
    {"type": "dict", "items": []},
    {"type": "dict", "items": [["empty", []], ["flag", False]]},
])
def test_input_validation_preserves_values_and_input_data(value: Any) -> None:
    data = {
        "version": 1,
        "graph": {"nodes": {"op": {
            "operator": "missing",
            "args": [value],
            "kwargs": {"value": value},
        }}},
    }
    original = copy.deepcopy(data)
    loaded = GraphRT.fromdict(data)
    assert data == original
    assert loaded.todict() == original


def test_runtime_accepts_document_positions_without_serializing_them() -> None:
    data = {
        "version": 1,
        "graph": {"nodes": {"op": {
            "operator": "missing",
            "position": [12, 34],
        }}},
    }
    original = copy.deepcopy(data)
    loaded = GraphRT.fromdict(data)
    assert data == original
    assert loaded.nodes()[0].get_name() == "op"
    assert "position" not in loaded.todict()["graph"]["nodes"]["op"]
