from dataclasses import dataclass, field, fields, is_dataclass
import json
from typing import Any, Mapping

from pygraphrt.node_rt import NodeRT
from pygraphrt.operator_rt_ref import OperatorRTRef
from pygraphrt.script_module_rt import ScriptModuleRT


@dataclass(frozen=True)
class ModuleRef:
    name: str

    def __str__(self) -> str:
        return self.name

@dataclass(frozen=True)
class NodeRef:
    name: str

    def __str__(self) -> str:
        return self.name

@dataclass(frozen=True)
class OperatorRef:
    module: str
    name: str

    def __str__(self) -> str:
        return f"{self.module}.{self.name}"
    

type LiteralValue = None | bool | int | float | str
type Value = NodeRef | LiteralValue

@dataclass(frozen=True)
class NodeSpec:
    operator: OperatorRef | None
    args: tuple[Value, ...] = ()
    kwargs: dict[str, Value] = field(default_factory=dict)

    def todict(self) -> dict:
        return {
            "operator": str(self.operator) if self.operator is not None else None,
            "args": self.args,
            "kwargs": self.kwargs
        }

@dataclass(frozen=True)
class ScriptModuleSpec:
    script:str

@dataclass(frozen=True)
class GraphSpec:
    # modules: dict[ModuleRef, ModuleSpec]
    nodes: dict[NodeRef, NodeSpec]
    output: NodeRef | None

    def todict(self) -> dict:
        return {
            "nodes": {
                str(key): value.todict() 
                for key, value in self.nodes.items()
            },
            "output": str(self.output) if self.output is not None else None
        }



from pygraphrt.graph_rt import GraphRT
def snapshot_script_module(module: ScriptModuleRT) -> ScriptModuleSpec:
    return ScriptModuleSpec(script=module.get_script())

def snapshot(runtime: GraphRT) -> GraphSpec:
    """Snapshot node bindings and output; module definitions are not collected yet."""
    nodes = dict()
    for name, node in runtime.nodes().items():
        args, kwargs = node.get_inputs()

        resolved_args = tuple(
            NodeRef(name=arg.get_name()) if isinstance(arg, NodeRT) else arg
            for arg in args
        )
        resolved_kwargs = {
            key: NodeRef(name=value.get_name()) if isinstance(value, NodeRT) else value
            for key, value in kwargs.items()
        }

        def ref_from_operator(operator_rt: OperatorRTRef | None)->OperatorRef | None:
            if operator_rt:
                module = operator_rt.module
                if module is None:
                    raise ValueError(f"Operator {operator_rt.key()} has no module.")
                return OperatorRef(module=module.name(), name=operator_rt.key())
            else:
                return None

        nodes[NodeRef(name)] = NodeSpec(
            operator=ref_from_operator(node.get_operator()),
            args=resolved_args,
            kwargs=resolved_kwargs
        )

    return GraphSpec(
        modules={},
        nodes=nodes,
        output=NodeRef(runtime.output.get_name()) if runtime.output is not None else None
    )

def serialize(obj, explicit=False)->dict:
    match obj:
        case OperatorRef():
            return f"{obj.module}.{obj.name}"

        case NodeRef():
            return str(obj)
        
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

def parse(script:str)->GraphSpec:
    ...

def evaluate(graph: GraphSpec) -> GraphRT:
    ...


def deserialize(data: dict) -> GraphSpec:
    ...

@dataclass(frozen=True)
class GraphDiff:
    ...

def diff(graph1: GraphSpec, graph2: GraphSpec) -> GraphDiff:
    ...

def apply(graph: GraphRT, changes: GraphDiff):
    ...
    
