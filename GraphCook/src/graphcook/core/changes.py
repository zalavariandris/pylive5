from typing import  Generic, TypeVar, Hashable, Mapping, Callable
from dataclasses import dataclass, field
from types import MappingProxyType
from dataclasses import dataclass, field

KeyT = TypeVar("KeyT", bound=Hashable)
ValueT = TypeVar("ValueT")


@dataclass(frozen=True)
class SetChanges(Generic[ValueT]):
    """Membership changes in an unordered collection."""
    added: set[ValueT] = field(default_factory=set)
    removed: set[ValueT] = field(default_factory=set)


@dataclass(frozen=True)
class ValueChange(Generic[ValueT]):
    old: ValueT
    new: ValueT


@dataclass(frozen=True)
class MappingChanges(Generic[KeyT, ValueT]):
    """Key additions/removals and value replacements in a mapping."""
    added: Mapping[KeyT, ValueT] = field(default_factory=dict)
    removed: Mapping[KeyT, ValueT] = field(default_factory=dict)
    changed: Mapping[KeyT, ValueChange[ValueT]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Make snapshots of the delta mappings, not just their dataclass fields.
        for name in ("added", "removed", "changed"):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))
