from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Literal, Callable, Generic, Hashable, Iterable, Mapping, Protocol, Set, TypeVar


from .base_engine import UNSET
from .graph import MutableGraph
from .observable_graph import ObservableGraph
from .changes import SetChanges, MappingChanges

NodeT = TypeVar("NodeT", bound=Hashable)
OperatorT = TypeVar("OperatorT", bound=Hashable)


@dataclass(frozen=True)
class GraphChange(Generic[NodeT]):
    """
    Independent changes to graph membership and per-node attributes.
    """
    nodes: SetChanges[NodeT] = field(default_factory=SetChanges)
    links: SetChanges[Link[NodeT]] = field(default_factory=SetChanges)
    attributes: Mapping[NodeT, MappingChanges[str, object]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "attributes", MappingProxyType(dict(self.attributes)))

class ObservableGraphProtocol(Protocol[NodeT]):
    def listen(self, callback: Callable[[GraphChange[NodeT]], None]) -> Callable[[], None]:
        ...

@dataclass(frozen=True)
class EngineChange(Generic[NodeT]):
    ...

class EngineGraphInterface(
    Generic[NodeT], 
    MutableGraph[NodeT], 
    ObservableGraphProtocol[NodeT], 
    Protocol[NodeT]
):...

class EngineProviderInterface(
    Generic[OperatorT], 
    ReadableProvider[OperatorT], 
    ObservableProvider[OperatorT], 
    Protocol[OperatorT]
): ...

class EngineInterface(Generic[NodeT, OperatorT], Protocol):
    def graph(self) -> EngineGraphInterface[NodeT]: ...
    def provider(self) -> EngineProviderInterface[OperatorT]: ...
    def set_script(self, script: str) -> None: ...
    def get_script(self) -> str: ...