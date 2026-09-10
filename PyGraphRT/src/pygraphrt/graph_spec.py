from dataclasses import dataclass, field
from typing import Any

from pygraphrt.graph_rt import GraphRT


@dataclass
class NodeRef:
    name: str


@dataclass
class OperatorRef:
    name: str


@dataclass(frozen=True)
class OperatorSpec:
    source: str


@dataclass(frozen=True)
class NodeSpec:
    operator: str
    args: tuple = field(default_factory=tuple)
    kwargs: dict[str, Any] = field(default_factory=dict)


@dataclass
class GraphSpec:
    nodes: dict[NodeRef, NodeSpec]
    operators: dict[OperatorRef, OperatorSpec]
    output: NodeRef


def parse(script:str)->GraphSpec:
    ...

def evaluate(graph: GraphSpec) -> GraphRT:
    ...

def snapshot(runtime: GraphRT) -> GraphSpec:
    ...

def unparse(graph: GraphSpec) -> str:
    ...

def diff(graph1: GraphSpec, graph2: GraphSpec) -> str:
    ...
