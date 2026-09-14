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
    G.remove_node(add)
    with pytest.raises(TypeError):
        result = G.execute(mult)

def test_set_operator_function_with_same_signature():
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
    
    mult_op.set_function(divide)
    result = G.execute(mult_node)
    assert result == 1, "Node should compute (1 + 2) / 3 = 1 after changing add to divide"

def test_remove_operator_from_graph():
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
    G.remove_operator(add_op)
    with pytest.raises(ValueError):
        result = G.execute(mult)

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

def test_set_operator_function_with_different_signature():
    G = rt.GraphRT()

    @G.op()
    def the_op(a:int, b:int) -> int:
        return a + b

    add_node = G.node(1, 2)(the_op)
    result = G.execute(add_node)
    assert result == 3, "Node should compute 1 + 2 = 3"

    # now change the function of the add operator to a function with a different signature
    def add_three(a:int, b:int, c:int) -> int:
        return a + b + c

    the_op.set_function(add_three)
    with pytest.raises(TypeError):
        result = G.execute(add_node)

if __name__ == "__main__":
    pytest.main([__file__, "-vv"]) 
