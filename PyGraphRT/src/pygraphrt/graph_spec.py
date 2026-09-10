from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ImportSpec:
    path: str
    module: str
    alias: str


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
class ModuleSpec:
    operators: dict[OperatorRef, OperatorSpec]

@dataclass(frozen=True)
class OperatorSpec:
    imports: list[ImportSpec]
    source: str

@dataclass(frozen=True)
class NodeSpec:
    operator: OperatorRef
    args: tuple = field(default_factory=tuple)
    kwargs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GraphSpec:
    modules: dict[ModuleRef, ModuleSpec]
    nodes: dict[NodeRef, NodeSpec]
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
