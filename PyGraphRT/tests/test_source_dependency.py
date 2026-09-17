import ast
import symtable

import pytest
from textwrap import dedent

from pygraphrt.source_dependency import build_dependency_graph


@pytest.mark.xfail(reason="behavior not yet implemented")
def test_dependency_graph_globals_and_calls():
    graph = build_dependency_graph(dedent("""
    value = 1
    def read_value():
        return value
    def doubled():
        return read_value() * 2
    """))

    assert graph == {
        "<module>": set(),
        "value": set(),
        "read_value": {"value"},
        "doubled": {"read_value"},
    }

def test_dependency_graph_shadowing_and_closures():
    graph = build_dependency_graph(dedent("""
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
    """))

    assert graph["outer"] == {"outer.inner"}
    assert graph["outer.inner"] == {"outer.value"}
    assert graph["local"] == {"local.value"}
    assert graph["global_reader"] == {"value"}


def test_dependency_graph_methods_skip_class_scope():
    graph = build_dependency_graph(dedent("""
    value = 1
    class Example:
        value = 2
        async def method(self):
            return value
        def owner(self):
            return __class__
    """))

    assert graph["Example.method"] == {"value"}
    assert graph["Example.owner"] == {"Example"}


def test_dependency_graph_imports_external_names_and_recursion():
    graph = build_dependency_graph(dedent("""
    import math as maths
    def recurse(n):
        return recurse(n - 1) if n else len(str(maths.pi))
    """))

    assert graph["recurse"] == {
        "recurse", "recurse.n", "maths", "<external>.len", "<external>.str"
    }
    assert all(target in graph for targets in graph.values() for target in targets)


def test_dependency_graph_invalid_source():
    with pytest.raises(SyntaxError):
        build_dependency_graph("def broken(")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))