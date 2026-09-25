# REVIEW: keep round-trip execution, values, references, and editable broken
# source. Exact dictionary snapshots below can be relaxed during format design.
# Integration blocker, not grounds for removal: node(..., name=...) currently
# ignores the requested name when creating a node, affecting aliased fixtures.
import copy
import json
import math
from pathlib import Path

from pygraphrt.import_module import ImportModuleRT
import pytest

from pygraphrt import GraphRT, OperatorRef

from textwrap import dedent
import pprint

# REVIEW SIMPLIFY: keep the executable round trip; the full expected dictionary
# and exact top-level key set unnecessarily freeze optional-field omission.
def test_strictly_the_hello_world_graph_serialization() -> None:
    local_definitions = dedent("""\
        def the_name():
            return "Masa"

        def the_greeting():
            return "Hey"
        
        def hello_world(name:str, greeting:str='Hello'):
            return f"{greeting} {name}!"
        """)
    G = GraphRT()
    G.setLocalDefinitions(local_definitions)

    operators_by_name = {
        op.get_name(): op 
        for op in G.local().operators()
    }

    assert set(operators_by_name.keys()) == {"the_name", "the_greeting", "hello_world"}

    
    the_name = G.node()(operators_by_name["the_name"], name="the_name")
    the_greeting = G.node()(operators_by_name["the_greeting"], name="the_greeting")
    hello_world = G.node(the_name, the_greeting)(operators_by_name["hello_world"], name="hello_world")

    data = G.todict(explicit=False)
    assert set(data.keys()) == {"version", "_local_", "graph"}

    assert data["_local_"] == local_definitions
    assert data["graph"] == {
        "nodes": {
            "the_name": {
                "operator": "the_name"
            },
            "the_greeting": {
                "operator": "the_greeting"
            },
            "hello_world": {
                "operator": "hello_world",
                "args": [
                    {"type": "node", "name": "the_name"},
                    {"type": "node", "name": "the_greeting"}
                ]
            }
        }
    }

    loaded_graph = GraphRT.fromdict(data)
    loaded_data = loaded_graph.todict()
    import json
    assert loaded_data == data, f"Loaded data does not match original data: {json.dumps(loaded_data, indent=2)} != {json.dumps(data, indent=2)}"
    assert loaded_graph.execute(loaded_graph.nodes()[-1]) == G.execute(hello_world) == "Hey Masa!"


# REVIEW OUTDATED SETUP / SIMPLIFY: ImportModuleRT currently accepts str/None,
# not Path. Keep imported-operator round trips, but relax the full dictionary
# snapshot and exact empty-field omission while the format is being developed.
def test_strictly_the_hello_world_graph_serialization_with_imports(tmp_path: Path) -> None:
    # create the hello_world_operator.py file in pytest temp folder
    source = dedent("""\
        def the_name() -> str:
            return "Masa"

        def the_greeting() -> str:
            return "Hey"

        def hello_world(name: str, greeting: str = "Hello") -> str:
            return f"{greeting} {name}!"
        """)
    import_module_path = tmp_path / "hello_world_operators.py"
    import_module_path.write_text(source, encoding="utf-8")

    # create the runtime graph and add the imported module
    graph = GraphRT()
    import_module = ImportModuleRT(import_module_path)
    graph.add_import(import_module)

    # collect operators from the imported module
    operators_by_name = {op.get_name(): op for op in import_module.operators()}
    assert set(operators_by_name) == {"the_name", "the_greeting", "hello_world"}

    # create the nodes using the imported module
    the_name = graph.node()(operators_by_name["the_name"], name="the_name")
    the_greeting = graph.node()(operators_by_name["the_greeting"], name="the_greeting")
    hello_world = graph.node(the_name, the_greeting)(
        operators_by_name["hello_world"], name="hello_world"
    )

    # serialize the graph to a dictionary
    data = graph.todict(explicit=False)
    assert set(data.keys()) == {"version", "imports", "graph"}
    assert data['version'] == 1
    assert data['imports'] == [str(import_module_path)]
    assert data == {
        "version": 1,
        "imports": [str(import_module_path)],
        "graph": {
            "nodes": {
                "the_name": {
                    "operator": {"module": str(import_module_path), "name": "the_name"}
                },
                "the_greeting": {
                    "operator": {"module": str(import_module_path), "name": "the_greeting"}
                },
                "hello_world": {
                    "operator": {"module": str(import_module_path), "name": "hello_world"},
                    "args": [
                        {"type": "node", "name": "the_name"},
                        {"type": "node", "name": "the_greeting"}
                    ]
                }
            }
        }
    }

    loaded = GraphRT.fromdict(json.loads(json.dumps(data)))
    assert loaded.todict() == data
    assert loaded.local().get_script() == ""
    assert all(node.get_operator().module is loaded.imports()[0] for node in loaded.nodes())
    loaded_nodes = {node.get_name(): node for node in loaded.nodes()}
    assert loaded.execute(loaded_nodes["hello_world"]) == graph.execute(hello_world) == "Hey Masa!"


@pytest.mark.parametrize("explicit", [False, True])
def test_empty_graph_round_trip(explicit: bool) -> None:
    graph = GraphRT()
    data = graph.todict(explicit=explicit)
    expected: dict[str, object] = {"version": 1}
    if explicit:
        expected.update(imports=[], _local_="", graph={"nodes": {}})
    assert data == expected
    assert GraphRT.fromdict(data).todict(explicit=explicit) == data


@pytest.fixture
def graph():
    graph = GraphRT()
    graph.setLocalDefinitions("def op(*args, **kwargs): return args, kwargs")
    operator = OperatorRef(graph.local(), "op")
    source = graph.node(42)(operator, name="source")
    graph.node(source, "source", 42, "42", True, None, 1.5,
               nested={"type": "node", "name": "source", (1, 2): [3, (4, 5)]},
               path=Path("images/test.png"))(operator, name="target")
    return graph


def test_runtime_round_trip_preserves_values_and_forward_references(graph):
    data = graph.todict()
    assert isinstance(data["_local_"], str)
    assert "nodes" not in data
    records = data["graph"]["nodes"]
    assert all("position" not in record for record in records.values())
    data["graph"]["nodes"] = dict(reversed(list(records.items())))
    original = copy.deepcopy(data)
    loaded = GraphRT.fromdict(copy.deepcopy(data))
    assert data == original
    nodes = {node.get_name(): node for node in loaded.nodes()}
    args, kwargs = nodes["target"].get_inputs()
    assert args[0] == nodes["source"]
    assert args[1:] == ("source", 42, "42", True, None, 1.5)
    assert [type(value) for value in args[1:]] == [str, int, str, bool, type(None), float]
    assert kwargs["nested"] == {"type": "node", "name": "source", (1, 2): [3, (4, 5)]}
    assert kwargs["path"] == Path("images/test.png")
    assert loaded.execute(nodes["target"]) == graph.execute(graph.nodes()[1])
    assert loaded.todict() == data


# REVIEW UNNECESSARY / DEFER: checks only the exact representation of empty
# inputs in explicit mode. Empty-graph and executable round trips provide the
# important behavior without making this output-format choice permanent.
def test_explicit_empty_node_inputs():
    graph = GraphRT()
    graph.setLocalDefinitions("def one(): return 1")
    one_op = list(graph.local().operators())[0]
    graph.node()(one_op, name="one")

    explicit_data = graph.todict(explicit=True)["graph"]["nodes"]["one"]
    assert explicit_data["args"] == []
    assert explicit_data["kwargs"] == {}

# REVIEW OUTDATED SETUP / KEEP: ImportModuleRT(path) now needs str(path).
# Module-qualified identity is essential; same names must not select the wrong op.
def test_imports_and_local_disambiguate_operator_names(tmp_path):
    path = tmp_path / "tools.py"
    path.write_text("def op(): return 42", encoding="utf-8")
    graph = GraphRT()
    graph.setLocalDefinitions("def op(value): return value * 2")
    import_module = ImportModuleRT(path)
    graph.add_import(import_module)
    source = graph.node()(OperatorRef(import_module, "op"), name="source")
    graph.node(source)(OperatorRef(graph.local(), "op"), name="target")
    assert graph.todict()["imports"] == [str(path)]
    records = graph.todict()["graph"]["nodes"]
    assert records["source"]["operator"] == {"module": str(path), "name": "op"}
    assert records["target"]["operator"] == "op"
    loaded = GraphRT.fromdict(graph.todict())
    assert loaded.execute(loaded.nodes()[1]) == 84
    assert loaded.nodes()[0].get_operator().module is loaded.imports()[0]
    assert loaded.nodes()[1].get_operator().module is loaded.local()


@pytest.mark.parametrize("explicit", [False, True])
def test_same_basename_imports_round_trip(tmp_path: Path, explicit: bool) -> None:
    graph = GraphRT()
    paths: list[str] = []
    for index, folder in enumerate(("first", "second")):
        directory = tmp_path / folder
        directory.mkdir()
        path = directory / "tools.py"
        path.write_text(f"def value(): return {index}", encoding="utf-8")
        module = ImportModuleRT(str(path))
        module.set_display_name("display label")
        graph.add_import(module)
        graph.node()(OperatorRef(module, "value"), name=folder)
        paths.append(str(path))

    data = graph.todict(explicit=explicit)
    assert data["imports"] == paths
    for name, path in zip(("first", "second"), paths):
        assert data["graph"]["nodes"][name]["operator"] == {
            "module": path, "name": "value"
        }
    loaded = GraphRT.fromdict(json.loads(json.dumps(data)))
    assert loaded.todict(explicit=explicit) == data
    assert [loaded.execute(node) for node in loaded.nodes()] == [0, 1]


@pytest.mark.parametrize("imports", [
    {"tools": "tools.py"}, [42], [None], [[]], [""], ["_local_"],
    ["tools.py", "tools.py"],
])
def test_invalid_import_paths_are_rejected(imports: object) -> None:
    with pytest.raises(ValueError):
        GraphRT.fromdict({"version": 1, "imports": imports})


def test_duplicate_import_paths_cannot_be_saved() -> None:
    graph = GraphRT()
    for _ in range(2):
        graph.add_import(ImportModuleRT("tools.py"))
    with pytest.raises(ValueError, match="unique"):
        graph.todict()


# REVIEW OUTDATED SETUP / KEEP: use a string path when migrating. Preserving
# unused imports protects editable documents from losing user-added modules.
def test_unused_imports_survive(tmp_path):
    path = tmp_path / "unused.py"
    path.write_text("def unused(): return 1", encoding="utf-8")
    graph = GraphRT()
    import_module = ImportModuleRT(path)
    graph.add_import(import_module)
    loaded = GraphRT.fromdict(graph.todict())
    assert len(loaded.imports()) == 1
    assert loaded.imports()[0].path() == str(path)
    assert loaded.nodes() == []


@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan")])
def test_nonfinite_floats_use_json_tags(value):
    graph = GraphRT()
    graph.setLocalDefinitions("def op(value): return value")
    graph.node(value)(OperatorRef(graph.local(), "op"))
    encoded = json.dumps(graph.todict(), allow_nan=False)
    loaded = GraphRT.fromdict(json.loads(encoded))
    restored = loaded.nodes()[0].get_inputs()[0][0]
    assert math.isnan(restored) if math.isnan(value) else restored == value


# REVIEW UNNECESSARY CASES / MERGE: version, _local_, imports, node, args, and
# value repeat the structural validation/import-path matrices. Keep module and
# reference cases: undeclared modules and dangling links need semantic checks.
@pytest.mark.parametrize("damage", ["version", "_local_", "imports", "node", "module", "reference", "args", "value"])
def test_malformed_runtime_data_is_rejected(graph, damage):
    data = graph.todict()
    record = data["graph"]["nodes"]["target"]
    if damage == "version":
        data["version"] = 99
    elif damage == "_local_":
        data["_local_"] = {}
    elif damage == "imports":
        data["imports"] = {}
    elif damage == "node":
        data["graph"]["nodes"]["target"] = None
    elif damage == "module":
        record["operator"] = {"module": "unknown", "name": "op"}
    elif damage == "reference":
        record["args"][0]["name"] = "unknown"
    elif damage == "args":
        record["args"] = "bad"
    else:
        record["args"] = [{"type": "unknown"}]
    with pytest.raises(ValueError):
        GraphRT.fromdict(data)


def test_invalid_source_and_missing_operator_stay_editable():
    graph = GraphRT()
    graph.setLocalDefinitions("def op(:")
    
    
    graph.node()(OperatorRef(graph.local(), "op"))
    loaded = GraphRT.fromdict(graph.todict())
    assert loaded.local().get_script() == "def op(:"
    assert loaded.nodes()[0].get_operator().get_value() is None
    loaded.local().set_script("def op(): return 7")
    assert loaded.execute(loaded.nodes()[0]) == 7


def test_opaque_values_and_inline_functions_fail_explicitly(graph):
    graph.nodes()[0].set_inputs(object())
    with pytest.raises(TypeError, match="Cannot save input"):
        graph.todict()
    inline = GraphRT()

    @inline.node()
    def op():
        return 1

    with pytest.raises(ValueError, match="script module"):
        inline.todict()


# REVIEW UNNECESSARY / DEFER: fixes subclass-preserving construction without a
# concrete subclass use case here. Base GraphRT round trips cover current needs.
def test_fromdict_constructs_subclass(graph):
    class CustomGraph(GraphRT):
        pass

    assert isinstance(CustomGraph.fromdict(graph.todict()), CustomGraph)

