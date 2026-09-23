"""Validation of the version 1 graph file structure."""

from schema import And, Optional, Or, Schema, SchemaError


def _validate_input(value: object) -> bool:
    """Allow the input schema to refer recursively to itself."""
    INPUT_SCHEMA.validate(value)
    return True


INPUT_SCHEMA: Schema = Schema(Or(
    None, bool, int, float, str,
    [_validate_input],
    {"type": "node", "name": str},
    {"type": "tuple", "items": [_validate_input]},
    {
        "type": "dict",
        "items": [And([_validate_input], lambda pair: len(pair) == 2)],
    },
    {"type": "path", "value": str},
    {"type": "float", "value": str},
))

NODE_SCHEMA: Schema = Schema({
    "operator": Or(str, {"module": str, "name": str}),
    Optional("args"): [_validate_input],
    Optional("kwargs"): {Optional(str): _validate_input},
    # PyFlow stores positions here and validates them in the document layer.
    Optional("position"): object,
})

GRAPH_SCHEMA: Schema = Schema({
    "version": And(int, lambda value: type(value) is int and value == 1),
    Optional("_local_"): str,
    Optional("imports"): [And(str, lambda path: bool(path) and path != "_local_")],
    Optional("graph"): {"nodes": {Optional(str): NODE_SCHEMA}},
})


def validate_graph_data(data: object) -> None:
    """Reject malformed data without constructing or executing a runtime."""
    try:
        GRAPH_SCHEMA.validate(data)
    except SchemaError as error:
        # Keep GraphRT.fromdict's existing public exception type.
        raise ValueError(f"Invalid graph format: {error}") from error
