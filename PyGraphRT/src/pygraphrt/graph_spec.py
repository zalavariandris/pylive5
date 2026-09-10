from dataclasses import dataclass, field
from typing import Any, Mapping





@dataclass(frozen=True)
class ModuleRef:
    name: str

@dataclass(frozen=True)
class NodeRef:
    name: str

@dataclass(frozen=True)
class OperatorRef:
    name: str

@dataclass(frozen=True)
class ImportSpec:
    path: str
    module: str
    alias: str

@dataclass(frozen=True)
class OperatorSpec:
    imports: tuple[ImportSpec, ...]
    source: str

@dataclass(frozen=True)
class ModuleSpec:
    operators: Mapping[OperatorRef, OperatorSpec]


type LiteralValue = None | bool | int | float | str
type Value = NodeRef | LiteralValue

@dataclass(frozen=True)
class NodeSpec:
    operator: OperatorRef
    args: tuple[Value, ...] = ()
    kwargs: Mapping[str, Value] = field(default_factory=dict)


@dataclass(frozen=True)
class GraphSpec:
    modules: Mapping[ModuleRef, ModuleSpec]
    nodes: Mapping[NodeRef, NodeSpec]
    output: NodeRef


from pygraphrt.graph_rt import GraphRT
def parse(script:str)->GraphSpec:
    ...

def evaluate(graph: GraphSpec) -> GraphRT:
    ...

def snapshot(runtime: GraphRT) -> GraphSpec:
    ...

def unparse(graph: GraphSpec) -> str:
    ...

@dataclass(frozen=True)
class GraphDiff:
    ...

def diff(graph1: GraphSpec, graph2: GraphSpec) -> GraphDiff:
    ...

def apply(graph: GraphRT, changes: GraphDiff):
    ...
    