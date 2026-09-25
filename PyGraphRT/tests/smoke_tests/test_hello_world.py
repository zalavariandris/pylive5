from pygraphrt.abstract_module_rt import OperatorRef
from pygraphrt.errors import GraphExecutionError, ModuleError

import pytest
from pygraphrt import GraphRT, ImportModuleRT
from textwrap import dedent




# Def hello(

# Def hello(): return “Hello!”

# Add the node
# Execute ‘hello’ node
# Result==“Hello!”
# create the_name and the_greetin operators
# Add the new nodes
# update hello operator (broken; finished)
# execute broken
# Hello(name: str, greeting:str=‘Hello) s return f”{greeting} {name}!}”

# -execute hellow world operator : report kissong inputs

# connect the_name 
# Execute hello node
# Connect the greetong
# Execute hello node



# !parametrize the test to use ‘watch’ for live execution.


# Lets make the user test go through each layer: pygrapg rt; document; gui

def find_operator_by_name(im, name)->OperatorRef|None:
    return next((op for op in im.operators() if op.get_name() == name), None)

def test_smoke_hello_world():
    G = GraphRT()
    im = ImportModuleRT()
    G.add_import(im)

    # - Create a broken 'hello' operator
    im.set_script("def hello( ") 
    assert 'hello' not in [op.name for op in im.operators()], "The broken 'hello' operator should not exist yet."

    # - Finish the 'hello' operator
    im.set_script("def hello(): return 'Hello!'") 
    assert 'hello' in [op.name for op in im.operators()], "The 'hello' operator should exist after a valid script was set."

    # - Add empty 'hello' node with the op
    hello_op = find_operator_by_name(im, "hello")
    hello_node = G._create_node(hello_op)
    assert G.execute(hello_node) == 'Hello!', "The 'hello' node should execute successfully."

    # brake the hello op
    im.set_script("def hello( ") 
    assert 'hello' not in [op.name for op in im.operators()], "The broken 'hello' operator should not exist yet."
    with pytest.raises(GraphExecutionError): #todo: we need to review this behaviour. if modules report errors, instead of raising them we might want similar behaviour for the graph as well.
        assert G.execute(hello_node)

    # fix the hello op
    im.set_script("def hello(): return 'Hello!'") 
    assert 'hello' in [op.name for op in im.operators()], "The 'hello' operator should exist after being fixed."
    assert G.execute(hello_node) == 'Hello!', "The 'hello' node should execute successfully after the operator is fixed."

    # add the_name, and the_greeting operators
    im.set_script(dedent("""\
        def the_name():
            return 'Mása'

        def the_greeting():
            return 'Hey'

        def hello():
            return 'Hello!'
    """))
    the_name_op =     find_operator_by_name(im, "the_name")
    the_greeting_op = find_operator_by_name(im, "the_greeting")

    the_name_node =     G._create_node(the_name_op)
    the_greeting_node = G._create_node(the_greeting_op)

    # update hello to use the_name and the_greeting
    im.set_script(dedent("""\
        def the_name():
            return 'Mása'

        def the_greeting():
            return 'Hey'

        def hello(name: str, greeting: str = 'Hello'):
            return f"{greeting} {name}!"
    """))

    with pytest.raises(GraphExecutionError):
        G.execute(hello_node)

    # Connect the_name 
    G._update_node(hello_node, hello_op, kwargs={"name": the_name_node})

    # Execute the hello node after connecting the_name
    assert G.execute(hello_node) == 'Hello Mása!', "The 'hello' node should execute successfully with the_name connected."
    # Connect the_greeting
    G._update_node(hello_node, hello_op, kwargs={"name": the_name_node, "greeting": the_greeting_node})
    # Execute the hello node after connecting the_greeting
    assert G.execute(hello_node) == 'Hey Mása!', "The 'hello' node should execute successfully with both the_name and the_greeting connected."

if __name__ == "__main__":
    pytest.main([__file__, "-vv"])