from pygraphrt.abstract_module_rt import OperatorRef
from pygraphrt.errors import ModuleError, GraphExecutionError
import pytest

import pygraphrt as rt


def test_set_node_inputs_to_raw_values():
    G = rt.GraphRT()

    @G.node(a=2, b=3)
    def n1(a:int, b:int) -> int:
        return a + b

    result = G.execute(n1)
    assert result == 5, "Node should compute 2 + 3 = 5"

    n1.set_inputs(5, 3)
    result = G.execute(n1)
    assert result == 8, "Node should compute 5 + 3 = 8 after changing input a to 5"

def test_set_node_inputs_to_nodes():
    G = rt.GraphRT()

    @G.node()
    def two() -> int:
        return 2

    @G.node(b=5)
    def n1(a:int, b:int) -> int:
        return a * b

    n1.set_inputs(a=two, b=5) # linking node two to input a of n1

    result = G.execute(n1)
    assert result == 10, "Node should compute 2 * 5 = 10"

# REVIEW OUTDATED / UPDATE: execute() wraps the missing-argument TypeError in
# GraphExecutionError. Keep dependent-input cleanup coverage; it is useful.
def test_remove_node_from_graph():
    G = rt.GraphRT()

    @G.node()
    def two() -> int:
        return 2

    @G.node(a=1, b=two)
    def add(a:int, b:int) -> int:
        return a + b

    @G.node(a=add, b=3)
    def mult(a:int, b:int) -> int:
        return a * b

    result = G.execute(mult)
    assert result == 9, "Node should compute (1 + 2) * 3 = 9"

    # now remove the node
    G._delete_node(add)
    assert mult.get_inputs() == ((), {"b": 3})
    with pytest.raises(TypeError):
        result = G.execute(mult)

def test_removing_nodes_cleanup_dependent_inputs():
    G = rt.GraphRT()

    @G.node()
    def source():
        return 2

    @G.node()
    def other():
        return 3

    @G.node(source, 10, source, other, removed=source, kept=other, literal=4)
    def collect(*args, **kwargs):
        return args, kwargs

    G._delete_node(source)

    assert collect.get_inputs() == ((10, other), {"kept": other, "literal": 4})
    assert G.execute(collect) == ((10, 3), {"kept": 3, "literal": 4})


# REVIEW SIMPLIFY: keep removal, dependent notifications, and fresh results
# across caches; the order of independent nodes in changes need not be fixed.
@pytest.mark.parametrize("cache_type", [rt.DummyCache, rt.MemoryCache, rt.HistoryMemoryCache])
def test_removing_node_updates_dependents_and_their_cached_results(cache_type):
    G = rt.GraphRT()
    G.cache = cache_type()

    @G.node()
    def source():
        return 2

    @G.node(value=source)
    def first(value=7):
        return value

    @G.node(value=source)
    def second(value=9):
        return value

    @G.node(first, second)
    def downstream(a, b):
        return a + b

    assert G.execute(downstream) == 4
    changes = []
    removals = []
    G.nodes_changed.connect(changes.extend)
    G.nodes_removed.connect(removals.extend)

    G._delete_node(source)

    assert first.get_inputs() == ((), {})
    assert second.get_inputs() == ((), {})
    assert downstream.get_inputs() == ((first, second), {})
    assert changes == [first, second]
    assert removals == [source]
    assert source not in G.nodes()
    assert G.execute(downstream) == 16


def test_remove_operator_from_graph_throws_missing_operator_error():
    G = rt.GraphRT()
    
    @G.node()
    def two() -> int:
        return 2

    @G.op()
    def add_op(a:int, b:int) -> int:
        return a + b

    add_node = G.node(a=1, b=two)(add_op)

    @G.node(a=add_node, b=3)
    def mult(a:int, b:int) -> int:
        return a * b

    result = G.execute(mult)
    assert result == 9, "Node should compute (1 + 2) * 3 = 9"

    # now remove the node
    G._inline_module.delete_operator(add_op)
    with pytest.raises(GraphExecutionError):
        result = G.execute(mult)

# REVIEW OUTDATED / REMOVE: GraphRT has no output property contract; this adds
# an unused attribute. execute(add) selects the root explicitly and the result
# duplicates basic execution coverage.
def test_setting_output():
    G = rt.GraphRT()

    @G.node()
    def two() -> int:
        return 2

    @G.node(a=two, b=3)
    def add(a:int, b:int) -> int:
        return a + b

    G.output = add
    result = G.execute(add)
    assert result == 5, "Node should compute 2 + 3 = 5"

class TestUpdatingNodesOperator:
    def test_update_operator_body(self):
        G = rt.GraphRT()

        @G.node(1, 2)
        def the_node(a:int, b:int) -> int:
            return a + b

        result = G.execute(the_node)
        assert result == 3, "Node should compute 1 + 2 = 3"

        # now update the body of the add operator
        def add(a:int, b:int) -> int:
            return a + b + 1

        G._inline_module._update_operator(the_node.get_operator(), add)

        result = G.execute(the_node)
        assert result == 4, "Node should compute 1 + 2 + 1 = 4 after updating operator body"

    # REVIEW OUTDATED / UPDATE: operator argument errors are wrapped in
    # GraphExecutionError. Preserve the incompatible-signature scenario.
    def test_execute_raises_type_error_after_operator_update_adds_required_parameter(self):
        G = rt.GraphRT()

        @G.node(1, 2)
        def the_node(a:int, b:int) -> int:
            return a + b

        result = G.execute(the_node)
        assert result == 3, "Node should compute 1 + 2 = 3"

        # now change the function of the add operator to a function with a different signature
        def add_three(a:int, b:int, c:int) -> int:
            return a + b + c

        G._inline_module._update_operator(the_node.get_operator(), add_three)

        with pytest.raises(TypeError):
            result = G.execute(the_node)

    def test_set_operator_function_with_same_signature(self):
        G = rt.GraphRT()

        @G.op()
        def add_op(a:int, b:int) -> int:
            return a + b

        @G.op()
        def mult_op(a:int, b:int) -> int:
            return a * b

        add_node = G.node(1, 2)(add_op)
        mult_node = G.node(add_node, 3)(mult_op)

        result = G.execute(mult_node)
        assert result == 9, "Node should compute (1 + 2) * 3 = 9"

        # now change the function of the add operator to multiply
        def divide(a:int, b:int) -> int:
            return a / b

        G._inline_module._update_operator(mult_op, divide)

        result = G.execute(mult_node)
        assert result == 1, "Node should compute (1 + 2) / 3 = 1 after changing add to divide"


# REVIEW KEEP: helper edits leaving callers stale is a real correctness gap,
# not an unnecessary restriction. The existing xfail records the limitation.
@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="Known limitation: helper edits leave callers stale; fix in a later iteration.",
)
def test_helper_edit_updates_existing_callers() -> None:
    source = "def helper(): return 1\ndef result(): return helper()"
    module = ScriptModuleRT("tools")
    module.set_script(source)

    module.set_script(source.replace("return 1", "return 2"))

    result = OperatorRef(module, "result").get_value()
    assert result is not None
    assert result() == 2


if __name__ == "__main__":
    pytest.main([__file__, "-vv"]) 
