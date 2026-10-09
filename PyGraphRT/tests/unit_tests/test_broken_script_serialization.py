
from pathlib import Path

from pygraphrt.import_module import ImportModuleRT
from pygraphrt.script_module import ScriptOperatorRef
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

def test_saving_broken_operators_than_load_back(tmp_path)->None:
    # setup
    registry = ModuleRegistry()
    module = ScriptModuleRT("broken_module")
    module.set_script(dedent("""\
        def hello(): return "bbom"
    """))
    registry.add_module(module)

    graph = GraphDefinitionRT()
    graph._create_node(module.get_operator_by_name("hello"))
    
    # Optionally, you can add assertions or further checks here to verify the graph's state
    assert len(graph.nodes()) == 1

    # NOW brake the script
    module.set_script(dedent("""\
        def hello(
    """))

    assert len(module.operators()) == 0
    assert len(graph.nodes()) == 1

    # node op is not inside the module, but it still retains a reference to the module
    node_op:ScriptOperatorRef = list(graph.nodes())[0].get_operator()
    assert isinstance(node_op, ScriptOperatorRef)
    assert node_op not in module.operators()
    assert node_op.get_module() == module

    # after a serializattionroundtrip, the node_op should still retain a reference to the module

    serialized_graph = GraphSerializer(graph, registry).todict()
    deserialized_registry, deserialized_graph = GraphDeserializer(base_dir=tmp_path).fromdict(serialized_graph)
    deserialized_module = deserialized_registry.find_module_by_name("broken_module")
    assert isinstance(deserialized_module, ScriptModuleRT)

    deserialized_node_op = list(deserialized_graph.nodes())[0].get_operator()
    assert isinstance(deserialized_node_op, ScriptOperatorRef)
    assert deserialized_node_op.get_name() == "hello"
    assert deserialized_node_op not in deserialized_module.operators()
    assert deserialized_node_op.get_module() is deserialized_module
    assert deserialized_module.get_source() == module.get_source()
    







if __name__ == "__main__":
    pytest.main([__file__, "-vv"])
