
import pytest

from textwrap import dedent

from pygraphrt import (
    GraphDefinitionRT,
    ModuleRegistry,
    ScriptModuleRT,
    ImportModuleRT,
    MemoryCache,
    GraphExecutorRT,
    GraphInvalidator,
    NodeRef,
    ExecutionSuccess,
    ExecutionFailure,
    FunctionOperator
)

def test_smoke_hello_world(subtests, tmp_path)->None:
    im = ImportModuleRT("hello_world")
    registry = ModuleRegistry()
    registry.add_module(im)
    graph = GraphDefinitionRT()
    executor = GraphExecutorRT(graph)

    invalidator = GraphInvalidator(graph, registry)
    nodes_invalidated_tracker:list[list[NodeRef]] = []

    @invalidator.nodes_invalidated.connect
    def on_nodes_invalidated(nodes):
        nodes_invalidated_tracker.append(nodes)
    
    # G.add_import(im)

    # with subtests.test(msg="Create and execute hello"):
    im.set_script("def hello( ") 
    assert 'hello' not in [op.get_name() for op in im.operators()], "The broken 'hello' operator should not exist yet."

    # with subtests.test("Finish the 'hello' operator"):
    im.set_script("def hello(): return 'Hello!'") 
    assert 'hello' in [op.get_name() for op in im.operators()], "The 'hello' operator should exist after a valid script was set."

    # with subtests.test("Add empty 'hello' node with the op"):
    # - Add empty 'hello' node with the op
    hello_op = im.get_operator_by_name("hello")
    hello_node = graph._create_node(hello_op)
    assert executor.execute(hello_node).result == 'Hello!', "The 'hello' node should execute successfully."

    # with subtests.test("Break the 'hello' operator"):
    im.set_script("def hello( ")
    assert 'hello' not in [op.get_name() for op in im.operators()], "The broken 'hello' operator should not exist yet."
    assert isinstance(executor.execute(hello_node), ExecutionFailure)
    assert hello_node in nodes_invalidated_tracker[-1], "The 'hello' node should be tracked as invalidated after the operator is broken."

    # with subtests.test("fix the hello op"):
    im.set_script("def hello(): return 'Hello!'") 
    assert 'hello' in [op.get_name() for op in im.operators()], "The 'hello' operator should exist after being fixed."
    assert hello_node in nodes_invalidated_tracker[-1], "The 'hello' node should be tracked as invalidated after the operator is fixed."
    assert executor.execute(hello_node).result == 'Hello!', "The 'hello' node should execute successfully after the operator is fixed."

    # with subtests.test("add the_name, and the_greeting operators"):
    im.set_script(dedent("""\
        def the_name():
            return 'Mása'

        def the_greeting():
            return 'Hey'

        def hello():
            return 'Hello!'
    """))
    the_name_op =     im.get_operator_by_name("the_name")
    the_greeting_op = im.get_operator_by_name("the_greeting")

    the_name_node =     graph._create_node(the_name_op)
    the_greeting_node = graph._create_node(the_greeting_op)

    # with subtests.test("update hello to use the_name and the_greeting"):
    im.set_script(dedent("""\
        def the_name():
            return 'Mása'

        def the_greeting():
            return 'Hey'

        def hello(name: str, greeting: str = 'Hello'):
            return f"{greeting} {name}!"
    """))

    assert hello_node in nodes_invalidated_tracker[-1], "The 'hello' node should be tracked as invalidated after the operator is updated."
    assert isinstance(executor.execute(hello_node), ExecutionFailure)

    # with subtests.test("connect the_name node to hello name input"):
    graph._update_node(hello_node, hello_op, kwargs={"name": the_name_node})

    # Execute the hello node after connecting the_name
    assert hello_node in nodes_invalidated_tracker[-1], "The 'hello' node should be tracked as invalidated after the operator is updated."
    assert executor.execute(hello_node).result == 'Hello Mása!', "The 'hello' node should execute successfully with the_name connected."

    # with subtests.test("connect the_greeting node to hello greeting input"):
    graph._update_node(hello_node, hello_op, kwargs={"name": the_name_node, "greeting": the_greeting_node})
    
    # Execute the hello node after connecting the_greeting
    assert hello_node in nodes_invalidated_tracker[-1], "The 'hello' node should be tracked as invalidated after the operator is updated."
    assert executor.execute(hello_node).result == 'Hey Mása!', "The 'hello' node should execute successfully with both the_name and the_greeting connected."

    # with subtests.test("add another module from file"):
    # create the file in pytest temporary directory
    temp_file = tmp_path / "another_module.py"
    temp_file.write_text(dedent("""\
        def another_function():
            return 'Another function!'
    """))


import numpy as np


def test_smoke_with_module_from_file_using_numpy( tmp_path)->None:
    imagi_script = dedent("""\
    import numpy as np
    import pathlib
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class ColorData:
        r: float
        g: float
        b: float
        a: float = 1.0

    @dataclass
    class ImageRGBA:
        data: np.ndarray

    def constant(width: int=512, height: int=512, color: ColorData=ColorData(0.5, 0.5, 0.5, 1.0))->ImageRGBA:
        return ImageRGBA(np.full((height, width, 4), [color.r, color.g, color.b, color.a], dtype=np.float32))

    def noise(
        w: int,
        h: int,
        amount: float = 0.15,
        seed: int = 1,
    ) -> np.ndarray:
        rng = np.random.default_rng(seed)

        noise = rng.random((h, w), dtype=np.float32)
        noise = 0.5 + (noise - 0.5) * amount

        out = np.empty((h, w, 4), dtype=np.float32)
        out[..., :3] = noise[..., None]
        out[..., 3] = 1.0

        return out

    def read(path: pathlib.Path)->ImageRGBA:
        return ImageRGBA(np.zeros((1, 1, 4), dtype=np.float32))

    def cornerpin(img: ImageRGBA)->ImageRGBA:
        return img

    def exposure(img: ImageRGBA, factor: float=0.0)->ImageRGBA:
        return img

    def temperature(img: ImageRGBA, value: float=0.0)->ImageRGBA:
        return img

    def img_to_np(img: ImageRGBA) -> np.ndarray:
        return img.data

    def merge(fg: ImageRGBA, bg: ImageRGBA) -> ImageRGBA:
        return fg+bg

    __all__ = [
        "constant",
        "read",
        "cornerpin",
        "exposure",
        "temperature",
        "img_to_np",
        "merge"
    ]

    """)
    imagi_path = tmp_path / "imagi_script.py"
    imagi_path.write_text(imagi_script)
    imagi = ImportModuleRT("imagi", imagi_path)
    # imagi.reload_file()
    
    assert len(imagi.operators()) > 0

    graph = GraphDefinitionRT()
    executor = GraphExecutorRT(graph)
    registry = ModuleRegistry()
    invalidator = GraphInvalidator(graph, registry)

    # with subtests.test("add another module from file"):
    # create the file in pytest temporary directory
    registry.add_module(imagi)
    assert imagi in set(registry.modules())

    # with subtests.test("create graph, executor, and invalidator"):
    tracker:list[list[NodeRef]] = []
    
    @invalidator.nodes_invalidated.connect
    def on_nodes_invalidated(nodes):
        tracker.append(nodes)

    ctx:dict = dict()
    exec(imagi_script, ctx)
    with pytest.raises(UnboundLocalError):
        # make sure exec did not populate ColorData in the local scope by mistake
        ColorData(1,1,1,1)
    ColorData = ctx['ColorData']
    ImageRGBA = ctx['ImageRGBA']
    constant_op = imagi.get_operator_by_name("constant")
    constant_node = graph._create_node(constant_op, [512, 512])

    execution = executor.execute(constant_node)
    assert isinstance(execution, ExecutionSuccess)
    # assert isinstance(execution.result, ImageRGBA), "Execution result is not an ImageRGBA, got {}".format(type(execution.result))
    assert execution.result.data.shape == (512, 512, 4)
    current_rgba = execution.result.data[0, 0]
    assert np.allclose(current_rgba, [0.5, 0.5, 0.5, 1.0]), f"Initial constant color does not match expected value got: {current_rgba}"

    # with subtests.test("set color input"):
    graph._update_node(constant_node, constant_op, [512, 512], {
        "color": ColorData(0.7, 0.7, 0.7, 1.0)
    })
    assert constant_node in tracker[-1], "Constant node was not tracked as invalidated"
    assert np.allclose(execution.result.data[0, 0], [0.5, 0.5, 0.5, 1.0]), "No change occured before execution"

    execution = executor.execute(constant_node)
    assert isinstance(execution, ExecutionSuccess)
    assert np.allclose(execution.result.data[0, 0], [0.7, 0.7, 0.7, 1.0]), "Constant color did not update after execution"

    # with subtests.test("image file changed"):
    #     new_imagi_script.
    #     imagi_path.write_text(new_imagi_script)



def test_graph_using_functions_direclty()->None:
    graph = GraphDefinitionRT()
    executor = GraphExecutorRT(graph)
    invalidator = GraphInvalidator(graph)
    tracker = []
    @invalidator.nodes_invalidated.connect
    def on_nodes_invalidated(nodes):
        tracker.append(nodes)

    @graph.node()
    def the_name():
        return "Mása"

    @graph.node()
    def the_greeting():
        return f"Hey"

    @graph.node(the_name, the_greeting)
    def hello_world(name:str, greeting:str="Hello"):
        return f"{greeting}, {name}!"

    execution = executor.execute(hello_world)
    assert isinstance(execution, ExecutionSuccess)
    assert execution.result == "Hey, Mása!"

    
    # update the node operator with another function
    def the_new_greeting():
        return "What's up"
    
    graph._update_node(the_greeting, FunctionOperator(the_new_greeting))
    assert the_greeting in tracker[-1], "Greeting node was not tracked as invalidated"
    execution = executor.execute(hello_world)
    assert isinstance(execution, ExecutionSuccess)
    assert execution.result == "What's up, Mása!"




if __name__ == "__main__":
    pytest.main([__file__, "-s"])