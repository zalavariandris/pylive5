import dictdiffer
import pytest
from textwrap import dedent
import pygraphrt as rt

def test_graph_ops_serialization():
    G = rt.GraphRT()

    @G.node()
    def two() -> int:
        return 2

    two_source=dedent("""\
    def two() -> int:
        return 2
    """)

    @G.node()
    def three() -> int:
        return 3

    three_source=dedent("""\
    def three() -> int:
        return 3
    """)

    @G.node(a=two, b=three)
    def add(a:int, b:int) -> int:
        return a + b

    add_source = dedent("""\
    def add(a:int, b:int) -> int:
        return a + b
    """)


    assert G.to_dict()['operators'] == {
        'two': two_source,
        'three': three_source,
        'add': add_source
    }, "Graph serialization should match expected structure"

def test_graph_nodes_implicit_serialization():
    G = rt.GraphRT()

    @G.node()
    def two() -> int:
        return 2

    @G.node()
    def three() -> int:
        return 3

    @G.node(a=two, b=three)
    def add(a:int, b:int) -> int:
        return a + b

    assert G.to_dict(explicit=False)['nodes'] == {
        'two': {
            'operator': 'two'
        },
        'three': {
            'operator': 'three'
        },
        'add': {
            'operator': 'add',
            'kwargs': {
                'a': 'two',
                'b': 'three'
            }
        }
    }, "Graph serialization should match expected structure"

def test_graph_nodes_explicitt_serialization():
    G = rt.GraphRT()

    @G.node()
    def two() -> int:
        return 2

    @G.node()
    def three() -> int:
        return 3

    @G.node(a=two, b=three)
    def add(a:int, b:int) -> int:
        return a + b

    expected_nodes = {
        'two': {
            'operator': 'two',
            'args': [],
            'kwargs': {},
        },
        'three': {
            'operator': 'three',
            'args': [],
            'kwargs': {},
        },
        'add': {
            'operator': 'add',
            'args': [],
            'kwargs': {
                'a': 'two',
                'b': 'three'
            }
        }
    }

    actual_nodes = G.to_dict(explicit=True)['nodes']
    assert actual_nodes == expected_nodes, f"Graph serialization should match expected structure: {dictdiffer.diff(expected_nodes, actual_nodes)}"

if __name__ == "__main__":
    pytest.main([__file__, "-vv"]) 

