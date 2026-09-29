from textwrap import dedent

import pytest
import pygraphrt as rt

@pytest.fixture
def hello_world_script():
    return dedent("""\
        def the_name():
            return "Mása"

        def the_greeting():
            return "Hey"

        def hello_world(name:str, greeting:str="Hello"):
            print(f"{greeting}, {name}!")
    """)

@pytest.fixture
def broken_hello_world_script():
    return dedent("""\
        def the_name():
            return "Mása"

        def the_greeting():
            return "Hey"

        def hello_world(name:str, 
    """)

@pytest.fixture
def hello_world_graph(hello_world_script):
    module = rt.ScriptModuleRT()
    module.set_script(hello_world_script)

    graph = rt.GraphDefinitionRT()

    the_name = graph._create_node(module.get_operator_by_name("the_name"))
    the_greeting = graph._create_node(module.get_operator_by_name("the_greeting"))
    hello_world = graph._create_node(module.get_operator_by_name("hello_world"), [the_name])

    return graph, module, [the_name, the_greeting, hello_world]


def test_linkin_intermediate_nodes_invalidates_output_node():
    script_module = rt.ScriptModuleRT()
    script_module.operators_added
    script_module.set_script("dummy_script")
    graph = rt.GraphDefinitionRT()
    invalidator = rt.GraphInvalidator(graph, module_registry)

    tracker = []
    @invalidator.nodes_invalidated.connect
    def on_nodes_invalidated(nodes):
        tracker.extend(nodes)

    


def test_setting_node_inputs_invalidates_output_node():
    ...

def test_setting_node_operator_invalidates_output_node():
    ...

def test_setting_module_operator_invalidate_output_node():
    ...

if __name__ == "__main__":
    pytest.main()
