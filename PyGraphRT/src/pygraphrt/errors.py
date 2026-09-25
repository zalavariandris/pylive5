# MODULE ERRORS
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .graph_rt import NodeRef
    from .graph_rt import OperatorRef
    from .abstract_module_rt import AbstractModuleRef

class ModuleError(Exception):
    """Base class for all module-related errors."""
    def __init__(self, msg:str="", module: AbstractModuleRef|None = None):
        assert module is None or isinstance(module, AbstractModuleRef), "module must be an instance of AbstractModuleRef or None"
        self.module = module
        if msg is None:
            msg = f"Error in module: {module}"
        super().__init__(msg)




class ScriptSyntaxError(ModuleError):
    """The script contains a syntax error."""

class ScriptEvaluationError(ModuleError):
    """The script could not be compiled, executed, or inspected."""

class ImportModuleNotFoundError(ModuleError):
    """Raised when an import module cannot be found."""

# GRAPH ERRORS
class GraphExecutionError(Exception):
    """Base class for all graph-related errors.""" 
    def __init__(self, msg:str|None=None, node: NodeRef|None=None) -> None:
        self.node = node
        if msg is None:
            msg = "Error occured during Graph Execution."

        super().__init__(
            f"{msg} "
            f"Node {node.get_name()!r} failed during execution: "
        )

class GraphValidateError(GraphExecutionError):
    """Raised when graph validation fails."""
    pass

class GraphPreparationError(GraphExecutionError):
    """Raised when an error occurs during graph preparation."""
    pass



# these errors are invalid api use. 
# maybe these should be caught during graph construction
# rather than execution, and treated differently
class NodeNameCollisionError(GraphExecutionError):
    pass

class OperatorNameCollisionError(GraphExecutionError):
    pass

class DuplicateNodeError(GraphExecutionError):
    pass