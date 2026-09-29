from typing import ClassVar, Any, Mapping
import abc
from dataclasses import dataclass


@dataclass(frozen=True)
class ParameterData:
    _empty:ClassVar = object()
    name:str
    annotation:type = _empty
    default: Any = _empty

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
    