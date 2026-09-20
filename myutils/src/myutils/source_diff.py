import ast
from typing import Any
from dataclasses import dataclass
from textwrap import dedent

@dataclass
class FunctionsDiff:
    changed: set[str]
    unchanged: set[str]
    added: set[str]
    removed: set[str]


def ast_functions_diff(source_before: str, source_after: str) -> FunctionsDiff:
    """Classify qualified function names by structural AST changes.

    Formatting, comments, and source positions are ignored. Signatures,
    decorators, docstrings, and nested definitions are included. This is a
    structural approximation of behavior: changes to globals or dependencies
    are not tracked, and equivalent expressions may be reported as changed.
    Repeated definitions in the same scope are compared in source order.
    
    Invalid Python is treated as having no function definitions; the syntax error
    is printed rather than raised.
    """
    def collect_functions(source: str) -> dict[str, list[str]]:
        """Collect function definitions from the source code."""
        definitions: dict[str, list[str]] = {}
        scope: list[str] = []

        class Collector(ast.NodeVisitor):
            def visit_ClassDef(self, node: ast.ClassDef) -> None:
                scope.append(node.name)
                self.generic_visit(node)
                scope.pop()

            def visit_FunctionDef(
                self, node: ast.FunctionDef | ast.AsyncFunctionDef
            ) -> None:
                scope.append(node.name)
                name = ".".join(scope)
                definitions.setdefault(name, []).append(
                    ast.dump(node, include_attributes=False)
                )
                self.generic_visit(node)
                scope.pop()

            visit_AsyncFunctionDef = visit_FunctionDef
        try:
            module = ast.parse(source) 
            Collector().visit(module)
        except SyntaxError as error:
            print(f"Syntax error in source: {error}")

        return definitions

    before = collect_functions(source_before)
    after = collect_functions(source_after)
    added = after.keys() - before.keys()
    removed = before.keys() - after.keys()
    common = before.keys() & after.keys()
    changed = {name for name in common if before[name] != after[name]}
    print(dedent(f"""\
    AST Diff:
        Added: {added}
        Removed: {removed}
        Changed: {changed}
        Unchanged: {common - changed}
    """))
    return FunctionsDiff(
        changed=changed,
        unchanged=common - changed,
        added=added,
        removed=removed,
    )