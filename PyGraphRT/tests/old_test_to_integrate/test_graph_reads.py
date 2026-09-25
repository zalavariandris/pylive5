import pytest
from pygraphrt.graph_rt import GraphRT
from pygraphrt.abstract_module_rt import OperatorRef, ParameterData


# REVIEW UNNECESSARY / REMOVE: construction and a non-None instance are already
# exercised by every graph test; this checks no additional behavior.
def test_graph_initialization():
    G = GraphRT()
    assert G is not None

# REVIEW UNNECESSARY / MERGE: overlaps the parameter-details test below.
# Keep its ordered-key assertion there when consolidating introspection tests.
def test_read_operator_parameter_names():
    G = GraphRT()

    @G.node()
    def two_node(a: int, b: int) -> int:
        return 2

    op = two_node.get_operator()
    assert isinstance(op, OperatorRef), f"{op} is not an instance of rt.OperatorRT"

    expected_parameters_names = [
        "a",
        "b"
    ]
    actual_parameter_names = list(op.get_parameters().keys())
    assert actual_parameter_names == expected_parameters_names, f"Expected {expected_parameters_names}, but got {actual_parameter_names}"

    
def test_read_operator_parameter_objects_details():
    G = GraphRT()

    @G.node()
    def two_node(a: int, b: int) -> int:
        return 2

    op = two_node.get_operator()
    assert isinstance(op, OperatorRef), f"{op} is not an instance of rt.OperatorRT"

    expected_parameters = [
        ParameterData("a", annotation=int), 
        ParameterData("b", annotation=int)
    ]
    actual_parameters = list(op.get_parameters().values())
    assert actual_parameters == expected_parameters, f"Expected {expected_parameters}, but got {actual_parameters}"

def test_function_operator_signatures():
    # todo: test multuple signatures, including return types.
    G = GraphRT()

    @G.node()
    def mult(a, b):
        return a * b

    actual_parameters = list(mult.get_operator().get_parameters().values())
    expected_parameters = [
        ParameterData("a"), 
        ParameterData("b")
    ]
    assert actual_parameters == expected_parameters


if __name__ == "__main__":
    pytest.main([__file__, "-v"])