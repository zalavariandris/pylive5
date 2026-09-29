"""Unit tests for the GraphBinder class."""


from textwrap import dedent

import pytest
import pygraphrt as rt

ResolverFixture = tuple[
    rt.GraphDefinitionRT, rt.ScriptModuleRT, rt.ScriptModuleRegistry, rt.GraphResolver
]

# @pytest.fixture
# def graph():
#     G = rt.GraphDefinitionRT()
#     return G

# @pytest.fixture
# def module_registry():
#     script_module = rt.ScriptModule()
#     registry = rt.ScriptModuleRegistry()
#     registry.add_module(script_module)
#     return registry


@pytest.fixture
def hello_world_script():
    return dedent("""
    def the_name():
        return "Mása"

    def the_greeting():
        return "Hey"

    def hello_world(name:str, greeting: str="Hello"):
        return f"{the_greeting()} {the_name()}!"
    """)

@pytest.fixture
def broken_hello_world_script():
    return dedent("""
    def the_name(

    def the_greeting(

    def hello_world(name:str, 
    """)


@pytest.fixture
def graph_module_registry_resolver(hello_world_script:str):
    module = rt.ScriptModuleRT()
    module.set_script(hello_world_script)

    graph = rt.GraphDefinitionRT()
    graph._create_node(module.get_operator_by_name("the_name"))
    graph._create_node(module.get_operator_by_name("the_greeting"))
    graph._create_node(module.get_operator_by_name("hello_world"))

    registry = rt.ScriptModuleRegistry()
    registry.add_module(module)

    resolver = rt.GraphResolver(graph, registry)

    return graph, module, registry, resolver


def test_initial_resolution_exists(graph_module_registry_resolver):
    graph, module, registry, resolver = graph_module_registry_resolver

    tracker = []    
    @resolver.resolutions_changed.connect
    def _(changed_nodes):
        tracker.append(changed_nodes)

    all_resolutions = [resolver.resolution(node) for node in graph.nodes()]
    assert len(all_resolutions) == len(graph.nodes())
    assert all(resolution!=None for resolution in all_resolutions)
    assert all(isinstance(resolution, (rt.GraphResolver.ResolutionSuccess, rt.GraphResolver.ResolutionFailure)) for resolution in all_resolutions)

    assert len(tracker) == 0, "Expected no resolution changes initially"

def test_when_script_is_temporary_broken(graph_module_registry_resolver, hello_world_script, broken_hello_world_script):
    graph, module, registry, resolver = graph_module_registry_resolver

    tracker = []
    @resolver.resolutions_changed.connect
    def _(changed_nodes):
        tracker.append(changed_nodes)

    # Temporarily break the script
    module.set_script(broken_hello_world_script)

    assert len(tracker) == 1, "Expected exactly one resolution change after breaking the script"
    assert all(isinstance(resolver.resolution(node), rt.GraphResolver.ResolutionFailure) for node in graph.nodes()), "Expected all nodes to have ResolutionFailure after breaking the script"

    # Restore the original script to fix the resolution
    module.set_script(hello_world_script)
    assert len(tracker) == 2, "Expected one additional resolution change after restoring the script"
    assert all(isinstance(resolver.resolution(node), rt.GraphResolver.ResolutionSuccess) for node in graph.nodes())
    assert tracker == [set(graph.nodes()), set(graph.nodes())]
    

def test_module_removal_and_readdition(
    graph_module_registry_resolver: ResolverFixture,
    hello_world_script: str,
) -> None:
    graph, module, registry, resolver = graph_module_registry_resolver
    tracker: list[set[rt.NodeRef]] = []
    resolver.nodes_invalidated.connect(tracker.append)

    registry.remove_module(module)
    assert tracker == [set(graph.nodes())]
    assert all(isinstance(resolver.resolution(node), rt.GraphResolver.ResolutionFailure) for node in graph.nodes())

    # Unregistered modules must no longer forward operator events.
    forwarded: list[list[rt.OperatorRef]] = []
    registry.operators_removed.connect(forwarded.append)
    module.set_script("")
    assert forwarded == []
    assert len(tracker) == 1

    module.set_script(hello_world_script)
    registry.add_module(module)
    assert len(tracker) == 2
    assert all(isinstance(resolver.resolution(node), rt.GraphResolver.ResolutionSuccess) for node in graph.nodes())

    module.set_script("")
    assert len(forwarded) == 1
    assert len(tracker) == 3
    assert all(isinstance(resolver.resolution(node), rt.GraphResolver.ResolutionFailure) for node in graph.nodes())


def test_added_node_tracks_operator_removal(
    graph_module_registry_resolver: ResolverFixture,
) -> None:
    graph, module, registry, resolver = graph_module_registry_resolver
    tracker: list[set[rt.NodeRef]] = []
    resolver.nodes_invalidated.connect(tracker.append)
    node = graph._create_node(module.get_operator_by_name("the_name"))
    assert isinstance(resolver.resolution(node), rt.GraphResolver.ResolutionSuccess)
    assert tracker == [{node}]

    module.set_script("")
    assert isinstance(resolver.resolution(node), rt.GraphResolver.ResolutionFailure)
    assert tracker[-1] == set(graph.nodes())


def test_deleted_node_is_not_resolved_on_operator_events(
    graph_module_registry_resolver: ResolverFixture,
) -> None:
    graph, module, registry, resolver = graph_module_registry_resolver
    node = graph.nodes()[0]
    tracker: list[set[rt.NodeRef]] = []
    resolver.nodes_invalidated.connect(tracker.append)

    graph._delete_node(node)
    assert resolver.resolution(node) is None
    assert tracker == [{node}]

    module.set_script("")
    assert resolver.resolution(node) is None
    assert tracker == [{node}, set(graph.nodes())]


def test_rebound_node_tracks_its_new_operator(
    graph_module_registry_resolver: ResolverFixture,
) -> None:
    graph, module, registry, resolver = graph_module_registry_resolver
    other_module = rt.ScriptModuleRT()
    other_module.set_script("def replacement():\n    return 1\n")
    registry.add_module(other_module)
    node = graph.nodes()[0]
    graph._update_node(node, other_module.get_operator_by_name("replacement"))

    module.set_script("")
    assert isinstance(resolver.resolution(node), rt.GraphResolver.ResolutionSuccess)

    other_module.set_script("")
    assert isinstance(resolver.resolution(node), rt.GraphResolver.ResolutionFailure)


@pytest.mark.parametrize("create_before_resolver", [True, False])
def test_node_without_operator_is_unresolved(create_before_resolver: bool) -> None:
    graph = rt.GraphDefinitionRT()
    if create_before_resolver:
        node = graph._create_node()
    resolver = rt.GraphResolver(graph, rt.ScriptModuleRegistry())
    if not create_before_resolver:
        node = graph._create_node()

    assert isinstance(resolver.resolution(node), rt.GraphResolver.ResolutionFailure)


def test_operator_body_change_keeps_successful_resolution(
    graph_module_registry_resolver: ResolverFixture,
    hello_world_script: str,
) -> None:
    graph, module, registry, resolver = graph_module_registry_resolver
    tracker: list[set[rt.NodeRef]] = []
    resolver.nodes_invalidated.connect(tracker.append)
    module.set_script(hello_world_script.replace('return "Hey"', 'return "Welcome"'))

    assert all(isinstance(resolver.resolution(node), rt.GraphResolver.ResolutionSuccess) for node in graph.nodes())
    assert tracker == []

def test_module_events_update_missing_operator_reason() -> None:
    graph = rt.GraphDefinitionRT()
    module = rt.ScriptModuleRT()
    node = graph._create_node(rt.OperatorRef(module, "missing"))
    registry = rt.ScriptModuleRegistry()
    resolver = rt.GraphResolver(graph, registry)
    missing_module = resolver.resolution(node)
    assert isinstance(missing_module, rt.GraphResolver.ResolutionFailure)

    registry.add_module(module)
    missing_operator = resolver.resolution(node)
    assert isinstance(missing_operator, rt.GraphResolver.ResolutionFailure)
    assert missing_operator != missing_module

    registry.remove_module(module)
    assert resolver.resolution(node) == missing_module


def test_module_changed_handles_removed_operators(
    graph_module_registry_resolver: ResolverFixture,
) -> None:
    graph, module, registry, resolver = graph_module_registry_resolver
    # Simulate a batch update reported through modules_changed alone.
    module.blockSignals(True)
    try:
        module.set_script("")
    finally:
        module.blockSignals(False)
    registry.modules_changed.emit([module])

    assert all(isinstance(resolver.resolution(node), rt.GraphResolver.ResolutionFailure) for node in graph.nodes())


if __name__ == "__main__":
    pytest.main([__file__])