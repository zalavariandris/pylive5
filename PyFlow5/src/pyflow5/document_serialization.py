"""Versioned document data. Runtime objects are built before any UI is changed.

Module IDs are independent of editable names. Dictionaries are tagged so literal
data cannot be mistaken for a node reference. Local Python functions and opaque
objects are rejected because their state cannot be reconstructed from JSON.
"""
import math
from pathlib import Path

from pygraphrt.abstract_module_rt import OperatorRef
from pygraphrt.graph_rt import GraphRT, NodeRef
from pygraphrt.import_module import ImportModuleRT
from pygraphrt.script_module import ScriptModuleRT


def _encode_value(value, nodes):
    if type(value) in (type(None), bool, int, str):
        return value
    if type(value) is float:
        return value if math.isfinite(value) else {"type": "float", "value": value.hex()}
    if isinstance(value, NodeRef):
        if value not in nodes:
            raise ValueError(f"Input references a node outside this graph: {value}")
        return {"type": "node", "name": value.get_name()}
    if type(value) is list:
        return [_encode_value(item, nodes) for item in value]
    if type(value) is tuple:
        return {"type": "tuple", "items": [_encode_value(item, nodes) for item in value]}
    if type(value) is dict:
        return {"type": "dict", "items": [
            [_encode_value(key, nodes), _encode_value(item, nodes)]
            for key, item in value.items()
        ]}
    if isinstance(value, Path):
        return {"type": "path", "value": str(value)}
    raise TypeError(f"Cannot save input of type {type(value).__name__}")


def _decode_value(value, nodes):
    if type(value) in (type(None), bool, int, float, str):
        return value
    if isinstance(value, list):
        return [_decode_value(item, nodes) for item in value]
    if not isinstance(value, dict):
        raise ValueError("Invalid input value")
    match value:
        case {"type": "node", "name": str(name)}:
            if name not in nodes:
                raise ValueError(f"Unknown node reference: {name}")
            return nodes[name]
        case {"type": "tuple", "items": list(items)}:
            return tuple(_decode_value(item, nodes) for item in items)
        case {"type": "dict", "items": list(items)}:
            return {_decode_value(key, nodes): _decode_value(item, nodes) for key, item in items}
        case {"type": "path", "value": str(path)}:
            return Path(path)
        case {"type": "float", "value": str(number)}:
            return float.fromhex(number)
    raise ValueError(f"Invalid tagged input: {value!r}")


def to_dict(graph, modules, positions):
    module_ids = {module: f"module_{i}" for i, module in enumerate(modules)}
    data = {"version": 1, "modules": {}, "nodes": {}}
    for module, module_id in module_ids.items():
        if not isinstance(module, ScriptModuleRT):
            raise TypeError(f"Cannot save module {module.get_name()!r}: only script modules are supported")
        record = {"type": "script", "name": module.get_name(), "source": module.get_script()}
        if isinstance(module, ImportModuleRT):
            record.update(type="import", path=str(module.path()))
        data["modules"][module_id] = record

    nodes = set(graph.nodes())
    for node in graph.nodes():
        name = node.get_name()
        if not isinstance(name, str):
            raise TypeError("Saved node names must be strings")
        operator = node.get_operator()
        if operator.module not in module_ids:
            raise ValueError(f"Node {name!r} uses a module outside the document; move its operator into a script module")
        args, kwargs = node.get_inputs()
        data["nodes"][name] = {
            "operator": {"module": module_ids[operator.module], "name": operator.name},
            "args": [_encode_value(value, nodes) for value in args],
            "kwargs": {key: _encode_value(value, nodes) for key, value in kwargs.items()},
            "position": list(positions[name]),
        }
    return data


def from_dict(data):
    if not isinstance(data, dict) or type(data.get("version")) is not int or data["version"] != 1:
        raise ValueError("Unsupported document format; expected version 1. Older files lack typed inputs and module references.")
    if not isinstance(data.get("modules"), dict) or not isinstance(data.get("nodes"), dict):
        raise ValueError("Document modules and nodes must be objects")

    modules = {}
    for module_id, record in data["modules"].items():
        if not isinstance(module_id, str) or not isinstance(record, dict):
            raise ValueError("Invalid module record")
        name, source = record.get("name"), record.get("source")
        if not isinstance(name, str) or not isinstance(source, str):
            raise ValueError("Module name and source must be strings")
        if record.get("type") == "script":
            module = ScriptModuleRT(name, source)
        elif record.get("type") == "import" and isinstance(record.get("path"), str):
            module = ImportModuleRT(record["path"], source=source)
            module.set_name(name)
        else:
            raise ValueError(f"Invalid module type for {module_id!r}")
        # Invalid scripts are editable document state; preserve their source.
        modules[module_id] = module

    graph = GraphRT()
    nodes, positions = {}, {}
    for name, record in data["nodes"].items():
        if not isinstance(name, str) or not isinstance(record, dict):
            raise ValueError("Invalid node record")
        operator = record.get("operator")
        if (not isinstance(operator, dict) or not isinstance(operator.get("module"), str)
                or operator["module"] not in modules or not isinstance(operator.get("name"), str)):
            raise ValueError(f"Invalid operator reference for node {name!r}")
        position = record.get("position", [0, 0])
        if (not isinstance(position, (list, tuple)) or len(position) != 2
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in position)):
            raise ValueError(f"Invalid position for node {name!r}")
        positions[name] = tuple(position)
        ref = OperatorRef(modules[operator["module"]], operator["name"])
        nodes[name] = graph.node()(ref, name=name)

    # All nodes exist before wiring inputs, including forward references.
    for name, record in data["nodes"].items():
        args, kwargs = record.get("args", []), record.get("kwargs", {})
        if not isinstance(args, list) or not isinstance(kwargs, dict) or any(not isinstance(k, str) for k in kwargs):
            raise ValueError(f"Invalid inputs for node {name!r}")
        nodes[name].set_inputs(
            *[_decode_value(value, nodes) for value in args],
            **{key: _decode_value(value, nodes) for key, value in kwargs.items()},
        )
    return graph, list(modules.values()), positions
