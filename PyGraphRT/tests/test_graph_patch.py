import pytest
import pygraphrt as rt
from textwrap import dedent

def test_add_op():
    G1 = rt.GraphRT()

    G2 = rt.graph_utils.graph_from_script(dedent("""\n
    import pygraphrt as rt 
    G = rt.GraphRT()
    @G.module().op()
    def const1():
        return 1
    """), 'G')
    
    rt.patch(G1, G2)

    assert G1.to_dict() == G2.to_dict(), "Graph patch should update the first graph to match the second graph"

def test_remove_op():
    G1 = rt.GraphRT()
    @G1.module().op()
    def const1():
        return 1

    G2 = rt.graph_utils.graph_from_script(dedent("""\n
    import pygraphrt as rt
    G = rt.GraphRT()
    """), 'G')

    rt.patch(G1, G2)

    assert 'const1' not in G1.nodes().keys(), "Graph patch should remove node from the first graph to match the second graph"

def test_add_node():
    G1 = rt.graph_utils.graph_from_script(dedent("""\n
    import pygraphrt as rt 
    G = rt.GraphRT()
    """), 'G')

    G2 = rt.graph_utils.graph_from_script(dedent("""\n
    import pygraphrt as rt
    G = rt.GraphRT()
    @G.node()
    def const1():
        return 1
        """), 'G')

    
    rt.patch(G1, G2)

    assert 'const1' in G1.nodes().keys(), "Graph patch should add new node to the first graph to match the second graph"
    assert G1.to_dict()['nodes'] == G2.to_dict()['nodes'], "Graph patch should update the first graph to match the second graph"

def test_remove_node():
    G1 = rt.GraphRT()
    @G1.node()
    def const1():
        return 1

    G2 = rt.graph_utils.graph_from_script(dedent("""\n
    import pygraphrt as rt
    G = rt.GraphRT()
    """), 'G')

    rt.patch(G1, G2)

    assert 'const1' not in G1.nodes().keys(), "Graph patch should remove node from the first graph to match the second graph"

def test_set_kwargs():
    G1 = rt.GraphRT()
    @G1.node()
    def const1():
        return 1

    @G1.node()
    def const2():
        return 2

    @G1.node(a=5, b=10)
    def mult(a, b):
        return a * b

    G2 = rt.graph_utils.graph_from_script(dedent("""\n
    import pygraphrt as rt
    G = rt.GraphRT()
    @G.node()
    def const1():
        return 1

    @G.node()
    def const2():
        return 2

    @G.node(a=const1, b=const2)
    def mult(a, b):
        return a * b
    """), 'G')

    rt.patch(G1, G2)

    assert G1.to_dict()['nodes'] == G2.to_dict()['nodes'], "Graph patch should update the first graph to match the second graph"

def test_set_args():
    G1 = rt.GraphRT()
    @G1.node()
    def const1():
        return 1

    @G1.node()
    def const2():
        return 2

    @G1.node(5, 10)
    def mult(a, b):
        return a * b

    G2 = rt.graph_utils.graph_from_script(dedent("""\n
    import pygraphrt as rt
    G = rt.GraphRT()
    @G.node()
    def const1():
        return 1

    @G.node()
    def const2():
        return 2

    @G.node(const1, const2)
    def mult(a, b):
        return a * b
    """), 'G')

    rt.patch(G1, G2)

    assert G1.to_dict()['nodes'] == G2.to_dict()['nodes'], "Graph patch should update the first graph to match the second graph"

def test_replace_args():
    G1 = rt.GraphRT()
    @G1.node()
    def mult(a, b):
        return a*b

    G2 = rt.graph_utils.graph_from_script(dedent("""\n
    import pygraphrt as rt
    G = rt.GraphRT()
    @G.node(10, 15)
    def mult(a, b):
        return a*b
    """), 'G')

    rt.patch(G1, G2)

    assert G1.to_dict()['nodes'] == G2.to_dict()['nodes'], "Graph patch should update the first graph to match the second graph"

def test_remove_args():
    G1 = rt.GraphRT()
    @G1.node(10,5)
    def mult(a, b):
        return a*b

    G2 = rt.graph_utils.graph_from_script(dedent("""\n
    import pygraphrt as rt
    G = rt.GraphRT()
    @G.node(10)
    def mult(a, b):
        return a*b
    """), 'G')

    rt.patch(G1, G2)

    assert G1.to_dict()['nodes'] == G2.to_dict()['nodes'], "Graph patch should update the first graph to match the second graph"

def test_add_kwargs():
    G1 = rt.GraphRT()
    @G1.node(a=10)
    def mult(a, b):
        return a*b

    G2 = rt.graph_utils.graph_from_script(dedent("""\n
    import pygraphrt as rt
    G = rt.GraphRT()
    @G.node(a=10, b=5)
    def mult(a, b):
        return a*b
    """), 'G')

    rt.patch(G1, G2)

    assert G1.to_dict()['nodes'] == G2.to_dict()['nodes'], "Graph patch should update the first graph to match the second graph"

def test_add_args():
    G1 = rt.GraphRT()
    @G1.node(10)
    def mult(a, b):
        return a*b

    G2 = rt.graph_utils.graph_from_script(dedent("""\n
    import pygraphrt as rt
    G = rt.GraphRT()
    @G.node(10, 5)
    def mult(a, b):
        return a*b
    """), 'G')

    rt.patch(G1, G2)

    assert G1.to_dict()['nodes'] == G2.to_dict()['nodes'], "Graph patch should update the first graph to match the second graph"

def test_replace_kwargs():
    G1 = rt.GraphRT()
    @G1.node()
    def mult(a, b):
        return a*b

    G2 = rt.graph_utils.graph_from_script(dedent("""\n
    import pygraphrt as rt
    G = rt.GraphRT()
    @G.node(a=10, b=15)
    def mult(a, b):
        return a*b
    """), 'G')

    rt.patch(G1, G2)

    assert G1.to_dict()['nodes'] == G2.to_dict()['nodes'], "Graph patch should update the first graph to match the second graph"

def test_remove_kwargs():
    G1 = rt.GraphRT()
    @G1.node(a=10,b=5)
    def mult(a, b):
        return a*b

    G2 = rt.graph_utils.graph_from_script(dedent("""\n
    import pygraphrt as rt
    G = rt.GraphRT()
    @G.node(a=10)
    def mult(a, b):
        return a*b
    """), 'G')

    rt.patch(G1, G2)

    assert G1.to_dict()['nodes'] == G2.to_dict()['nodes'], "Graph patch should update the first graph to match the second graph"

def test_setting_operator_function():
    G = rt.GraphRT()
    @G.node()
    def hello():
        return "Hello World!"

    G2 = rt.graph_utils.graph_from_script(dedent("""\n
    import pygraphrt as rt
    G = rt.GraphRT()
    @G.node()
    def hello(str:name):
        return f"Hello {name}!"
    """), 'G')

    rt.patch(G, G2)

    assert G.get_node('hello').get_operator().get_source() == G2.get_node('hello').get_operator().get_source()
    assert G.get_node('hello').get_inputs() == G2.get_node('hello').get_inputs(), "Graph patch should update the first graph to match the second graph"

def test_replace_node_name_with_links():
    G = rt.GraphRT()
    @G.node()
    def const1():
        return 1

    @G.node()
    def const2():
        return 2

    @G.node(const1, const2)
    def mult(a, b):
        return a * b
    
    G2 = rt.graph_utils.graph_from_script(dedent("""\n
    import pygraphrt as rt
    G = rt.GraphRT()
    @G.node()
    def const1():
        return 1

    @G.node()
    def const2():
        return 2

    @G.node(const1, const2)
    def hello(a, b):
        return a * b
    """), 'G')

    rt.patch(G, G2)
    assert G.module().operators().keys() == {'const1', 'const2', 'hello'}
    assert G.nodes().keys() == {'const1', 'const2', 'hello'}
    inputs = G.get_node('hello').get_inputs()[0]
    assert {arg.get_name() for arg in inputs} == {'const1', 'const2'}

def test_missing_arguments():
    G = rt.GraphRT()
    @G.node(15)
    def identity(val):
        return val

    G1 = rt.graph_utils.graph_from_script(dedent("""\n
    import pygraphrt as rt
    G = rt.GraphRT()
    @G.node()
    def identity(val):
        return val
    """), 'G')

    rt.patch(G, G1)

    assert G.to_dict()['nodes'] == G1.to_dict()['nodes'], "Graph patch should update the first graph to match the second graph"

def test_executing_with_missing_arguments():
    G = rt.GraphRT()
    @G.node()
    def identity(val):
        return val
    with pytest.raises(TypeError):
        G.output = G.get_node('identity')
        G.execute()

def test_move_kwarg_to_arg():
    G = rt.GraphRT()
    @G.node(val=10)
    def identity(val):
        return val

    G2 = rt.graph_utils.graph_from_script(dedent("""\n
    import pygraphrt as rt
    G = rt.GraphRT()
    @G.node(10)
    def identity(val):
        return val
    """), 'G')

    assert G.get_node('identity').get_inputs() != G2.get_node('identity').get_inputs(), "Graph patch should update the first graph to match the second graph"
    rt.patch(G, G2)
    assert G.get_node('identity').get_inputs() == G2.get_node('identity').get_inputs(), "Graph patch should update the first graph to match the second graph"

def test_move_arg_to_kwarg():
    G = rt.GraphRT()
    @G.node(10)
    def identity(val):
        return val

    G2 = rt.graph_utils.graph_from_script(dedent("""\n
    import pygraphrt as rt
    G = rt.GraphRT()
    @G.node(val=10)
    def identity(val):
        return val
    """), 'G')

    assert G.get_node('identity').get_inputs() != G2.get_node('identity').get_inputs(), "Graph patch should update the first graph to match the second graph"
    rt.patch(G, G2)
    assert G.get_node('identity').get_inputs() == G2.get_node('identity').get_inputs(), "Graph patch should update the first graph to match the second graph"

def test_invalid_kwarg():
    G = rt.GraphRT()
    @G.node(val=10)
    def identity(val):
        return val

    G2 = rt.graph_utils.graph_from_script(dedent("""\n
    import pygraphrt as rt
    G = rt.GraphRT()
    @G.node(val=10)
    def identity(value):
        return value
    """), 'G')

    rt.patch(G, G2)
    assert G.to_dict() == G2.to_dict(), "Graph patch should update the first graph to match the second graph"

    G.output = G.get_node('identity')
    with pytest.raises(TypeError):
        G.execute()

def test_setting_output():
    G = rt.GraphRT()
    @G.node()
    def identity(val):
        return val

    G.output = G.get_node('identity')
    assert G.output == G.get_node('identity'), "Setting the output node should update the graph's output"

    G2 = rt.graph_utils.graph_from_script(dedent("""\n
    import pygraphrt as rt
    G = rt.GraphRT()
    @G.node()
    def other_node():
        return 'other node'

    G.output = other_node
    """), 'G')

    rt.patch(G, G2)
    assert G.to_dict()['output'] == G2.to_dict()['output'], "Graph patch should update the first graph to match the second graph"

def test_replace_output_node():
    G = rt.GraphRT()

    @G.node(43)
    def const1(val):
        return val

    @G.node(34)
    def const2(val):
        return val

    @G.node(a=const1, b=const2)
    def mult(a, b):
        return a * b

    G.output = mult

    G2 = rt.graph_utils.graph_from_script(dedent("""\
    from pygraphrt import GraphRT
    G = GraphRT()

    @G.node(43)
    def const1(val):
        return val

    @G.node(34)
    def const2(val):
        return val

    @G.node(a=const1, b=const2)
    def the_modules(a, b):
        return a * b

    G.output = the_modules
    """), 'G')

    rt.patch(G, G2)

    G.execute()

if __name__ == "__main__":
    pytest.main([__file__, "-vv"])

