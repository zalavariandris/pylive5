"""Serialization and deserialization of a graph with its modules."""
from pygraphrt.import_module import ImportModuleRT
from .abstract_module import AbstractModuleRT

from .script_module import ScriptModuleRT, ScriptOperatorRef

from .graph_definition_rt import GraphDefinitionRT, NodeRef
from .module_registry import ModuleRegistry


class GraphSerializer:
    def __init__(self, graph:GraphDefinitionRT, registry:ModuleRegistry):
        self.graph = graph
        self.registry = registry

    def _get_module_pointer(self, module: ScriptModuleRT) -> dict:
        return module.get_display_name()

    def _get_operator_pointer(self, operator: AbstractModuleRT)->dict:
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

    def serialize_node(self, node, explicit: bool = False)->dict:
        node_data = dict()
        # operator
        op = node.get_operator()

        if op is not None or explicit:
            node_data["operator"] = self._get_operator_pointer(op)

        # inputs
        args_data = [
            value.get_name() if isinstance(value, NodeRef) else value
            for value in node.get_args()
        ]
        if args_data or explicit:
            node_data["args"] = args_data

        kwargs_data = {
            inlet: value.get_name() if isinstance(value, NodeRef) else value
            for inlet, value in node.get_kwargs().items()
        }
        if kwargs_data or explicit:
            node_data["kwargs"] = kwargs_data

        return node_data

    def _serialize_module(self, module) -> dict:
        match module:
            case ImportModuleRT():
                return {
                    'type': 'import',
                    'path': module.path()
                }
            case ScriptModuleRT():
                return {
                    'type': 'embedded',
                    'source': module.get_source()
                }
            case _:
                raise ValueError(f"Unsupported module type: {type(module)}")

    def serialize(self, explicit: bool = False)->dict:
        # Implement the serialization logic here

        # = VALIDATE =
        # runtime node decorators are not supported in initializations.
        # warn that these are skipped.
        # the current format supports embedded script modules and 
        # import modules

        # frontmatter
        data = {
            "version": "0.02"
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
            modules_data[self._get_module_pointer(module)] = self._serialize_module(module)

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
            node_data = self._serialize_node(node, explicit=explicit)
            nodes_data[node.get_name()] = node_data

        if nodes_data or explicit:
            data['graph']["nodes"] = nodes_data

        return data

class Deserializer:
    def __init__(self, data:dict):
        # validate the input data with schema"
        ...

    def deserialize(self)->tuple[GraphDefinitionRT, ModuleRegistry]:
        ...