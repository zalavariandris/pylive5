"""Proposed source-preserving graph API; see docs/script_graph.md.

Conversion methods are deliberately unimplemented pending design review.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pygraphrt.imports_rt import ImportRT

if TYPE_CHECKING:
    from pygraphrt.graph_rt import GraphRT


class UnsupportedScriptError(ValueError):
    """Valid Python that cannot be represented by the supported graph subset."""


@dataclass(frozen=True)
class NodeRef:
    """Reference to a node result, distinguished from a literal string."""

    name: str


Literal = str | int | float | bool | None


@dataclass
class NodeSpec:
    operator: str
    args: tuple[Literal | NodeRef, ...] = ()
    kwargs: dict[str, Literal | NodeRef] = field(default_factory=dict)


@dataclass
class GraphSpec:
    """Temporary parse result or graph snapshot, never authoritative state."""

    imports: list[ImportRT] = field(default_factory=list)
    operators: dict[str, str] = field(default_factory=dict)
    nodes: dict[str, NodeSpec] = field(default_factory=dict)
    output: str | None = None


class ScriptGraph:
    """Python source adapter for an authoritative, existing GraphRT instance."""

    def __init__(self, graph: GraphRT):
        self._graph = graph

    @property
    def graph(self) -> GraphRT:
        """The live graph supplied by the caller; never replaced by the adapter."""
        return self._graph

    @staticmethod
    def parse(source: str) -> GraphSpec:
        """Parse and validate without executing imports or function bodies."""
        raise NotImplementedError

    @property
    def spec(self) -> GraphSpec:
        """Return a detached snapshot of the current live graph."""
        raise NotImplementedError

    def to_source(self) -> str:
        """Export the current graph, retaining source formatting where possible."""
        raise NotImplementedError

    def update_source(self, source: str) -> None:
        """Validate source, then mutate the existing graph between executions.

        Invalid edits leave the graph unchanged. Imports and definitions may
        execute during application; node calls must remain deferred. Trusted
        source only. Retain unaffected node identities and invalidate affected
        caches. Remember source formatting only after accepting the update.
        """
        raise NotImplementedError

    def apply_spec(self, spec: GraphSpec) -> None:
        """Validate a candidate and apply mutations to the existing live graph."""
        raise NotImplementedError
