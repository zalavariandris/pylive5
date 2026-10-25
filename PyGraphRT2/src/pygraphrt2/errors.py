"""Errors reported by script modules."""


class ModuleError(Exception):
    """Base class for script module errors."""


class ScriptSyntaxError(ModuleError):
    """The script could not be compiled."""


class ScriptEvaluationError(ModuleError):
    """The script could not be evaluated."""
