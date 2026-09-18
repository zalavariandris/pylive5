from typing import Callable
import inspect
from .graph_rt import GraphRT, NodeRT

def get_in_links(graph:GraphRT, node: NodeRT) -> set[tuple[NodeRT, int | str, NodeRT]]:
    """Returns the set of nodes that are direct inputs to the given node, along with their input keys."""
    args, kwargs = node.get_inputs()
    in_links = set()
    for idx, value in enumerate(args):
        if isinstance(value, NodeRT):
            in_links.add((value, idx, node))
    for key, value in kwargs.items():
        if isinstance(value, NodeRT):
            in_links.add((value, key, node))
    return in_links

def get_out_links(graph:GraphRT, node: NodeRT) -> set[tuple[NodeRT, int | str, NodeRT]]:
    """Returns the set of nodes that directly use the given node as an input, along with the input keys."""
    out_links = set()
    successors_map = graph._successors
    for successor_node in successors_map.get(node, set()):
        args, kwargs = successor_node.get_inputs()
        for idx, value in enumerate(args):
            if value is node:
                out_links.add((node, idx, successor_node))
        for key, value in kwargs.items():
            if value is node:
                out_links.add((node, key, successor_node))
    return out_links

def args_to_kwargs(func, *args, **kwargs):
    inspect_signature = inspect.signature(func)
    for param in inspect_signature.parameters.values():
        param_name = param.name
    """Converts positional arguments to keyword arguments."""
    args_dict = {i: arg for i, arg in enumerate(args)}
    args_dict.update(kwargs)
    return args_dict

def graph_from_script(script: str, graph="G") -> GraphRT:
    """Creates a GraphRT object from a Python script."""
    import hashlib, linecache
    # register source with linecache so inspect.getsource works on exec'd functions
    filename = f"<graph_script_{hashlib.md5(script.encode()).hexdigest()}>"
    code = compile(script, filename, "exec")
    linecache.cache[filename] = (len(script), None, script.splitlines(keepends=True), filename)
    locals_dict = {}
    exec(code, locals_dict)
    return locals_dict[graph]

def func_from_source(script: str, name:str|None=None) -> Callable:
    """Compiles the given source code into a callable function."""
    #todo: consider using a more secure execution environment!
    import hashlib, linecache
    # register source with linecache so inspect.getsource works on exec'd functions
    filename = f"<graph_script_{hashlib.md5(script.encode()).hexdigest()}>"
    code = compile(script, filename, "exec")
    linecache.cache[filename] = (len(script), None, script.splitlines(keepends=True), filename)
    locals_dict = {}
    exec(code, locals_dict)

    if name is not None:
        # find the function with the given name in the locals_dict
        if name not in locals_dict:
            raise ValueError(f"Function '{name}' not found in the source.")
        func = locals_dict[name]
        if not callable(func):
            raise ValueError(f"'{name}' is not a callable function.")
        return func
    else:
        # find the last function defined in the locals_dict
        function_objects = list(
            filter(lambda item: callable(item), locals_dict.values())
        )
        if not function_objects:
            raise ValueError("No function found in the source.")

        return function_objects[-1]
