import gc
import weakref

import pytest
import pygraphrt as rt


@pytest.fixture(params=[rt.MemoryCache, rt.HistoryMemoryCache])
def cache(request):
    return request.param()

def test_if_cache_is_used(cache):
    G = rt.GraphRT()
    G.cache = cache
    call_count = 0

    @G.op()
    def add_op(a: int, b: int) -> int:
        nonlocal call_count
        call_count += 1
        return a + b

    node = G.node(1, 2)(add_op)

    G.execute(node)
    assert call_count == 1, "first execution should call the function"

    G.execute(node)
    assert call_count == 1, "second execution should use cache, not call the function again"

def test_upstream_input_change_invalidates_doWwnstream_cache(cache):
    G = rt.GraphRT()
    G.cache = cache

    @G.op()
    def add_op(a: int, b: int) -> int:
        return a + b

    @G.op()
    def mult_op(a: int, b: int) -> int:
        return a * b

    add_node = G.node(1, 2)(add_op)
    mult_node = G.node(add_node, 3)(mult_op)

    result = G.execute(mult_node)
    assert result == 9, "should compute (1 + 2) * 3 = 9"

    add_node.set_inputs(4, 2)
    result = G.execute(mult_node)
    assert result == 18, "should compute (4 + 2) * 3 = 18 after changing add_node input"

def test_operator_function_change_invalidates_cache(cache):
    G = rt.GraphRT()
    G.cache = cache

    @G.op()
    def func(a: int, b: int) -> int:
        return a + b

    node = G.node(3, 4)(func)

    result = G.execute(node)
    assert result == 7, "should compute 3 + 4 = 7"

    def func(a: int, b: int) -> int:
        return a * b

    G._inline_module.update_operator(node.get_operator(), rt.FunctionOperator(func))

    result = G.execute(node)
    assert result == 12, "should compute 3 * 4 = 12 after swapping add to multiply"

def test_upstream_operator_function_change_invalidates_downstream_cache(cache):
    G = rt.GraphRT()
    G.cache = cache

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

    G._inline_module.update_operator(add_node.get_operator(), rt.FunctionOperator(subtract))

    result = G.execute(mult_node)
    assert result == -2, "should compute (3 - 4) * 2 = -2 after swapping add to subtract"


@pytest.mark.parametrize("keyword_dependency", [False, True])
def test_reverting_inputs_respects_cache_history_policy(keyword_dependency, cache):
    G = rt.GraphRT()
    G.cache = cache
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

    executions = 2 if isinstance(cache, rt.HistoryMemoryCache) else 3
    assert calls == ["source", "times_ten"] * executions
    assert G.execute(downstream) == 10
    assert calls == ["source", "times_ten"] * executions


def test_cached_dependency_invalidates_other_execution_roots(cache):
    G = rt.GraphRT()
    G.cache = cache

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
def test_eviction_does_not_change_computation_fingerprints(cache_action, cache):
    G = rt.GraphRT()
    G.cache = cache
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
        G.cache.clear()
    else:
        G.cache.remove(source)

    assert G.execute(doubled) == 6
    expected = ["source", "doubled"] * 2 if cache_action == "clear" else ["source", "doubled", "source"]
    assert calls == expected


def test_none_results_are_cached(cache):
    G = rt.GraphRT()
    G.cache = cache
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
def test_equal_literal_values_with_different_types_invalidate_cache(keyword_input, cache):
    G = rt.GraphRT()
    G.cache = cache

    @G.node(1)
    def input_type(value):
        return type(value)

    for value in (1, True, 1.0):
        if keyword_input:
            input_type.set_inputs(value=value)
        else:
            input_type.set_inputs(value)
        assert G.execute(input_type) is type(value)

def test_removing_node_releases_its_cached_result(cache):
    G = rt.GraphRT()
    G.cache = cache

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


def test_shared_dependencies_do_not_repeat_fingerprinting(cache):
    G = rt.GraphRT()
    G.cache = cache
    calls = []
    hash_calls = 0
    node_count = 20

    def add(left, right):
        calls.append((left, right))
        return left + right

    class CountedOperator(rt.FunctionOperator):
        def __hash__(self):
            nonlocal hash_calls
            hash_calls += 1
            assert hash_calls <= 6 * node_count, "Hashing must not expand shared dependency paths"
            return object.__hash__(self)

    add_op = G.op()(add)
    G._inline_module.update_operator(add_op, CountedOperator(add))
    root = G.node(1, 1)(add_op)
    for _ in range(node_count - 1):
        root = G.node(root, root)(add_op)

    assert G.execute(root) == 2 ** node_count
    assert G.execute(root) == 2 ** node_count
    assert len(calls) == node_count


def test_failed_execution_is_retried_and_only_success_is_cached(cache):
    G = rt.GraphRT()
    G.cache = cache
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


@pytest.mark.parametrize("keyword_dependency", [False, True])
def test_rewiring_to_equivalent_node_recomputes_downstream(keyword_dependency, cache):
    G = rt.GraphRT()
    G.cache = cache
    calls = []

    @G.op()
    def source(value):
        calls.append("source")
        return value

    first = G.node(3)(source, name="first")
    second = G.node(3)(source, name="second")

    @G.node(value=first)
    def doubled(value):
        calls.append("doubled")
        return value * 2

    # Keep the calling convention the same when changing the connection.
    if not keyword_dependency:
        doubled.set_inputs(first)
    assert G.execute(doubled) == 6
    if keyword_dependency:
        doubled.set_inputs(value=second)
    else:
        doubled.set_inputs(second)
    assert G.execute(doubled) == 6
    assert calls == ["source", "doubled", "source", "doubled"]
    assert G.execute(doubled) == 6
    assert calls == ["source", "doubled", "source", "doubled"]


def test_changes_to_unrelated_branch_do_not_invalidate_cached_root(cache):
    G = rt.GraphRT()
    G.cache = cache
    calls = []

    @G.op()
    def source(value):
        calls.append(value)
        return value

    first = G.node(1)(source)
    second = G.node(2)(source)
    assert G.execute(first) == 1
    assert G.execute(second) == 2
    second.set_inputs(3)
    assert G.execute(second) == 3
    assert G.execute(first) == 1
    assert calls == [1, 2, 3]


def test_equivalent_nodes_have_separate_results_and_independent_eviction(cache):
    G = rt.GraphRT()
    G.cache = cache
    calls = []

    class Result:
        pass

    @G.op()
    def source():
        calls.append("source")
        return Result()

    first = G.node()(source)
    second = G.node()(source)
    first_result = weakref.ref(G.execute(first))
    second_result = weakref.ref(G.execute(second))
    assert first_result() is not second_result()
    assert G.execute(first) is first_result()
    assert G.execute(second) is second_result()
    assert calls == ["source", "source"]

    G.remove_node(first)
    gc.collect()
    assert first_result() is None
    assert G.execute(second) is second_result()
    assert calls == ["source", "source"]
    G.remove_node(second)
    gc.collect()
    assert second_result() is None


def test_operator_replacement_respects_cache_history_policy(cache):
    G = rt.GraphRT()
    G.cache = cache
    calls = []

    def original(value):
        calls.append("original")
        return value + 1

    def replacement(value):
        calls.append("replacement")
        return value + 2

    node = G.node(1)(original)
    original_data = rt.FunctionOperator(original)
    G._inline_module.update_operator(node.get_operator(), original_data)
    assert G.execute(node) == 2
    G._inline_module.update_operator(node.get_operator(), rt.FunctionOperator(replacement))
    assert G.execute(node) == 3
    G._inline_module.update_operator(node.get_operator(), original_data)
    assert G.execute(node) == 2
    expected = ["original", "replacement"]
    if isinstance(cache, rt.MemoryCache):
        expected.append("original")
    assert calls == expected


def test_argument_positions_names_and_keyword_order_are_significant(cache):
    G = rt.GraphRT()
    G.cache = cache

    @G.node(1, 2)
    def arguments(*args, **kwargs):
        return args, tuple(kwargs.items())

    assert G.execute(arguments) == ((1, 2), ())
    arguments.set_inputs(2, 1)
    assert G.execute(arguments) == ((2, 1), ())
    arguments.set_inputs(a=1, b=2)
    assert G.execute(arguments) == ((), (("a", 1), ("b", 2)))
    arguments.set_inputs(b=2, a=1)
    assert G.execute(arguments) == ((), (("b", 2), ("a", 1)))
    arguments.set_inputs(c=2, a=1)
    assert G.execute(arguments) == ((), (("c", 2), ("a", 1)))


@pytest.mark.parametrize("first,second", [
    ([1, {"value": (True, None)}], [1, {"value": (True, None)}]),
    ({"value": [1, 2]}, {"value": [1, 2]}),
])
def test_equal_container_literals_reuse_same_node_result(first, second, cache):
    G = rt.GraphRT()
    G.cache = cache
    calls = []

    @G.node(first)
    def identity(value):
        calls.append("identity")
        return value

    G.execute(identity)
    identity.set_inputs(second)
    assert G.execute(identity) == second
    assert calls == ["identity"]


@pytest.mark.parametrize("first,second", [
    ([1], [True]),
    ([1], (1,)),
    (b"value", "value"),
    (0.0, -0.0),
    ({"a": 1, "b": 2}, {"b": 2, "a": 1}),
])
def test_observable_literal_differences_get_distinct_keys(first, second, cache):
    G = rt.GraphRT()
    G.cache = cache
    calls = []

    @G.node(first)
    def describe(value):
        calls.append("describe")
        return repr(value)

    assert G.execute(describe) == repr(first)
    describe.set_inputs(second)
    assert G.execute(describe) == repr(second)
    assert calls == ["describe", "describe"]


def test_custom_literal_objects_use_identity_without_requiring_hashability(cache):
    G = rt.GraphRT()
    G.cache = cache

    class Value:
        __hash__ = None

        def __eq__(self, other):
            return True

    first, second = Value(), Value()

    @G.node(first)
    def identity(value):
        return value

    assert G.execute(identity) is first
    identity.set_inputs(second)
    assert G.execute(identity) is second
    identity.set_inputs(first)
    assert G.execute(identity) is first


def test_default_dummy_cache_still_executes_every_time():
    G = rt.GraphRT()
    calls = []

    @G.node()
    def source():
        calls.append("source")
        return 1

    assert G.execute(source) == 1
    assert G.execute(source) == 1
    assert calls == ["source", "source"]


@pytest.mark.parametrize("value", [1 << 16000, -(1 << 16000)], ids=["positive", "negative"])
def test_large_integer_literals_do_not_require_decimal_conversion(value, cache):
    G = rt.GraphRT()
    G.cache = cache
    calls = []

    @G.node(value)
    def identity(value):
        calls.append("identity")
        return value

    assert G.execute(identity) == value
    assert G.execute(identity) == value
    assert calls == ["identity"]


def test_custom_operator_behavior_contributes_to_identity(cache):
    G = rt.GraphRT()
    G.cache = cache

    def original(value):
        return value

    class DoubledOperator(rt.FunctionOperator):
        def __call__(self, value):
            return super().__call__(value) * 2

    node = G.node(3)(original)
    assert G.execute(node) == 3
    G._inline_module.update_operator(node.get_operator(), DoubledOperator(original))
    assert G.execute(node) == 6


def test_equivalent_nodes_do_not_share_results_in_one_execution(cache):
    G = rt.GraphRT()
    G.cache = cache

    @G.op()
    def source():
        return []

    first = G.node()(source)
    second = G.node()(source)

    @G.node(first, second)
    def pair(left, right):
        return left, right

    left, right = G.execute(pair)
    assert left is not right
    left.append("first only")
    assert right == []
    assert G.execute(first) is left
    assert G.execute(second) is right


@pytest.mark.parametrize("eviction", ["remove", "clear"])
def test_cache_lookup_hit_and_eviction(cache, eviction):
    G = rt.GraphRT()

    @G.node()
    def node():
        return None

    @G.node()
    def other():
        return None

    assert cache.lookup(node, 1) is None
    assert not cache.hit(node, 1)
    cache.save(node, 1, None)
    assert cache.hit(node, 1)
    assert cache.lookup(node, 1).value is None
    assert not cache.hit(other, 1)

    cache.save(node, 2, "new")
    cache.save(other, 1, "other")
    assert cache.lookup(node, 2).value == "new"
    assert cache.hit(node, 1) is isinstance(cache, rt.HistoryMemoryCache)

    if eviction == "remove":
        cache.remove(node)
        cache.remove(node)  # Removing an absent node is harmless.
        assert cache.lookup(other, 1).value == "other"
    else:
        cache.clear()
        assert not cache.hit(other, 1)
    for fingerprint in (1, 2):
        assert not cache.hit(node, fingerprint)
        assert cache.lookup(node, fingerprint) is None


def test_cache_policy_controls_retention_of_previous_results(cache):
    G = rt.GraphRT()
    G.cache = cache

    class Result:
        pass

    @G.node(1)
    def source(value):
        return Result()

    first = weakref.ref(G.execute(source))
    source.set_inputs(2)
    latest = weakref.ref(G.execute(source))
    gc.collect()
    assert (first() is not None) is isinstance(cache, rt.HistoryMemoryCache)
    assert latest() is not None

    cache.clear()
    gc.collect()
    assert first() is None
    assert latest() is None


def test_cache_collisions_with_minus_1(cache):
    """this is a regression test
    turnes out hash(-1) == hash(-2) which messes with the cache using hash for fingerprints"""
    G = rt.GraphRT()
    G.cache = cache

    @G.node(-1)
    def source(value):
        return value

    node = G.node()(source)
    assert G.execute(node) == -1
    source.set_inputs(-2)
    assert G.execute(node) == -2

if __name__ == "__main__":
    pytest.main([__file__, "-vv"]) 
