import ast
import pytest
from textwrap import dedent
from pygraphrt.source_diff import ast_diff, FunctionsDiff


def test_ast_diff_expectations():
    source1 = dedent("""
    def same():
        return 1

    def changed():
        return 2

    def removed():
        pass
    """)

    source2 = dedent("""
    # Formatting and comments do not affect the comparison.
    def same( ): return 1

    def changed():
        return 3

    async def added():
        pass
    """)

    assert ast_diff(source1, source2) == FunctionsDiff(
        changed={"changed"},
        unchanged={"same"},
        added={"added"},
        removed={"removed"},
    )


def test_ast_diff_qualified_names():
    source = dedent("""
    class First:
        def method(self):
            def inner():
                return 1
            return inner()
    class Second:
        async def method(self):
            return 2
    """)

    result = ast_diff(source, source.replace("return 1", "return 3"))
    assert result == FunctionsDiff(
        changed={"First.method", "First.method.inner"},
        unchanged={"Second.method"},
        added=set(),
        removed=set(),
    )


@pytest.mark.parametrize(
    "replacement",
    [
        "def f(value=2): return value",
        "@decorator\ndef f(value=1): return value",
        "async def f(value=1): return value",
    ],
)

def test_ast_diff_function_contract(replacement):
    assert ast_diff("def f(value=1): return value", replacement).changed == {"f"}

def test_ast_diff_repeated_definitions():
    source = "def f(): return 1\ndef f(): return 2"
    assert ast_diff(source, source.replace("return 1", "return 3")).changed == {"f"}

def test_ast_diff_ignores_module_statements():
    assert ast_diff("a = 1", "a = 2") == FunctionsDiff(
        changed=set(), unchanged=set(), added=set(), removed=set()
    )

def test_ast_diff_global_change_affects_behavior_but_reports_unchanged():
    source1 = dedent("""
    value = 1

    def read_value():
        return value
    """)

    source2 = source1.replace("value = 1", "value = 2")
    before = {}
    after = {}
    exec(source1, before)
    exec(source2, after)

    assert before["read_value"]() == 1
    assert after["read_value"]() == 2
    assert ast_diff(source1, source2) == FunctionsDiff(
        changed=set(),
        unchanged={"read_value"},
        added=set(),
        removed=set(),
    )


def test_ast_diff_invalid_source():
    with pytest.raises(SyntaxError):
        ast_diff("def broken(", "")

if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))