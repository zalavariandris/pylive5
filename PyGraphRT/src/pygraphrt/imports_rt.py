
class ImportRT:
    def __init__(self, module:str, name:str | None = None, alias:str | None = None):
        assert isinstance(module, str), "module must be a string"
        assert name is None or isinstance(name, str), "name must be a string or None"
        assert alias is None or isinstance(alias, str), "alias must be a string or None"
        self._module = module
        self._name = name
        self._alias = alias

    def __repr__(self) -> str:
        return f"ModuleRT(module={self._module!r}, name={self._name!r}, alias={self._alias!r})"

    def __str__(self):
        text = ""
        if self._module:
            text += f"import {self._module}"
        if self._name:
            text += f" from {self._module} import {self._name}"
        if self._alias:
            text += f" as {self._alias}"
        return f"RT('{text}')"
    
    def __hash__(self) -> int:
        return hash((self._module, self._name, self._alias))

    def __eq__(self, value):
        return (
            isinstance(value, ImportRT)
            and self._module == value._module
            and self._name == value._name
            and self._alias == value._alias
        )
    
import ast
def imports_from_script(script: str) -> list[ImportRT]:
    """Extract top-level imports in source order without executing the script.

    Imports inside functions, classes, or control-flow blocks are omitted so
    that local or conditional imports are not turned into unconditional ones.
    Invalid Python syntax raises SyntaxError.
    """
    modules: list[ImportRT] = []
    for statement in ast.parse(script).body:
        if isinstance(statement, ast.Import):
            for imported in statement.names:
                modules.append(ImportRT(module=imported.name, alias=imported.asname))

        elif isinstance(statement, ast.ImportFrom):
            module = "." * statement.level + (statement.module or "")
            for imported in statement.names:
                modules.append(
                    ImportRT(module=module, name=imported.name, alias=imported.asname)
                )
    return modules

def __module_to_import_statement(module: ImportRT) -> str:
    if module._name:
        statement = f"from {module._module} import {module._name}"
    else:
        statement = f"import {module._module}"
    if module._alias:
        statement += f" as {module._alias}"
    return statement

def imports_to_script(modules: list[ImportRT]) -> str:
    """Join import statements in input order, preserving duplicate imports."""
    return "\n".join(__module_to_import_statement(module) for module in modules)
