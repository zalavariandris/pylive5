
from pathlib import Path

from pygraphrt.import_module import ImportModuleRT
import pytest

from textwrap import dedent

from pygraphrt import (
    GraphDefinitionRT,
    ModuleRegistry,
    ScriptModuleRT,
    ImportModuleRT,
    GraphSerializer,
    GraphDeserializer
)

@pytest.fixture
def hello_world(tmp_path):
    registry = ModuleRegistry()
    module_path = tmp_path / "hello.py"
    module_path.write_text(dedent("""\
        def the_name():
            return 'Mása'

        def the_greeting():
            return 'Hey'

        def hello_world(name:str, greeting:str='Hello'):
            return f"{greeting}, {name}!"
    """
    ), encoding="utf-8")
    hello_module = ImportModuleRT("hello", path=module_path)
    registry.add_module(hello_module)
    graph = GraphDefinitionRT()
    
    the_name_node = graph._create_node(hello_module.get_operator_by_name("the_name"))
    the_greeting_node = graph._create_node(hello_module.get_operator_by_name("the_greeting"))
    hello_node = graph._create_node(hello_module.get_operator_by_name("hello_world"), [the_name_node, the_greeting_node])
    
    return registry, graph

def test_smoke_modules_serialization(hello_world, tmp_path):
    registry, graph = hello_world

    serializer = GraphSerializer(graph, registry, base_dir=tmp_path)

    data = serializer.todict()

    assert 'modules' in data
    assert 'hello' in data['modules'], f"Module not found in {[k for k in data['modules'].keys()]}"
    assert data['modules']['hello'].keys() == {"type", "path"}
    assert data['modules']['hello']['type'] == 'import'
    assert data['modules']['hello']['path'] == str(Path(tmp_path / "hello.py").relative_to(tmp_path))
    
def test_smoke_graph_serialization(hello_world):
    registry, graph = hello_world

    serializer = GraphSerializer(graph, registry)

    data = serializer.todict()

    assert 'graph' in data
    assert 'nodes' in data['graph']
    assert data['graph']['nodes'].keys() == {"the_name", "the_greeting", "hello_world"}

    for node_name, node_data in data['graph']['nodes'].items():
        assert 'operator' in node_data

    assert 'args' in data['graph']['nodes']["hello_world"]
    assert set(map(lambda x: x['name'], data['graph']['nodes']["hello_world"]['args'])) == {"the_name", "the_greeting"}



def test_roundtrip_serialization(tmp_path):
    hello_graph_file = tmp_path / "hello_graph.json"
    hello_world_module_file2 = tmp_path / "hello2.py"

    # save hello.py file
    hello_world_module_file2.write_text(
        dedent("""\
        def the_name():
            return 'Mása'

        def the_greeting():
            return 'Hey'

        def hello_world(name:str, greeting:str='Hello'):
            return f"{greeting}, {name}!"
        """),
        encoding="utf-8"
    )

    # save hello_graph.json file
    hello_graph_file.write_text(dedent("""\
    {
        "version": "0.1.2",
        "modules": {
            "hello2": {
                "type": "import",
                "path": "hello2.py"
            }
        },
        "graph": {
            "nodes": {
                "the_name": {
                    "operator": {"module": "hello2", "name": "the_name"}
                },
                "the_greeting": {
                    "operator": {"module": "hello2", "name": "the_greeting"}
                },
                "hello_world": {
                    "operator": {"module": "hello2", "name": "hello_world"},
                    "args": [
                        {"type": "node", "name": "the_name"},
                        {"type": "node", "name": "the_greeting"}
                    ]
                }
            }
        }
    }
    """))

    # load
    import json
    deserializer = GraphDeserializer(base_dir=tmp_path)
    loaded_data = json.loads(hello_graph_file.read_text(encoding="utf-8"))
    registry, graph = deserializer.fromdict(loaded_data)

    # sanity check
    assert registry is not None
    assert graph is not None
    assert len(registry.modules()) > 0
    assert len(graph.nodes()) > 0

    # serialize the graph again
    serializer = GraphSerializer(graph, registry, base_dir=tmp_path)
    roundtrip_data = serializer.todict()

    assert roundtrip_data["modules"] == loaded_data["modules"]
    assert roundtrip_data["graph"] == loaded_data["graph"]







if __name__ == "__main__":
    pytest.main([__file__, "-vv"])
