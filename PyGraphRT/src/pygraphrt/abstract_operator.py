from typing import ClassVar, Any, Mapping
import abc
import inspect
from dataclasses import dataclass


@dataclass(frozen=True)
class ParameterData:
    EMPTY: ClassVar[Any] = inspect.Parameter.empty
    _empty: ClassVar[Any] = EMPTY  # Compatibility for existing callers.
    name:str
    annotation: Any = EMPTY
    default: Any = EMPTY

    def __repr__(self):
        return f"ParameterData(name='{self.name}', annotation={self.annotation}, default={self.default})"

    
class AbstractOperator(abc.ABC):
    def __init__(self):
        ...

    @abc.abstractmethod
    def fingerprint(self) -> int:
        pass

    @abc.abstractmethod
    def get_parameters(self) -> Mapping[str, ParameterData]:
        pass

    @abc.abstractmethod
    def get_return_type(self) -> type:
        pass

    @abc.abstractmethod
    def get_name(self) -> str:
        pass

    @abc.abstractmethod
    def __call__(self, *args, **kwargs) -> Any:
        pass
    
