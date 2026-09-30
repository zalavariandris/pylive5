"""Serialization and deserialization of a graph with its modules."""
from pathlib import Path
import warnings

from pygraphrt.abstract_operator import AbstractOperator
from pygraphrt.import_module import ImportModuleRT
from .abstract_module_rt import AbstractModule

from .script_module import ScriptModuleRT, ScriptOperatorRef

from .graph_definition_rt import GraphDefinitionRT, NodeRef
from .module_registry import ModuleRegistry

import math

def _encode_value(value):
    from .graph_definition_rt import NodeRef

    if type(value) in (type(None), bool, int, str):
        return value

    if type(value) is float:
        return value if math.isfinite(value) else {"type": "float", "value": value.hex()}

    if type(value) is list:
        return [_encode_value(item) for item in value]

    if type(value) is tuple:
        return {"type": "tuple", "items": [_encode_value(item) for item in value]}

    if type(value) is dict:
        return {"type": "dict", "items": [
            [_encode_value(key), _encode_value(item)]
            for key, item in value.items()
        ]}

    if isinstance(value, Path):
        return {"type": "path", "value": str(value)}
    
    raise TypeError(f"Cannot save input of type: {type(value).__name__!r}")

def _decode_value(value):
    if type(value) in (type(None), bool, int, float, str):
        return value
    
    if isinstance(value, list):
        return [_decode_value(item) for item in value]
    
    if not isinstance(value, dict):
        raise ValueError("Invalid input value")
    
    match value:
        case {"type": "tuple", "items": list(items)}:
            return tuple(_decode_value(item) for item in items)

        case {"type": "dict", "items": list(items)}:
            return {_decode_value(key): _decode_value(item) for key, item in items}

        case {"type": "path", "value": str(path)}:
            return Path(path)

        case {"type": "float", "value": str(number)}:
            return float.fromhex(number)
        
    raise ValueError(f"Invalid tagged input: {value!r}")




class GraphSerializer:
    def __init__(self, graph:GraphDefinitionRT, registry:ModuleRegistry, *, base_dir:Path|None=None):
        self._base_dir = base_dir
        self.graph = graph
        self.registry = registry

    def _get_module_pointer(self, module: ScriptModuleRT) -> dict:
        return module.get_display_name()

    def _get_operator_pointer(self, operator: AbstractOperator)->dict:
        assert isinstance(operator, ScriptOperatorRef), "Operator must be an instance of ScriptOperatorRef"
        module = operator.get_module()
        assert module in self.registry.modules(), "Module must be registered in the module registry"
        module_name = module.get_display_name()
        assert module_name is not None, "Module name must not be None at this point. Probably it was not saved?"
        # todo: review unnamed modules... We want to be able to create new modules, that has no real filepath initally. but it could have a nem like untitled1. This could be handled by the registry?
        op_data = {
            'module': self._get_module_pointer(module),
            'name': operator.get_name()
        }
        return op_data

    def _node_todict(self, node:NodeRef, explicit: bool = False)->dict:
        node_data = dict()
        # operator
        op = node.get_operator()

        if op is not None or explicit:
            node_data["operator"] = self._get_operator_pointer(op)

        # inputs
        args, kwargs = node.get_inputs()
        args_data = [
            {'type': 'node', 'name': value.get_name()} if isinstance(value, NodeRef) else {'type': 'literal', 'value': value}
            for value in args
        ]
        if args_data or explicit:
            node_data["args"] = args_data

        kwargs_data = {
            inlet: {'type': 'node', 'name': value.get_name()} if isinstance(value, NodeRef) else {'type': 'literal', 'value': value}
            for inlet, value in kwargs.items()
        }
        if kwargs_data or explicit:
            node_data["kwargs"] = kwargs_data

        return node_data

    def _module_todict(self, module) -> dict:
        match module:
            case ImportModuleRT():
                return {
                    'type': 'import',
                    'path': str(Path(self._base_dir / module.path()).relative_to(self._base_dir)) if self._base_dir is not None else str(module.path())
                }
            case ScriptModuleRT():
                return {
                    'type': 'embedded',
                    'source': module.get_source()
                }
            case _:
                raise ValueError(f"Unsupported module type: {type(module)}")

    def todict(self, explicit: bool = False)->dict:
        """Convert the entire graph and its modules to a json compatible dictionary representation.

        Args:
            explicit (bool): If True, include all fields even if they are empty.

        Returns:
            dict: The dictionary representation of the graph and its modules.
        """
        # Implement the serialization logic here

        # = VALIDATE =
        # runtime node decorators are not supported in initializations.
        # warn that these are skipped.
        # the current format supports embedded script modules and 
        # import modules

        # frontmatter
        data = {
            "version": "0.1.2"
        }

        # modules
        # 'modules': {
        #     '_local_': {
        #         'type': 'embedded',
        #         'source': '<local_module_source>'
        #     },
        #     '<module_name>': {
        #         'type': 'import',
        #         'path': '<module_path>'
        #     },
        # },
        modules_data = dict()
        for module in self.registry.modules():
            modules_data[self._get_module_pointer(module)] = self._module_todict(module)

        if modules_data or explicit:
            data['modules'] = modules_data

        # graph
        # 'graph': {
                #     'nodes': {
                #         '<node_name>': {
                #             'operator': {
                #                 'module': '<module_name>',
                #                 'name': '<operator_name>'
                #             },
                #             'args': [
                #                 # List of input node names
                #             ],
                #             'kwargs': {
                #                 # Dictionary of keyword arguments for the node
                #             }
                #         }
                #     }
                # }

        data['graph'] = {}
        nodes_data = dict()
        for node in self.graph.nodes():
            node_data = self._node_todict(node, explicit=explicit)
            nodes_data[node.get_name()] = node_data

        if nodes_data or explicit:
            data['graph']["nodes"] = nodes_data

        return data

class GraphDeserializer:
    def __init__(self, *, base_dir:Path|None=None):
        self._base_dir = base_dir
        # validate the input data with schema
        ...

    def fromdict(self, data:dict) -> tuple[ModuleRegistry, GraphDefinitionRT]:
        """Converts a json-compatible dictionary representation back into a ModuleRegistry and GraphDefinitionRT.

        Args:
            data (dict): The dictionary representation of the graph and its modules. Must be json-compatible.

        Returns:
            tuple[ModuleRegistry, GraphDefinitionRT]: The deserialized module registry and graph definition.
        """
        # == deserialize modules ==
        registry = ModuleRegistry()
        for module_name, module_data in data.get('modules', {}).items():
            match module_data['type']:
                case 'import':
                    module_path = Path(module_data['path'])
                    if self._base_dir is not None:
                        module_path = Path(self._base_dir / module_path)
                    module = ImportModuleRT(module_name, path=module_path)
                    try:
                        module.reload_file()
                    except FileNotFoundError as e:
                        warnings.warn(f"Module file not found for '{module_name}': {e}")
                case 'embedded':
                    module = ScriptModuleRT(module_name)
                    module.set_script(module_data['source'])
                case _:
                    raise ValueError(f"Unsupported module type: {module_data['type']}")
            registry.add_module(module)

        # == deserialize graph nodes ==
        graph = GraphDefinitionRT()

        # create empty nodes
        _nodes_by_name:dict[str, NodeRef] = dict()
        for node_name, node_data in data.get('graph', {}).get('nodes', {}).items():
            node_ref = graph._create_node(name=node_name)
            _nodes_by_name[node_name] = node_ref

        # == collect operator information for each node ==
        _operator_by_nodename: dict[str, AbstractOperator|None] = dict()
        for node_name, node_data in data.get('graph', {}).get('nodes', {}).items():
            operator_info = node_data.get('operator', {})
            module_name = operator_info.get('module')
            operator_name = operator_info.get('name')
            operator = registry.find_module_by_name(module_name).get_operator_by_name(operator_name)
            _operator_by_nodename[node_name] = operator

        # == collect operator information for each node ==
        _inputs_by_node:dict[str, tuple[list[NodeRef], dict[str, NodeRef]]] = dict()

        for node_name, node_data in data.get('graph', {}).get('nodes', {}).items():
            args = []
            for value in node_data.get('args', []):
                match value['type']:
                    case 'node':
                        args.append(_nodes_by_name[value['name']])
                    case 'literal':
                        args.append(value['value'])

            kwargs = dict()
            for inlet, value in node_data.get('kwargs', dict()).items():
                match value['type']:
                    case 'node':
                        kwargs[inlet] = _nodes_by_name[value['name']]
                    case 'literal':
                        kwargs[inlet] = value['value']

            _inputs_by_node[node_name] = args, kwargs


        # == uppdate each nodes ==
        for node_name in data.get('graph', {}).get('nodes', {}):
            node_ref = _nodes_by_name[node_name]
            operator = _operator_by_nodename[node_name]
            args, kwargs = _inputs_by_node[node_name]
            graph._update_node(node_ref, operator, args, kwargs)

        return registry, graph