import pytest
from pygraphrt.graph_rt import GraphRT
from pygraphrt.operator_rt import ParameterRT
from pygraphrt.local_module_rt import LocalModuleRT
from pygraphrt.local_module_rt import OperatorRTRef
from textwrap import dedent

class TestGraphReads:
    def test_graph_initialization(self):
        G = GraphRT()
        assert G is not None
        
class TestNodeReads:
    ...

class TestOperatorReads:
    G = GraphRT()

    @G.node()
    def two_node(a: int, b: int) -> int:
        return 2

    op = two_node.get_operator()
    assert isinstance(op, OperatorRTRef), f"{op} is not an instance of rt.OperatorRT"

    expected_parameters = {
        ParameterRT("a"), 
        ParameterRT("b")
    }
    actual_parameters = op.get_parameters()
    assert actual_parameters == expected_parameters

if __name__ == "__main__":
    pytest.main([__file__, "-v"])