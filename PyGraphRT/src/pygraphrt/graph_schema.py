"""Validate the modules/graph document without loading or executing modules."""

from collections.abc import Iterator
import math
from typing import Any

from schema import And, Optional, Or, Schema, SchemaError


def _validate_input(value: object) -> bool:
    """Allow the input schema to refer recursively to itself."""
    INPUT_SCHEMA.validate(value)
    return True


def _is_hashable_input(value: Any) -> bool:
    """Reject dictionary keys that would decode to lists or dictionaries."""
    if isinstance(value, list):
        return False
    if isinstance(value, dict):
        if value["type"] == "dict":
            return False
        if value["type"] == "tuple":
            return all(_is_hashable_input(item) for item in value["items"])
    return True


NAME_SCHEMA = And(str, lambda value: bool(value.strip()))

INPUT_SCHEMA: Schema = Schema(Or(
    None, bool, int, And(float, math.isfinite), str,
    [_validate_input],
    {"type": "node", "name": NAME_SCHEMA},
    {"type": "tuple", "items": [_validate_input]},
    {
        "type": "dict",
        "items": [And(
            [_validate_input],
            lambda pair: len(pair) == 2,
            lambda pair: _is_hashable_input(pair[0]),
        )],
    },
    {"type": "path", "value": str},
    {"type": "float", "value": Or("inf", "-inf", "nan")},
))

MODULE_SCHEMA: Schema = Schema(Or(
    {"type": "embedded", "source": str},
    {"type": "import", "path": NAME_SCHEMA},
))

NODE_SCHEMA: Schema = Schema({
    "operator": {"module": NAME_SCHEMA, "name": NAME_SCHEMA},
    Optional("args"): [_validate_input],
    Optional("kwargs"): {Optional(str): _validate_input},
    # PyFlow owns node positions and validates them in the document layer.
    Optional("position"): object,
})

GRAPH_SCHEMA: Schema = Schema({
    "modules": {Optional(NAME_SCHEMA): MODULE_SCHEMA},
    "graph": {"nodes": {Optional(NAME_SCHEMA): NODE_SCHEMA}},
})


def _node_references(value: Any) -> Iterator[str]:
    """Find references inside an already validated encoded input."""
    if isinstance(value, list):
        for item in value:
            yield from _node_references(item)
    elif isinstance(value, dict):
        if value["type"] == "node":
            yield value["name"]
        elif "items" in value:
            yield from _node_references(value["items"])


def validate_graph_data(data: object) -> None:
    """Check document structure and references before constructing a runtime."""
    try:
        document = GRAPH_SCHEMA.validate(data)
    except SchemaError as error:
        raise ValueError(f"Invalid graph format: {error}") from error

    modules = document["modules"]
    nodes = document["graph"]["nodes"]
    if "_local_" in modules and modules["_local_"]["type"] != "embedded":
        raise ValueError("Module '_local_' must be embedded")

    for name, record in nodes.items():
        module = record["operator"]["module"]
        if module not in modules:
            raise ValueError(f"Node {name!r} references unknown module {module!r}")
        inputs = [*record.get("args", []), *record.get("kwargs", {}).values()]
        for reference in _node_references(inputs):
            if reference not in nodes:
                raise ValueError(f"Node {name!r} references unknown node {reference!r}")
