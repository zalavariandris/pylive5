import dictdiffer
import json
from pygraphrt.import_module_rt import ImportModuleRT
from pygraphrt.script_module_rt import ScriptModuleRT
import pytest
from textwrap import dedent
import pygraphrt as rt

from pygraphrt.graph_rt_serialize import _to_dict, serialize
from pygraphrt.graph_rt_serialize import _from_dict, deserialize

import json

class TestNodesSerialization:
    def test_graph_nodes_implicit_serialization(self):
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

        assert serialized['nodes'] == {
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

    def test_graph_nodes_explicit_serialization(self):
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


class TestModulesSerialization:
    def test_script_module_serialization(self):
        from textwrap import dedent
        source = dedent("""\
        def value():
            return 1
        """)
        script_module = ScriptModuleRT("tools", source)
        serialized = _to_dict(script_module)
        assert serialized == {
            "source": source
        }

    def test_import_module_serialization(self):
        import_module = ImportModuleRT("tools", "tools.py")
        serialized = _to_dict(import_module)

        serialized = _to_dict(import_module)
        assert serialized == {
            "file": "tools.py"
        }


def test_graph_serialization():
    G = rt.GraphRT()
    script_module = ScriptModuleRT("tools", dedent("""\
    def value():
        return 1
    """))
    G.add_modules([script_module])


    serialized = _to_dict(G, explicit=False)

    assert 'modules' in serialized
    assert 'tools' in serialized['modules']
    assert serialized['modules']['tools']['source'] == dedent("""\
    def value():
        return 1
    """)
    assert 'nodes' in serialized


def test_graph_deserialization():
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

    serialized = _to_dict(G, explicit=False)
    deserialized = _from_dict(serialized)

    reserialized = _to_dict(deserialized, explicit=False)
    assert serialized == reserialized, f"Deserialized graph should match original serialization: got: {reserialized}"

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

