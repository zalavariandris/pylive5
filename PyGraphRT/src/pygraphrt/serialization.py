
from pathlib import Path
from .graph_rt import GraphRT
from .graph_rt import NodeRef, NodeData
from .graph_rt import OperatorRef, AbstractOperator

from .local_module import LocalModuleRT, FunctionOperator
from .script_module import ScriptModuleRT


def __to_str(obj):
    match obj:
        case NodeRef():
            return obj.get_name()
            
        case OperatorRef():
            return obj.get_name()
        
        case float() | int() | str() | bool():
            return str(obj)
        
        case _:
            return str(obj)

def __to_dict(obj, explicit: bool = False) -> dict:
    match obj:
        case GraphRT():
            return {
                'modules': {
                    __to_str(ref): __to_dict(ref, explicit)
                    for ref in obj.modules()
                },
                'nodes': {
                    __to_str(ref): __to_dict(ref.get_value(), explicit)
                    for ref in obj.nodes()
                }
            }
        case NodeData():
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

        case LocalModuleRT():
            # a a list of function definitions?
            ...

        case ScriptModuleRT():
            # embedded pythn script
            return {
                "type": "script",
                "source": obj.get_script()
            }

        # case ImportModule():
        #     # reference to an external file module
        #     return {
        #         "type": "import",
        #         "file": str(obj.file_binding.path()) if obj.file_binding.path() is not None else ""
        #     }


        

        case _:
            raise ValueError(f"Cannot serialize object of type {type(obj)}")

def _todict(graph: GraphRT, explicit: bool = False) -> str|dict:
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
    return json.dumps(_todict(obj, explicit), indent=4)

def deserialize(serialized: str) -> GraphRT:
    raise NotImplementedError("Deserialization is not implemented yet.") 