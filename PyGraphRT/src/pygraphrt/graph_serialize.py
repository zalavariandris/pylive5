
from pathlib import Path
from pygraphrt.graph_rt import GraphRT
from pygraphrt.graph_spec import OperatorRef, NodeRef, NodeSpec, GraphSpec
from pygraphrt.script_module_rt import ScriptModuleRT
from pygraphrt.import_module_rt import ImportModuleRT

def serialize(obj, explicit: bool = False) -> str|dict:
    match obj:
        case OperatorRef():
            return f"{obj.module}.{obj.name}"

        case NodeRef():
            return str(obj)

        case ScriptModuleRT():
            return {
                "source": obj.get_script()
            }
        case ImportModuleRT():
            return {
                "file": str(obj.file_binding.path()) if obj.file_binding.path() is not None else ""
            }
        case NodeSpec():
            return {
                "operator": serialize(obj.operator, explicit),
                "args": [
                    serialize(arg, explicit) 
                    for arg in obj.args
                ],
                "kwargs": {
                    serialize(key, explicit): serialize(value, explicit) 
                    for key, value in obj.kwargs.items()
                }
            }

        case GraphSpec():
            return {
                'nodes': {
                    serialize(key, explicit): serialize(value, explicit)
                    for key, value in obj.nodes.items()
                }
            }

        case int() | float() | str() | bool():
            return obj

        case _:
            raise ValueError(f"Cannot serialize object of type {type(obj)}")