
from pathlib import Path
from pygraphrt.graph_rt import GraphRT
from pygraphrt.node_rt import NodeRT

from pygraphrt.operator_rt_ref import OperatorRTRef

from pygraphrt.local_module_rt import LocalModuleRT
from pygraphrt.script_module_rt import ScriptModuleRT
from pygraphrt.import_module_rt import ImportModuleRT

def __to_str(obj):
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

def __to_dict(obj, explicit: bool = False) -> str|dict:
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
                "operator": __to_str(obj.get_operator())
            }
            args, kwargs = obj.get_inputs()
            if explicit or len(args) > 0:
                data["args"] = [
                    __to_str(val) 
                    for val in args
                ]
            if explicit or len(kwargs) > 0:
                data["kwargs"] = {
                    key: __to_str(val) 
                    for key, val in kwargs.items()
                }
            return data

        case GraphRT():
            return {
                'modules': {
                    __to_str(key): __to_dict(value, explicit)
                    for key, value in obj.modules().items()
                },
                'nodes': {
                    __to_str(key): __to_dict(value, explicit)
                    for key, value in obj.nodes().items()
                }
            }

        case int() | float() | str() | bool():
            return obj

        case _:
            raise ValueError(f"Cannot serialize object of type {type(obj)}")

def _to_dict(graph: GraphRT, explicit: bool = False) -> str|dict:
    return __to_dict(graph, explicit)

def _from_dict(graph: dict)-> GraphRT:
    G = GraphRT()
    for module in graph['modules']:
        # Implement logic to add modules to G
        pass

    for node in graph['nodes']:
        # Implement logic to add nodes to G
        
        G.node()(op)

    return G

import json
def serialize(obj, *, explicit: bool = False) -> str:
    return json.dumps(_to_dict(obj, explicit), indent=4)

def deserialize(serialized: str) -> GraphRT:
    raise NotImplementedError("Deserialization is not implemented yet.")