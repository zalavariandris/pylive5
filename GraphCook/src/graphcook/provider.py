from typing import Callable, Any, Iterable, Protocol, Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class OperatorHandle:
    name: str


class UnresolvedOperatorError(LookupError):
    pass


@dataclass(frozen=True)
class ProviderChange:
    added: tuple[OperatorHandle, ...] = ()
    removed: tuple[OperatorHandle, ...] = ()
    changed: tuple[OperatorHandle, ...] = ()
    unknown: bool = False


class ProviderSnapshot:
    def __init__(self, operators: Mapping[OperatorHandle, Any]) -> None:
        self._operators = dict(operators)

    def resolve(self, handle: OperatorHandle) -> Any:
        try:
            return self._operators[handle]
        except KeyError:
            raise UnresolvedOperatorError(f"Missing operator: {handle.name}") from None


class OperatorProvider(Protocol):
    def operators(self) -> Iterable[OperatorHandle]: ...
    def resolve(self, handle: OperatorHandle) -> Any: ...
    def listen(self, callback: Callable[[ProviderChange], None]) -> Callable[[], None]: ...
