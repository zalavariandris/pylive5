import dictdiffer
import json
import pytest
from textwrap import dedent
import pygraphrt as rt

from pygraphrt.graph_rt_serialize import _to_dict, serialize

import json

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

    serialized= _to_dict(G, explicit=False)

    assert serialized == {
        'two': {
            'operator': 'local.two'
        },
        'three': {
            'operator': 'local.three'
        },
        'add': {
            'operator': 'local.add',
            'kwargs': {
                'a': 'two',
                'b': 'three'
            }
        }
    }, f"Graph serialization should match expected structure: got: {serialized}"

def test_graph_nodes_explicit_serialization():
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

    expected_graph = {
        'two': {
            'operator': 'local.two',
            'args': [],
            'kwargs': {},
        },
        'three': {
            'operator': 'local.three',
            'args': [],
            'kwargs': {},
        },
        'add': {
            'operator': 'local.add',
            'args': [],
            'kwargs': {
                'a': 'two',
                'b': 'three'
            }
        }
    }

    serialized = _to_dict(G, explicit=True)['nodes']
    assert serialized == expected_graph, f"Graph serialization should match expected structure: got: {serialized}"

if __name__ == "__main__":
    pytest.main([__file__, "-vvv"]) 
    # G = rt.GraphRT()
    
    # @G.node()
    # def two() -> int:
    #     return 2

    # @G.node()
    # def three() -> int:
    #     return 3

    # @G.node(a=two, b=three)
    # def add(a:int, b:int) -> int:
    #     return a + b

    # print(serialize(G, explicit=True))

