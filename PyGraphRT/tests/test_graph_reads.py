import pytest
from pygraphrt.graph_rt import GraphRT
from pygraphrt.operator_rt import ParameterRT
from pygraphrt.local_module_rt import LocalModuleRT
from pygraphrt.local_module_rt import OperatorRTRef
from textwrap import dedent


def test_graph_initialization():
    G = GraphRT()
    assert G is not None

def test_read_operator_parameter_names():
    G = GraphRT()

    @G.node()
    def two_node(a: int, b: int) -> int:
        return 2

    op = two_node.get_operator()
    assert isinstance(op, OperatorRTRef), f"{op} is not an instance of rt.OperatorRT"

    expected_parameters_names = [
        "a",
        "b"
    ]
    actual_parameter_names = list(op.get_parameters().keys())
    assert actual_parameter_names == expected_parameters_names, f"Expected {expected_parameters}, but got {actual_parameters}"

    
def test_read_operator_parameter_objects_details():
    G = GraphRT()

    @G.node()
    def two_node(a: int, b: int) -> int:
        return 2

    op = two_node.get_operator()
    assert isinstance(op, OperatorRTRef), f"{op} is not an instance of rt.OperatorRT"

    expected_parameters = [
        ParameterRT("a", annotation=int), 
        ParameterRT("b", annotation=int)
    ]
    actual_parameters = list(op.get_parameters().values())
    assert actual_parameters == expected_parameters, f"Expected {expected_parameters}, but got {actual_parameters}"

if __name__ == "__main__":
    pytest.main([__file__, "-v"])