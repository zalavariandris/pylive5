import ast
import symtable

import pytest


def build_dependency_graph(source: str) -> dict[str, set[str]]:
    """Return direct lexical dependencies as ``scope -> referenced bindings``.

    Module bindings use plain names; nested bindings use qualified names such
    as ``outer.inner`` or ``outer.value``. Every target has a graph entry, even
    if it has no dependencies. Unresolved globals (including builtins) use the
    ``<external>.`` prefix. The module scope is named ``<module>``.

    Symbol tables parse the source without executing it and resolve locals,
    globals, and closure captures. References to parameters and local variables
    are retained as leaf nodes. Imports remain local bindings; attribute targets,
    runtime aliases, and assignment data flow are not resolved. Defaults and
    decorators belong to the scope evaluating them, not the function body.
    Edges indicate potential dependencies, not proven behavioral changes.
    """
    module = symtable.symtable(source, "<source>", "exec")
    graph: dict[str, set[str]] = {}

    def binding_name(scope_name: str, name: str) -> str:
        return name if scope_name == "<module>" else f"{scope_name}.{name}"

    def bound(table: symtable.SymbolTable, name: str) -> bool:
        try:
            symbol = table.lookup(name)
        except KeyError:
            return False
        return symbol.is_local() or symbol.is_parameter() or symbol.is_imported()

    def visit(
        table: symtable.SymbolTable,
        scope_name: str,
        ancestors: list[tuple[symtable.SymbolTable, str]],
    ) -> None:
        dependencies = graph.setdefault(scope_name, set())
        for symbol in table.get_symbols():
            name = symbol.get_name()
            if bound(table, name):
                graph.setdefault(binding_name(scope_name, name), set())
            if not symbol.is_referenced():
                continue
            if symbol.is_global():
                target = name if bound(module, name) else f"<external>.{name}"
            elif symbol.is_free() or symbol.is_nonlocal():
                target = f"<external>.{name}"
                for parent, parent_name in reversed(ancestors):
                    # Class namespaces do not supply ordinary closure bindings.
                    if parent.get_type() == "class":
                        if name == "__class__":
                            target = parent_name
                            break
                        continue
                    if bound(parent, name):
                        target = binding_name(parent_name, name)
                        break
            else:
                target = binding_name(scope_name, name)
            dependencies.add(target)
            graph.setdefault(target, set())

        for child in table.get_children():
            name = child.get_name()
            if name in {"lambda", "listcomp", "setcomp", "dictcomp", "genexpr"}:
                name = f"<{name}@{child.get_lineno()}>"
            visit(
                child,
                binding_name(scope_name, name),
                [*ancestors, (table, scope_name)],
            )

    visit(module, "<module>", [])
    return graph


def ast_diff(source1: str, source2: str) -> dict[str, set[str]]:
    """Classify qualified function names by structural AST changes.

    Formatting, comments, and source positions are ignored. Signatures,
    decorators, docstrings, and nested definitions are included. This is a
    structural approximation of behavior: changes to globals or dependencies
    are not tracked, and equivalent expressions may be reported as changed.
    Repeated definitions in the same scope are compared in source order.
    Invalid Python raises SyntaxError.
    """
    def functions(source: str) -> dict[str, list[str]]:
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

        Collector().visit(ast.parse(source))
        return definitions

    before = functions(source1)
    after = functions(source2)
    common = before.keys() & after.keys()
    changed = {name for name in common if before[name] != after[name]}
    return {
        "changed": changed,
        "unchanged": common - changed,
        "added": after.keys() - before.keys(),
        "removed": before.keys() - after.keys(),
    }


def test_dependency_graph_globals_and_calls():
    graph = build_dependency_graph("""
value = 1
def read_value():
    return value
def doubled():
    return read_value() * 2
""")
    assert graph == {
        "<module>": set(),
        "value": set(),
        "read_value": {"value"},
        "doubled": {"read_value"},
    }


def test_dependency_graph_shadowing_and_closures():
    graph = build_dependency_graph("""
value = 1
def outer(value):
    def inner():
        return value
    return inner()
def local():
    value = 2
    return value
def global_reader():
    global value
    return value
""")
    assert graph["outer"] == {"outer.inner"}
    assert graph["outer.inner"] == {"outer.value"}
    assert graph["local"] == {"local.value"}
    assert graph["global_reader"] == {"value"}


def test_dependency_graph_methods_skip_class_scope():
    graph = build_dependency_graph("""
value = 1
class Example:
    value = 2
    async def method(self):
        return value
    def owner(self):
        return __class__
""")
    assert graph["Example.method"] == {"value"}
    assert graph["Example.owner"] == {"Example"}


def test_dependency_graph_imports_external_names_and_recursion():
    graph = build_dependency_graph("""
import math as maths
def recurse(n):
    return recurse(n - 1) if n else len(str(maths.pi))
""")
    assert graph["recurse"] == {
        "recurse", "recurse.n", "maths", "<external>.len", "<external>.str"
    }
    assert all(target in graph for targets in graph.values() for target in targets)


def test_dependency_graph_invalid_source():
    with pytest.raises(SyntaxError):
        build_dependency_graph("def broken(")


def test_ast_diff_expectations():
    source1 = """
def same():
    return 1
def changed():
    return 2
def removed():
    pass
"""
    source2 = """
# Formatting and comments do not affect the comparison.
def same( ): return 1
def changed():
    return 3
async def added():
    pass
"""
    assert ast_diff(source1, source2) == {
        "changed": {"changed"},
        "unchanged": {"same"},
        "added": {"added"},
        "removed": {"removed"},
    }


def test_ast_diff_qualified_names():
    source = """
class First:
    def method(self):
        def inner():
            return 1
        return inner()
class Second:
    async def method(self):
        return 2
"""
    result = ast_diff(source, source.replace("return 1", "return 3"))
    assert result == {
        "changed": {"First.method", "First.method.inner"},
        "unchanged": {"Second.method"},
        "added": set(),
        "removed": set(),
    }


@pytest.mark.parametrize(
    "replacement",
    [
        "def f(value=2): return value",
        "@decorator\ndef f(value=1): return value",
        "async def f(value=1): return value",
    ],
)
def test_ast_diff_function_contract(replacement):
    assert ast_diff("def f(value=1): return value", replacement)["changed"] == {"f"}


def test_ast_diff_repeated_definitions():
    source = "def f(): return 1\ndef f(): return 2"
    assert ast_diff(source, source.replace("return 1", "return 3"))["changed"] == {"f"}


def test_ast_diff_ignores_module_statements():
    assert ast_diff("a = 1", "a = 2") == {
        "changed": set(), "unchanged": set(), "added": set(), "removed": set()
    }


def test_ast_diff_global_change_affects_behavior_but_reports_unchanged():
    source1 = """
value = 1

def read_value():
    return value
"""
    source2 = source1.replace("value = 1", "value = 2")
    before = {}
    after = {}
    exec(source1, before)
    exec(source2, after)

    assert before["read_value"]() == 1
    assert after["read_value"]() == 2
    assert ast_diff(source1, source2) == {
        "changed": set(),
        "unchanged": {"read_value"},
        "added": set(),
        "removed": set(),
    }


def test_ast_diff_invalid_source():
    with pytest.raises(SyntaxError):
        ast_diff("def broken(", "")

if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
