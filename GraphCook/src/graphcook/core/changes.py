from collections.abc import Callable, Hashable, Mapping
from typing import Any, Generic, Literal, Required, TypeVar, TypedDict

ValueT = TypeVar("ValueT")


class SetChanges[T: Hashable](TypedDict, total=False):
    kind: Required[Literal["set"]]
    added: set[T]
    removed: set[T]


class ValueChange[ValueT](TypedDict):
    kind: Literal["value"]
    old: ValueT
    new: ValueT


class MappingChanges[K: Hashable, V, U](TypedDict, total=False):
    """Complete values for membership changes; patches of type U for updates.

    U may be a ValueChange, SetChanges, MappingChanges, or a union of these.
    A kind-only change is a no-op; the operation groups must be disjoint.
    """

    kind: Required[Literal["map"]]
    added: dict[K, V]
    removed: dict[K, V]
    updated: dict[K, U]


type Change = ValueChange[Any] | SetChanges[Any] | MappingChanges[Any, Any, Change]


def apply_change(target: object, change: Change) -> object:
    """Apply a tagged patch without mutating the target.

    Copy changed containers, sharing untouched values and supplied payloads.
    Membership must match the patch; old values are history, not equality guards.
    """
    match change["kind"]:
        case "value":
            return change["new"]
        case "set":
            if not isinstance(target, (set, frozenset)):
                raise TypeError("A set change requires a set target")
            set_added = change.get("added", set())
            set_removed = change.get("removed", set())
            if set_added & set_removed:
                raise ValueError("A member cannot be both added and removed")
            if set_added & target or not set_removed <= target:
                raise ValueError("Set membership does not match the change")
            return (target - set_removed) | set_added
        case "map":
            if not isinstance(target, Mapping):
                raise TypeError("A mapping change requires a mapping target")
            added = change.get("added", {})
            removed = change.get("removed", {})
            updated = change.get("updated", {})
            if (added.keys() & removed.keys()
                    or added.keys() & updated.keys()
                    or removed.keys() & updated.keys()):
                raise ValueError("Mapping change groups must have disjoint keys")
            if added.keys() & target.keys():
                raise ValueError("An added key already exists")
            if not (removed.keys() | updated.keys()) <= target.keys():
                raise KeyError("A removed or updated key does not exist")
            result = dict(target)
            for key in removed:
                del result[key]
            result.update(added)
            for key, update in updated.items():
                result[key] = apply_change(target[key], update)
            return result
        case _:
            raise ValueError(f"Unknown change kind: {change['kind']!r}")


# Observable data structures
class ObservableValue(Generic[ValueT]):
    def __init__(self, value: ValueT) -> None:
        self._value = value
        self._listeners: list[Callable[[ValueChange[ValueT]], None]] = []

    def get(self) -> ValueT:
        return self._value

    def set(self, value: ValueT) -> None:
        old_value = self._value
        self._value = value
        for listener in tuple(self._listeners):
            listener(ValueChange(kind="value", old=old_value, new=value))

    def listen(self, callback: Callable[[ValueChange[ValueT]], None]) -> Callable[[], None]:
        self._listeners.append(callback)

        def unsubscribe() -> None:
            self._listeners.remove(callback)

        return unsubscribe
