
from pathlib import Path
from pygraphrt.graph_rt import GraphRT
from pygraphrt.node_rt import NodeRT

from pygraphrt.operator_rt_ref import OperatorRTRef

from pygraphrt.local_module_rt import LocalModuleRT
from pygraphrt.script_module_rt import ScriptModuleRT
from pygraphrt.import_module_rt import ImportModuleRT

def _to_str(obj):
    match obj:
        case OperatorRTRef():
            if module:=obj.module():
                return f"{module.name()}.{obj.name()}"
            else:
                return f"{obj.name()}"
            
        case NodeRT():
            return obj.get_name()
        
        case float() | int() | str() | bool():
            return str(obj)
        
        case _:
            return str(obj)

def _to_dict(obj, explicit: bool = False) -> str|dict:
    match obj:
        case OperatorRTRef():
            if module:=obj.module():
                return f"{module.name()}.{obj.name()}"
            else:
                return f"{obj.name()}"

        case LocalModuleRT():
            return {
                "source": obj.get_script()
            }
        
        case ScriptModuleRT():
            return {
                "source": obj.get_script()
            }
        case ImportModuleRT():
            return {
                "file": str(obj.file_binding.path()) if obj.file_binding.path() is not None else ""
            }
        case NodeRT():
            data = {
                "operator": _to_str(obj.get_operator())
            }
            args, kwargs = obj.get_inputs()
            if explicit or len(args) > 0:
                data["args"] = [
                    _to_str(val) 
                    for val in args
                ]
            if explicit or len(kwargs) > 0:
                data["kwargs"] = {
                    key: _to_str(val) 
                    for key, val in kwargs.items()
                }
            return data

        case GraphRT():
            return {
                'nodes': {
                    _to_str(key): _to_dict(value, explicit)
                    for key, value in obj.nodes().items()
                }
            }

        case int() | float() | str() | bool():
            return obj

        case _:
            raise ValueError(f"Cannot serialize object of type {type(obj)}")

def _from_dict(data: dict):
    # Implement deserialization logic here
    raise NotImplementedError("Deserialization is not yet implemented.")

import json
def serialize(obj, *, explicit: bool = False) -> str:
    return json.dumps(_to_dict(obj, explicit), indent=4)