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
    def add_op(a: int, b: int) -> int:
        return a + b

    node = G.node(3, 4)(add_op)

    result = G.execute(node)
    assert result == 7, "should compute 3 + 4 = 7"

    def mult(a: int, b: int) -> int:
        return a * b

    add_op.set_function(mult)
    result = G.execute(node)
    assert result == 12, "should compute 3 * 4 = 12 after swapping add to multiply"

def test_upstream_operator_function_change_invalidates_downstream_cache():
    G = rt.GraphRT()

    @G.module().op()
    def add_op(a: int, b: int) -> int:
        return a + b

    @G.module().op()
    def mult_op(a: int, b: int) -> int:
        return a * b

    add_node = G.node(3, 4)(add_op)
    mult_node = G.node(add_node, 2)(mult_op)

    result = G.execute(mult_node)
    assert result == 14, "should compute (3 + 4) * 2 = 14"

    def subtract(a: int, b: int) -> int:
        return a - b

    add_op.set_function(subtract)
    result = G.execute(mult_node)
    assert result == -2, "should compute (3 - 4) * 2 = -2 after swapping add to subtract"

if __name__ == "__main__":
    pytest.main([__file__, "-vv"]) 
