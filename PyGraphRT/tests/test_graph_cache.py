import gc
import weakref

from pygraphrt.node_rt import NodeRT
import pytest
import pygraphrt as rt

def test_if_cache_is_used():
    G = rt.GraphRT()
    call_count = 0

    @G.module().op()
    def add_op(a: int, b: int) -> int:
        nonlocal call_count
        call_count += 1
        return a + b

    node = G.node(1, 2)(add_op)

    G.execute(node)
    assert call_count == 1, "first execution should call the function"

    G.execute(node)
    assert call_count == 1, "second execution should use cache, not call the function again"

def test_upstream_input_change_invalidates_doWwnstream_cache():
    G = rt.GraphRT()

    @G.module().op()
    def add_op(a: int, b: int) -> int:
        return a + b

    @G.module().op()
    def mult_op(a: int, b: int) -> int:
        return a * b

    add_node = G.node(1, 2)(add_op)
    mult_node = G.node(add_node, 3)(mult_op)

    result = G.execute(mult_node)
    assert result == 9, "should compute (1 + 2) * 3 = 9"

    add_node.set_inputs(4, 2)
    result = G.execute(mult_node)
    assert result == 18, "should compute (4 + 2) * 3 = 18 after changing add_node input"

def test_operator_function_change_invalidates_cache():
    G = rt.GraphRT()

    @G.module().op()
    def func(a: int, b: int) -> int:
        return a + b

    node:NodeRT = G.node(3, 4)(func)

    result = G.execute(node)
    assert result == 7, "should compute 3 + 4 = 7"

    def func(a: int, b: int) -> int:
        return a * b

    G.module().update_operator(node.get_operator(), func)

    result = G.execute(node)
    assert result == 12, "should compute 3 * 4 = 12 after swapping add to multiply"

def test_upstream_operator_function_change_invalidates_downstream_cache():
    G = rt.GraphRT()

    @G.node(3, 4)
    def add_node(a: int, b: int) -> int:
        return a + b

    @G.node(add_node, 2)
    def mult_node(a: int, b: int) -> int:
        return a * b


    result = G.execute(mult_node)
    assert result == 14, "should compute (3 + 4) * 2 = 14"

    def subtract(a: int, b: int) -> int:
        return a - b

    G.module().update_operator(add_node.get_operator(), subtract)

    result = G.execute(mult_node)
    assert result == -2, "should compute (3 - 4) * 2 = -2 after swapping add to subtract"


@pytest.mark.parametrize("keyword_dependency", [False, True])
def test_reverting_inputs_recomputes_nodes_without_reusing_history(keyword_dependency):
    G = rt.GraphRT()
    calls = []

    @G.node(1)
    def source(value):
        calls.append("source")
        return value

    def times_ten(value):
        calls.append("times_ten")
        return value * 10

    downstream = (
        G.node(value=source)(times_ten)
        if keyword_dependency else G.node(source)(times_ten)
    )

    for value in (1, 2, 1):
        source.set_inputs(value)
        assert G.execute(downstream) == value * 10

    assert calls == ["source", "times_ten"] * 3
    assert G.execute(downstream) == 10
    assert calls == ["source", "times_ten"] * 3


def test_cached_dependency_invalidates_other_execution_roots():
    G = rt.GraphRT()

    @G.node(1)
    def source(value):
        return value

    @G.node(source)
    def doubled(value):
        return value * 2

    @G.node(value=source)
    def tripled(value):
        return value * 3

    assert G.execute(doubled) == 2
    assert G.execute(tripled) == 3

    source.set_inputs(2)
    assert G.execute(source) == 2
    assert G.execute(doubled) == 4
    assert G.execute(tripled) == 6

    source.set_inputs(1)
    assert G.execute(source) == 1
    assert G.execute(tripled) == 3
    assert G.execute(doubled) == 2


@pytest.mark.parametrize("cache_action", ["clear", "remove"])
def test_cache_eviction_recomputes_node_and_dependents(cache_action):
    G = rt.GraphRT()
    calls = []

    @G.node()
    def source():
        calls.append("source")
        return 3

    @G.node(source)
    def doubled(value):
        calls.append("doubled")
        return value * 2

    assert G.execute(doubled) == 6
    assert G.execute(doubled) == 6
    assert calls == ["source", "doubled"]

    if cache_action == "clear":
        G.cache().clear()
    else:
        G.cache().remove(source)

    assert G.execute(doubled) == 6
    assert calls == ["source", "doubled"] * 2


def test_none_results_are_cached():
    G = rt.GraphRT()
    calls = []

    @G.node()
    def source():
        calls.append("source")
        return None

    @G.node(source)
    def is_none(value):
        calls.append("is_none")
        return value is None

    assert G.execute(is_none) is True
    assert G.execute(is_none) is True
    assert calls == ["source", "is_none"]


@pytest.mark.parametrize("keyword_input", [False, True])
def test_equal_literal_values_with_different_types_invalidate_cache(keyword_input):
    G = rt.GraphRT()

    @G.node(1)
    def input_type(value):
        return type(value)

    for value in (1, True, 1.0):
        if keyword_input:
            input_type.set_inputs(value=value)
        else:
            input_type.set_inputs(value)
        assert G.execute(input_type) is type(value)


def test_cached_function_is_retained_until_its_entry_is_replaced():
    G = rt.GraphRT()

    def original():
        return 1

    node = G.node()(original)
    original_ref = weakref.ref(original)
    assert node.get_operator().fingerprint() is original
    assert G.execute(node) == 1

    def replacement():
        return 2

    G.module().update_operator(node.get_operator(), replacement)
    del original
    gc.collect()
    assert original_ref() is not None, "The cached function's identity must not be recycled"
    assert node.get_operator().fingerprint() is replacement

    assert G.execute(node) == 2
    gc.collect()
    assert original_ref() is None, "Superseded cache entries must release old functions"


def test_removing_node_releases_its_cached_result():
    G = rt.GraphRT()

    class Result:
        pass

    @G.node()
    def source():
        return Result()

    result_ref = weakref.ref(G.execute(source))
    assert result_ref() is not None

    G.remove_node(source)
    gc.collect()
    assert result_ref() is None


def test_shared_dependencies_do_not_repeat_fingerprinting(monkeypatch):
    G = rt.GraphRT()
    calls = []

    @G.module().op()
    def add(left, right):
        calls.append((left, right))
        return left + right

    root = G.node(1, 1)(add)
    node_count = 20
    for _ in range(node_count - 1):
        root = G.node(root, root)(add)

    fingerprint_calls = 0
    original_fingerprint = add.fingerprint

    def counted_fingerprint():
        nonlocal fingerprint_calls
        fingerprint_calls += 1
        assert fingerprint_calls <= 4 * node_count, "Fingerprinting must not expand shared dependency paths"
        return original_fingerprint()

    monkeypatch.setattr(add, "fingerprint", counted_fingerprint)

    assert G.execute(root) == 2 ** node_count
    assert G.execute(root) == 2 ** node_count
    assert len(calls) == node_count


def test_failed_execution_is_retried_and_only_success_is_cached():
    G = rt.GraphRT()
    call_count = 0

    @G.node()
    def flaky():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("First attempt failed")
        return 42

    with pytest.raises(RuntimeError, match="First attempt failed"):
        G.execute(flaky)
    assert G.execute(flaky) == 42
    assert G.execute(flaky) == 42
    assert call_count == 2


if __name__ == "__main__":
    pytest.main([__file__, "-vv"]) 
