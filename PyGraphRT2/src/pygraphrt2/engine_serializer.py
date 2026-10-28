"""Serialize a graph and its single script module using format version 4."""

import math
from pathlib import Path
from typing import Any, Callable

from .graph import Graph, NodeRef
from .inline_scriptmodule import InlineScriptModule, ScriptOperatorRef


def _encode_value(value: Any) -> Any:
    if type(value) in (type(None), bool, int, str):
        return value

    if type(value) is float:
        return value if math.isfinite(value) else {"type": "float", "value": value.hex()}

    if type(value) is list:
        return [_encode_value(item) for item in value]

    if type(value) is tuple:
        return {"type": "tuple", "items": [_encode_value(item) for item in value]}

    if type(value) is dict:
        return {
            "type": "dict",
            "items": [
                [_encode_value(key), _encode_value(item)]
                for key, item in value.items()
            ],
        }

    if isinstance(value, Path):
        return {"type": "path", "value": str(value)}

    raise TypeError(f"Cannot save input of type: {type(value).__name__!r}")


def _decode_value(value: Any) -> Any:
    if type(value) in (type(None), bool, int, float, str):
        return value

    if isinstance(value, list):
        return [_decode_value(item) for item in value]

    if not isinstance(value, dict):
        raise ValueError("Invalid input value")

    match value:
        case {"type": "tuple", "items": list(items)}:
            return tuple(_decode_value(item) for item in items)

        case {"type": "dict", "items": list(items)}:
            return {_decode_value(key): _decode_value(item) for key, item in items}

        case {"type": "path", "value": str(path)}:
            return Path(path)

        case {"type": "float", "value": str(number)}:
            return float.fromhex(number)

    raise ValueError(f"Invalid tagged input: {value!r}")


def _encode_input(value: Any) -> dict[str, Any]:
    if isinstance(value, NodeRef):
        return {"type": "node", "name": value.name()}

    return {"type": "literal", "value": _encode_value(value)}


def _decode_input(data: dict[str, Any], nodes: dict[str, NodeRef]) -> Any:
    match data["type"]:
        case "node":
            return nodes[data["name"]]
        case "literal":
            return _decode_value(data["value"])
        case _:
            raise ValueError(f"Unsupported input type: {data['type']!r}")


class GraphSerializer:
    def __init__(self, graph: Graph, registry: InlineScriptModule) -> None:
        self.graph = graph
        self.registry = registry

    def _get_operator_pointer(self, operator: Callable[..., Any]) -> str:
        if not isinstance(operator, ScriptOperatorRef):
            raise TypeError("Only script operator references can be saved")

        if operator.module() is not self.registry:
            raise ValueError("The operator belongs to a different script module")

        return operator.name()

    def _node_todict(
        self,
        node: NodeRef,
        explicit: bool = False,
    ) -> dict[str, Any]:
        state = node.resolve()
        data: dict[str, Any] = {}

        if state.operator is not None:
            data["operator"] = self._get_operator_pointer(state.operator)
        elif explicit:
            data["operator"] = None

        if state.args or explicit:
            data["args"] = [_encode_input(value) for value in state.args]

        if state.kwargs or explicit:
            data["kwargs"] = {
                name: _encode_input(value)
                for name, value in state.kwargs.items()
            }

        return data

    def todict(self, explicit: bool = False) -> dict[str, Any]:
        """Save source, operator names, and inputs; optionally include empty fields."""
        return {
            "version": 4,
            "script": {
                "name": self.registry.name(),
                "source": self.registry.get_script(),
            },
            "graph": {
                "nodes": {
                    node.name(): self._node_todict(node, explicit)
                    for node in self.graph.nodes()
                },
            },
        }


class GraphDeserializer:
    def fromdict(self, data: dict[str, Any]) -> tuple[InlineScriptModule, Graph]:
        """Restore the script module and graph, retaining missing operator names."""
        version = data.get("version")
        if type(version) is not int or version != 4:
            raise ValueError("Unsupported graph format; expected version 4")

        script = data["script"]
        if not isinstance(script, dict) or not isinstance(script.get("source"), str):
            raise ValueError("Script must contain a source string")
        if script.get("name") is not None and not isinstance(script["name"], str):
            raise ValueError("Script name must be a string or None")
        registry = InlineScriptModule(script.get("name"))
        registry.set_script(script["source"])
        try:
            registry.evaluate()
        except Exception as error:
            # A document with a broken script must still reopen for repair.
            # Only tolerate errors recorded by script evaluation itself.
            if registry.get_state() is not error:
                raise

        graph = Graph()
        records = data["graph"].get("nodes", {})

        # Create every node before restoring connections.
        nodes = {
            name: graph._create_node(name=name)
            for name in records
        }

        for name, record in records.items():
            operator_name = record.get("operator")
            operator = None

            if operator_name is not None:
                if not isinstance(operator_name, str):
                    raise ValueError(f"Invalid operator name: {operator_name!r}")

                # Keep the name even when the script currently lacks this function.
                operator = ScriptOperatorRef(registry, operator_name)

            args = tuple(
                _decode_input(value, nodes)
                for value in record.get("args", [])
            )
            kwargs = {
                inlet: _decode_input(value, nodes)
                for inlet, value in record.get("kwargs", {}).items()
            }

            graph._update_node(nodes[name], operator, args, kwargs)

        return registry, graph
