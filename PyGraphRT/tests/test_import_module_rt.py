from textwrap import dedent

import pytest

from pygraphrt.abstract_module_rt import AbstractModuleRT
from pygraphrt.graph_rt import GraphRT
from pygraphrt.import_module_rt import ImportModuleRT
from pygraphrt.operator_rt import ParameterRT
from pygraphrt.script_module_rt import ScriptModuleRT
from pygraphrt.watch import watch


def write_source(path, source):
    path.write_text(dedent(source), encoding="utf-8")
    return path


@pytest.mark.parametrize("path_type", [str, lambda path: path], ids=["string", "path"])
def test_loads_imports_globals_helpers_aliases_and_parameters(tmp_path, path_type):
    path = write_source(tmp_path / "operators.py", """\
        import math
        from math import sqrt

        FACTOR = 2

        def helper(value):
            return math.floor(sqrt(value)) * FACTOR

        def result(value: int = 9) -> int:
            return helper(value)

        alias = result
    """)
    module = ImportModuleRT("tools", path_type(path), watch=False)

    assert isinstance(module, AbstractModuleRT)
    assert not isinstance(module, ScriptModuleRT)
    assert type(module.script_module) is ScriptModuleRT
    assert module.file_binding.path() == path
    assert module.get_script() == path.read_text(encoding="utf-8")
    assert set(module.operators()) == {"sqrt", "helper", "result", "alias"}
    result = module.get_operator("result")
    assert result() == 6
    assert module.get_operator("alias")(16) == 8
    assert module.get_operator("sqrt")(25) == 5
    assert dict(result.get_parameters()) == {"value": ParameterRT("value", int, 9)}

    exported = module.operators()
    exported.clear()
    assert module.get_operator("result") is result


def test_empty_source_file_is_valid(tmp_path):
    module = ImportModuleRT("empty", write_source(tmp_path / "empty.py", ""), watch=False)
    assert module.get_script() == ""
    assert module.operators() == {}
    assert module.get_operator("missing") is None


def test_edits_save_and_reload_preserve_operator_handles(tmp_path):
    initial = 'def value():\n    return "initial"\n'
    edited = 'def value():\n    return "árvíz"\n'
    external = 'def value():\n    return "external"\n'
    path = write_source(tmp_path / "operators.py", initial)
    module = ImportModuleRT("tools", path, watch=False)
    value = module.get_operator("value")

    module.set_script(edited)
    assert value() == "árvíz"
    assert path.read_text(encoding="utf-8") == initial
    module.file_binding.save()
    assert path.read_text(encoding="utf-8") == edited

    path.write_text(external, encoding="utf-8")
    module.file_binding.reload()
    assert module.get_operator("value") is value
    assert module.get_script() == external
    assert value() == "external"


def test_opening_identical_source_at_another_path_updates_file_context(tmp_path):
    source = "def location():\n    return __name__, __file__\n"
    first = write_source(tmp_path / "first.py", source)
    second = write_source(tmp_path / "second.py", source)
    module = ImportModuleRT("tools", first, watch=False)
    location = module.get_operator("location")
    fingerprint = location.fingerprint()

    module.file_binding.open(str(second))

    assert module.file_binding.path() == second
    assert module.get_operator("location") is location
    assert location() == ("tools", str(second))
    assert location.fingerprint() != fingerprint
    wrapped_location = module.script_module.get_operator("location")
    assert module.script_module._get_function(wrapped_location).__code__.co_filename == str(second)


@pytest.mark.parametrize("action", ["set_script", "set_text", "reload", "open"])
@pytest.mark.parametrize("bad_source, error", [
    ("def broken(:\n", SyntaxError),
    ("def replacement():\n    return 99\nraise RuntimeError('failed')\n", RuntimeError),
])
def test_failed_updates_keep_the_last_accepted_runtime(tmp_path, action, bad_source, error):
    source = "def value():\n    return 1\n"
    path = write_source(tmp_path / "operators.py", source)
    module = ImportModuleRT("tools", path, watch=False)
    value = module.get_operator("value")
    fingerprint = value.fingerprint()
    events = []
    failures = []
    module.script_failed.connect(failures.append)
    module.script_changed.connect(lambda: events.append("script"))
    module.operators_added.connect(lambda names: events.append(("added", names)))
    module.operators_removed.connect(lambda names: events.append(("removed", names)))
    module.operators_changed.connect(lambda names: events.append(("changed", names)))

    if action == "set_script":
        module.set_script(bad_source)
    elif action == "set_text":
        module.file_binding.set_text(bad_source)
    elif action == "reload":
        write_source(path, bad_source)
        module.file_binding.reload()
    else:
        path = write_source(tmp_path / "broken.py", bad_source)
        module.file_binding.open(path)

    assert len(failures) == 1
    assert isinstance(failures[0], error)
    assert module.file_binding.path() == path
    assert module.file_binding.get_text() == (source if action == "set_script" else bad_source)
    assert module.get_script() == source
    assert module.operators() == {"value": value}
    assert value() == 1
    assert value.fingerprint() == fingerprint
    assert events == []


def test_missing_file_errors_leave_the_module_usable(tmp_path):
    path = write_source(tmp_path / "operators.py", "def value():\n    return 1\n")
    module = ImportModuleRT("tools", path, watch=False)
    with pytest.raises(FileNotFoundError):
        module.file_binding.open(tmp_path / "missing.py")
    assert module.file_binding.path() == path
    path.unlink()
    with pytest.raises(FileNotFoundError):
        module.file_binding.reload()
    assert module.get_operator("value")() == 1


def test_reload_signals_are_batched_and_observe_committed_state(tmp_path):
    path = write_source(tmp_path / "operators.py", """\
        def removed():
            return 1
        def kept():
            return 2
    """)
    module = ImportModuleRT("tools", path, watch=False)
    kept = module.get_operator("kept")
    removed = module.get_operator("removed")
    events = []

    def observe(kind, names=None):
        events.append((kind, names, sorted(module.operators()), kept()))

    module.script_changed.connect(lambda: observe("script"))
    module.operators_removed.connect(lambda names: observe("removed", names))
    module.operators_added.connect(lambda names: observe("added", names))
    module.operators_changed.connect(lambda names: observe("changed", names))
    module.set_script("""\
def kept():
    return 20
def z_added():
    return 30
def a_added():
    return 40
""")

    assert module.get_operator("kept") is kept
    assert [(kind, names) for kind, names, _, _ in events] == [
        ("script", None), ("removed", ["removed"]),
        ("added", ["a_added", "z_added"]), ("changed", ["kept"]),
    ]
    assert all(names == ["a_added", "kept", "z_added"] and value == 20
               for _, _, names, value in events)
    assert not removed.isValid()
    assert dict(removed.get_parameters()) == {}
    with pytest.raises(ValueError):
        removed()
    with pytest.raises(ValueError):
        removed.fingerprint()


def test_exports_follow_executed_bindings_on_load_and_reload(tmp_path):
    source = """\
from math import sqrt
def outer():
    def inner():
        return 3
    return inner()
alias = outer
class Callable:
    def __call__(self):
        return 4
instance = Callable()
"""
    path = write_source(tmp_path / "operators.py", "")
    module = ImportModuleRT("tools", path, watch=False)
    write_source(path, source)
    module.file_binding.reload()
    fresh = ImportModuleRT("fresh", path, watch=False)
    assert set(module.operators()) == set(fresh.operators()) == {
        "sqrt", "outer", "alias", "Callable", "instance",
    }
    assert module.get_operator("alias")() == 3
    assert module.get_operator("instance")() == 4
    outer = module.get_operator("outer")
    module.set_script("def outer():\n    return 5\n")
    assert module.operators() == {"outer": outer}
    assert outer() == 5


def test_unchanged_source_does_not_emit_signals_or_invalidate_cache(tmp_path):
    source = "def value():\n    return 1\n"
    module = ImportModuleRT("tools", write_source(tmp_path / "operators.py", source), watch=False)
    value = module.get_operator("value")
    fingerprint = value.fingerprint()
    events = []
    module.script_changed.connect(lambda: events.append("script"))
    module.operators_changed.connect(events.append)
    module.file_binding.reload()
    module.set_script(source)
    assert events == []
    assert module.get_operator("value") is value
    assert value.fingerprint() == fingerprint


@pytest.mark.parametrize(
    "before, after, expected_names, expected_results",
    [
        ("return 2", "return 3", ["value"], [30]),
        ("return 99", "return 100", ["unused"], []),
        ("# comment", "# edited comment", [], []),
    ],
)
def test_reload_only_notifies_changed_functions(
    tmp_path, before, after, expected_names, expected_results
):
    source = "def value():\n    return 2\ndef unused():\n    return 99\n# comment\n"
    path = write_source(tmp_path / "operators.py", source)
    module = ImportModuleRT("tools", path, watch=False)
    graph = GraphRT()
    graph.add_modules([module])
    value = graph.node()(module.get_operator("value"))

    @graph.node(value)
    def result(number):
        return number * 10

    assert graph.execute(result) == 20
    results = []
    changes = []
    module.operators_changed.connect(changes.extend)
    watcher = watch(graph, result, lambda: results.append(graph.execute(result)))
    try:
        write_source(path, source.replace(before, after))
        module.file_binding.reload()
        assert changes == expected_names
        assert results == expected_results
        assert module.get_operator("value")() == (3 if expected_results else 2)
    finally:
        watcher.stop()


def test_removed_globals_do_not_survive_reload(tmp_path):
    source = "FLAG = 1\ndef value():\n    return globals().get('FLAG', 0)\n"
    path = write_source(tmp_path / "operators.py", source)
    module = ImportModuleRT("tools", path, watch=False)
    value = module.get_operator("value")
    assert value() == 1
    module.set_script("def value():\n    return globals().get('FLAG', 0)\n")
    assert value() == 0


def test_operator_ownership_is_module_specific(tmp_path):
    path = write_source(tmp_path / "operators.py", "from math import sqrt\n")
    first = ImportModuleRT("first", path, watch=False)
    second = ImportModuleRT("second", path, watch=False)
    sqrt = first.get_operator("sqrt")
    assert not second.isValid(sqrt)
    assert dict(second.get_parameters(sqrt)) == {}
    with pytest.raises(ValueError):
        second.call(sqrt, 4)
    with pytest.raises(ValueError):
        second.fingerprint(sqrt)


def test_buffer_edits_and_script_edits_stay_connected(tmp_path):
    path = write_source(tmp_path / "operators.py", "def value():\n    return 1\n")
    module = ImportModuleRT("tools", path, watch=False)
    events = []
    module.script_changed.connect(lambda: events.append(module.get_operator("value")()))

    module.file_binding.set_text("def value():\n    return 2\n")
    assert module.get_operator("value")() == 2
    assert module.get_script() == module.file_binding.get_text()
    module.set_script("def value():\n    return 3\n")
    assert module.get_script() == module.file_binding.get_text()
    assert events == [2, 3]
    assert path.read_text(encoding="utf-8") == "def value():\n    return 1\n"


def test_open_context_is_visible_to_observers_and_survives_runtime_edits(tmp_path):
    source = "def location():\n    return __file__\n"
    first = write_source(tmp_path / "first.py", source)
    second = write_source(tmp_path / "second.py", source)
    module = ImportModuleRT("tools", first, watch=False)
    states = []
    module.script_changed.connect(lambda: states.append((
        module.file_binding.path(), module.file_binding.get_text(),
        module.get_operator("location")(),
    )))

    module.file_binding.open(second)
    module.set_script(source + "# edited\n")

    assert states == [
        (second, source, str(second)),
        (second, source + "# edited\n", str(second)),
    ]


def test_initial_invalid_source_raises(tmp_path):
    path = write_source(tmp_path / "broken.py", "def broken(:\n")
    with pytest.raises(SyntaxError):
        ImportModuleRT("tools", path, watch=False)


def test_wrapped_runtime_updates_preserve_wrapper_ownership_and_sync_the_buffer(tmp_path):
    initial = "def value(number: int = 1):\n    return number + 1\n"
    path = write_source(tmp_path / "operators.py", initial)
    module = ImportModuleRT("tools", path, watch=False)
    operator = module.get_operator("value")
    wrapped_operator = module.script_module.get_operator("value")
    assert operator.module() is module
    assert wrapped_operator.module() is module.script_module
    assert operator is not wrapped_operator
    assert module.fingerprint(operator) == module.script_module.fingerprint(wrapped_operator)
    assert module.get_parameters(operator) == wrapped_operator.get_parameters()
    assert module.call(operator, number=5) == 6

    assert not module.isValid(wrapped_operator)
    assert dict(module.get_parameters(wrapped_operator)) == {}
    with pytest.raises(ValueError):
        module.call(wrapped_operator)
    with pytest.raises(ValueError):
        module.fingerprint(wrapped_operator)

    scripts = []
    changes = []
    module.script_changed.connect(lambda: scripts.append(module.get_script()))
    module.operators_changed.connect(changes.append)
    edited = "def value(number: int = 1):\n    return number + 2\n"
    module.script_module.set_script(edited)

    assert module.get_operator("value") is operator
    assert operator.module() is module
    assert operator(5) == 7
    assert module.file_binding.get_text() == edited
    assert scripts == [edited]
    assert changes == [["value"]]
    assert path.read_text(encoding="utf-8") == initial


def test_fixing_a_failed_open_uses_the_new_file_context(tmp_path):
    source = "def location():\n    return __file__\n"
    first = write_source(tmp_path / "first.py", source)
    second = write_source(tmp_path / "second.py", "def broken(:\n")
    module = ImportModuleRT("tools", first, watch=False)
    location = module.get_operator("location")

    module.file_binding.open(second)
    assert location() == str(first)
    module.set_script(source)

    assert module.get_operator("location") is location
    assert location() == str(second)
    assert module.file_binding.get_text() == source
