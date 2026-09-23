import pytest
import pygraphrt as rt
from textwrap import dedent
import sys

from pygraphrt.inline_module import FunctionOperator


@pytest.mark.skipif(sys.version_info < (3, 14), reason="Deferred annotations require Python 3.14")
@pytest.mark.parametrize("annotation_position", ["parameter", "return"])
def test_incomplete_annotations_preserve_signature(annotation_position):
    from annotationlib import ForwardRef

    namespace = {}
    source = (
        "def greet(name: s = 'world', count: int = 1) -> str: return name"
        if annotation_position == "parameter" else
        "def greet(name: str = 'world', count: int = 1) -> s: return name"
    )
    exec(source, namespace)
    operator = FunctionOperator(namespace["greet"])
    parameters = operator.get_parameters()
    return_type = operator.get_return_type()
    assert list(parameters) == ["name", "count"]
    assert parameters["name"].default == "world"
    assert parameters["count"].annotation is int
    unresolved = parameters["name"].annotation if annotation_position == "parameter" else return_type
    assert isinstance(unresolved, ForwardRef)
    assert unresolved.__forward_arg__ == "s"
    assert operator() == "world"

    namespace["s"] = str
    assert operator.get_parameters()["name"].annotation is str
    assert operator.get_return_type() is str

def test_operator_decorator():
    graph = rt.GraphRT()
    
    @graph._inline_module.op()
    def add(a:int, b:int) -> int:
        return a + b

    @graph._inline_module.op()
    def mult(a:int, b:int) -> int:
        return a * b

    add_node2 = graph.node(1,1)(add)
    add_node3 = graph.node(3,5)(add)
    mult_node = graph.node(add_node2, add_node3)(mult)

    assert all(
        isinstance(node, rt.OperatorRef) 
        for node in [add, mult]
    )
    assert graph.operators() == [add, mult]

