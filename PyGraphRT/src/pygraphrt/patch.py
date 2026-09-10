import dictdiffer
from .graph_rt import GraphRT, NodeRT
from .utils import func_from_source


def _resolve_args(graph: GraphRT, args:tuple):
    assert isinstance(args, (list, tuple)), f"Expected args to be a tuple, got {type(args)}"
    """Resolves any names in args to their corresponding NodeRT instances."""
    resolved_args = []
    for arg in args:
        if isinstance(arg, str):
            resolved_args.append(graph.get_node(arg))
        else:
            resolved_args.append(arg)
    return tuple(resolved_args)

def _resolve_kwargs(graph: GraphRT, kwargs:dict):
    assert isinstance(kwargs, dict), f"Expected kwargs to be a dict, got {type(kwargs)}"
    """Resolves any names in kwargs to their corresponding NodeRT instances."""
    resolved_kwargs = {}
    for key, value in kwargs.items():
        if isinstance(value, str):
            resolved_kwargs[key] = graph.get_node(value)
        else:
            resolved_kwargs[key] = value
    return resolved_kwargs

def patch_operators(graph1: GraphRT, operators: dict):
    ...

def patch(graph1: GraphRT, graph2: GraphRT):
    op_changes = dictdiffer.diff(graph1.to_dict()['operators'], graph2.to_dict()['operators'], dot_notation=False)
    
    for action, path, values in op_changes:
        match action, path:
            case 'add', ():
                for key, value in values:
                    func = func_from_source(value)
                    assert func.__name__ == key, f"Function name '{func.__name__}' does not match expected operator name '{key}'"
                    graph1.op()(func) # add operator to graph

            case 'remove', ():
                for key, value in values:
                    op = graph1.get_operator(key)
                    assert op is not None, f"Operator '{key}' not found in graph1"
                    graph1.remove_operator(op) # remove operator from graph

            case 'change', (_, ):
                operator_name = path[0]
                op = graph1.get_operator(operator_name)
                assert op is not None, f"Operator '{operator_name}' not found in graph1"
                prev_value, next_value = values
                func = func_from_source(next_value)
                op.set_function(func)

            case _:
                raise NotImplementedError(f"Operator patch not implemented: Action: {action}, Path: {path!r}, Values: {values}")

    node_changes = dictdiffer.diff(graph1.to_dict()['nodes'], graph2.to_dict()['nodes'], dot_notation=False)
    for action, path, values in node_changes:
        print(f"Action: {action}, Path: {path}, Values: {values}")
        match action, path:
            case 'add', ():
                # raise NotImplementedError(f"Adding new nodes is not implemented yet. {action}, {path}, {value}")
                for node_name, node_data in values:
                    op_name = node_data['operator']
                    op = graph1.get_operator(op_name) # ensure operator exists
                    new_args = _resolve_args(graph1, node_data.get('args', ()))
                    new_kwargs = _resolve_kwargs(graph1, node_data.get('kwargs', {}))
                    n = graph1.node(*new_args, **new_kwargs)(op, node_name) # add node to graph

            case 'remove', ():
                # remove node
                for node_name, node_data in values:
                    node = graph1.get_node(node_name)
                    assert node is not None, f"Node '{node_name}' not found in graph1"
                    graph1._nodes.remove(node) # remove node from graph

            case 'add', (_, ):
                node_name = path[0]
                node = graph1.get_node(node_name)
                assert node is not None, f"Node '{node_name}' not found in {graph1}"
                for attr, new_args in values:
                    match attr:
                        case 'args':
                            new_args = _resolve_args(graph1, new_args)
                            node.set_inputs(*new_args, **node.get_inputs()[1]) # update node inputs

                        case 'kwargs':
                            new_kwargs = _resolve_kwargs(graph1, new_args)
                            node.set_inputs(*node.get_inputs()[0], **new_kwargs) # update node inputs

                        case _:
                            raise ValueError(f"Unknown node attribute change: {attr}")

            case 'remove', (_, ):
                for key, old_value in values:
                    match key:
                        case 'args':
                            node_name = path[0]
                            node = graph1.get_node(node_name)
                            assert node is not None, f"Node '{node_name}' not found in {graph1}"
                            old_args, old_kwargs = node.get_inputs()
                            node.set_inputs(**old_kwargs) # restore old inputs
                        case 'kwargs':
                            node_name = path[0]
                            node = graph1.get_node(node_name)
                            assert node is not None, f"Node '{node_name}' not found in {graph1}"
                            old_args, old_kwargs = node.get_inputs()
                            node.set_inputs(*old_args) # restore old inputs
                        case _:
                            pass
                # raise ValueError(f"Unknown node removal action")

            case 'add', (_,_):
                node_name = path[0]
                match path[1]:
                    case 'args':
                        for idx, new_value in values:
                            node = graph1.get_node(node_name)
                            assert node is not None, f"Node '{node_name}' not found in {graph1}"
                            if input_node := graph1.get_node(new_value):
                                # resolve input to node, input string is the name of the node
                                new_value = input_node
                            new_args = list(node.get_inputs()[0])
                            assert idx == len(new_args), f"Expected index {idx} to be equal to the length of current args"
                            new_args.append(new_value) # update the specific arg
                            node.set_inputs(*new_args, **node.get_inputs()[1]) # update node inputs

                    case 'kwargs':
                        for key, new_value in values:
                            node = graph1.get_node(node_name)
                            assert node is not None, f"Node '{node_name}' not found in {graph1}"
                            if input_node := graph1.get_node(new_value):
                                # resolve input to node, input string is the name of the node
                                new_value = input_node
                            new_kwargs = node.get_inputs()[1]
                            new_kwargs[key] = new_value # update the specific kwarg
                            node.set_inputs(*node.get_inputs()[0], **new_kwargs) # update node inputs
                        
                    case _:
                        raise ValueError(f"Unknown node attribute change: {path[1]}")

            case 'change', (_,'args',_):

                node_name, attr, key = path
                # args at idx(key) changed
                node = graph1.get_node(node_name)
                
                _, new_value = values
                if input_node := graph1.get_node(new_value):
                    # resolve input to node, input string is the name of the node
                    new_value = input_node
                args, kwargs = node.get_inputs()
                new_args = list(args)
                new_args[key] = new_value # update the specific kwarg
                print(f"set inputs for node {node_name}: {new_args}, kwargs: {kwargs}")
                node.set_inputs(*new_args, **kwargs) # update node inputs

            case 'change', (_,'kwargs',_):
                node_name, attr, key = path
                # kwargs changed
                node = graph1.get_node(node_name)
                args, new_kwargs = node.get_inputs()
                _, new_value = values
                if input_node := graph1.get_node(new_value):
                    # resolve input to node, input string is the name of the node
                    new_value = input_node
                new_kwargs[key] = new_value # update the specific kwarg
                node.set_inputs(*args, **new_kwargs) # update node inputs

            case 'remove', (_,_):
                node_name = path[0]
                match path[1]:
                    case 'args':
                        for idx, _ in values:
                            node = graph1.get_node(node_name)
                            args, new_kwargs = node.get_inputs()
                            new_args = list(args)
                            new_args.pop(idx) # remove the specific arg
                            node.set_inputs(*new_args, **new_kwargs) # update node inputs

                    case 'kwargs':
                        for key, _ in values:
                            node = graph1.get_node(node_name)
                            args, new_kwargs = node.get_inputs()
                            new_kwargs.pop(key) # remove the specific kwarg
                            node.set_inputs(*args, **new_kwargs) # update node inputs

            case 'change', (_,'operator'):
                assert path[0] in graph1._nodes, f"Node {path[0]} not found in graph1"
                raise NotImplementedError(f"Changing node operator is not implemented yet. {action}, {path}, {values}")

            case _:
                raise ValueError(f"Unknown node change: {action}, {path}, {values}")

    match (graph1.output, graph2.output):
        case (None, None):
            pass
        case (_, None):
            graph1.output = None
        case (None, _):
            graph1.output = graph1.get_node(graph2.output.get_name())
        case (_, _):
            if graph1.output.get_name() != graph2.output.get_name():
                graph1.output = graph1.get_node(graph2.output.get_name())
