# REVIEW ERROR CONTRACT: builtin SyntaxError/AttributeError/TypeError assertions
# predate the current ScriptSyntaxError/ScriptEvaluationError wrappers. Keep
# invalid-source storage, operator removal, notification, and recovery coverage.
# set_script() also reads error.error, absent on ScriptEvaluationError: that is
# an implementation inconsistency, not a reason to remove recovery tests.
import pytest

import pygraphrt.script_module as script_module
from pygraphrt.abstract_module_rt import OperatorRef
from textwrap import dedent
from pygraphrt.script_module import ScriptModuleRT
from pygraphrt.import_module import ImportModuleRT
from pygraphrt.abstract_module_rt import ParameterData

# REVIEW UNNECESSARY / MERGE: repeats export discovery and parameter details
# in test_importmodule.test_initialization, which already covers both classes.
def test_initialization():
    sm = ScriptModuleRT("mathy")
    sm.set_script(dedent("""\
    def one():
        return 1

    def pow(x):
        return x ** 2

    def mult(a, b):
        return a * b
    """))
    assert sm is not None

    assert set(op.name for op in sm.operators()) == {"one", "pow", "mult"}

    mult_op = next(op for op in sm.operators() if op.name == 'mult')
    actual_parameters = list(mult_op.get_parameters().values())
    expected_parameters = [
        ParameterData("a"), 
        ParameterData("b")
    ]
    assert actual_parameters == expected_parameters


def test_changing_all_updates_exports_and_signals():
    source = "def public(): return 1\ndef _private(): return 2\n"
    module = ScriptModuleRT("tools")
    module.set_script(source)
    added, removed = [], []
    module.operators_added.connect(added.append)
    module.operators_removed.connect(removed.append)

    module.set_script(source + "__all__ = ['_private']")
    assert [ref.name for ref in module.operators()] == ["_private"]
    assert added == [[OperatorRef(module, "_private")]]
    assert removed == [[OperatorRef(module, "public")]]
    assert OperatorRef(module, "_private").get_value()() == 2

    added.clear()
    removed.clear()
    module.set_script(source)
    assert [ref.name for ref in module.operators()] == ["public"]
    assert added == [[OperatorRef(module, "public")]]
    assert removed == [[OperatorRef(module, "_private")]]


# REVIEW SIMPLIFY: keep missing/invalid exports and operator removal. The
# exhaustive container/subclass exclusions fix a narrow __all__ type policy
# before it is needed; exception classes also need the error-contract review.
@pytest.mark.parametrize("exports, error_type", [
    ("['missing']", AttributeError),
    ("['public', 'missing']", AttributeError),
    ("[1]", TypeError),
    ("None", TypeError),
    ("'public'", TypeError),
    ("{'public'}", TypeError),
    ("{'public': 1}", TypeError),
    ("iter(['public'])", TypeError),
    ("type('Names', (list,), {})(['public'])", TypeError),
    ("[type('Name', (str,), {})('public')]", TypeError),
])
def test_invalid_all_records_failure_and_removes_operators(
    exports: str, error_type: type[Exception]
) -> None:
    source = "def public(): return 1\n"
    invalid_source = source + f"__all__ = {exports}"
    initial = ScriptModuleRT("tools")
    initial.set_script(invalid_source)
    assert isinstance(initial.get_state(), error_type)
    assert list(initial.operators()) == []

    module = ScriptModuleRT("tools")
    module.set_script(source)
    removed = []
    module.operators_removed.connect(removed.append)
    module.set_script(invalid_source)
    assert isinstance(module.get_state(), error_type)
    assert list(module.operators()) == []
    assert removed == [[OperatorRef(module, "public")]]


@pytest.mark.parametrize("exports", ["['_private']", "('_private',)", "[]", "()"])
def test_explicit_exports_allow_private_names_and_empty_containers(exports: str) -> None:
    module = ScriptModuleRT()
    module.set_script("def _private(): return 1\n" + f"__all__ = {exports}")
    assert module.get_state() == "VALID"
    expected = ["_private"] if "_private" in exports else []
    assert [ref.name for ref in module.operators()] == expected


# REVIEW UNNECESSARY / DEFER: module-level dynamic __getattr__ is a specialized
# discovery policy beyond ordinary exports. Revisit if dynamic exports become
# supported; the "dynamic" case also expects an obsolete AttributeError.
@pytest.mark.parametrize("exports", ["", "__all__ = ['op']", "__all__ = ['dynamic']"])
def test_export_discovery_does_not_call_module_getattr(exports: str) -> None:
    module = ScriptModuleRT()
    module.set_script(dedent("""\
        def op(): return 1
        def __getattr__(name):
            raise RuntimeError('Export discovery must not call this')
    """) + exports)
    if "dynamic" in exports:
        assert isinstance(module.get_state(), AttributeError)
        assert "dynamic" in str(module.get_state())
        assert list(module.operators()) == []
    else:
        assert module.get_state() == "VALID"
        assert [ref.name for ref in module.operators()] == ["op"]


# REVIEW SIMPLIFY: discovering locally defined functions is useful, but blanket
# rejection of callable objects/builtins freezes a current limitation; callable
# object support is already a TODO. Defer the hostile __getattribute__ edge case.
@pytest.mark.parametrize("explicit", [False, True])
def test_only_python_functions_become_operators(explicit: bool) -> None:
    source = dedent("""\
        from textwrap import dedent
        class CallableObject:
            def __getattribute__(self, name):
                raise RuntimeError('Do not inspect callable objects')
            def __call__(self): return 0
        instance = CallableObject()
        constant = 42
        builtin = len
        def op(): return 1
    """)
    if explicit:
        source += "__all__ = ['CallableObject', 'instance', 'constant', 'builtin', 'dedent', 'op']"
    module = ScriptModuleRT()
    module.set_script(source)
    assert module.get_state() == "VALID"
    assert [ref.name for ref in module.operators()] == ["op"]
    assert OperatorRef(module, "op")() == 1


# REVIEW UNNECESSARY / DEFER: exercises a private helper's defined_only=False
# mode, which ScriptModuleRT.set_script() never uses. Integrate when there is
# a public imported-function export workflow to protect.
def test_imported_python_functions_can_be_included_explicitly() -> None:
    functions = script_module._get_all_callables_from_script(
        "from textwrap import dedent\n__all__ = ['dedent']",
        name="tools", defined_only=False,
    )
    assert functions == {"dedent": dedent}




# REVIEW UNNECESSARY / MERGE: repeats the same edit as test_updating_script_signals;
# move its final export-set assertion there when consolidating.
def test_updating_script():
    sm = ScriptModuleRT("mathy")
    sm.set_script(dedent("""\
    def one():
        return 1

    def pow(x):
        return x ** 2

    def mult(a, b):
        return a * b
    """))

    # Update the script
    sm.set_script(dedent("""\
        def two():
            return 2

        def pow(x, y):
            return x ** y

        def mult(a, b):
            return a * b
        """))

    assert set([op.name for op in sm.operators()]) == {"two", "pow", "mult"}

# REVIEW UNNECESSARY / MERGE: two invalid scripts are only compared for equal
# operator lists, so both could be wrong. Keep the explicit removed-operator
# and recovery assertions in the later error tests instead.
def test_updating_script_with_syntaxerror():
    """Script module should be deterministic.
    therefore a script with a syntax error should return the 
    same operators as a newly initialized script with syntax errors."""
    source_without_syntaxerror = dedent("""\
        def one():
            return 1

        def pow(x):
            return x ** 2

        def mult(a, b):
            return a * b
        """)
    source_with_syntaxerror = dedent("""\
        def one():
            return 1

        def pow(x):
            return x ** 2

        def mult(a, 
            return a * b
        """)
    
    sm = ScriptModuleRT("mathy")
    sm.set_script(source_without_syntaxerror)
    sm.set_script(source_with_syntaxerror)

    expected_sm = ScriptModuleRT("mathy")
    expected_sm.set_script(source_with_syntaxerror)
    expected_operators = expected_sm.operators()
    
    assert sm.operators() == expected_operators


from qtpy.QtTest import QSignalSpy
def test_updating_script_signals():
    sm = ScriptModuleRT("mathy")
    sm.set_script(dedent("""\
    def one():
        return 1

    def pow(x):
        return x ** 2

    def mult(a, b):
        return a * b
    """))

    removed = []
    added = []
    changed = []

    def on_removed(names):
        nonlocal removed
        removed = names

    def on_added(names):
        nonlocal added
        added = names

    def on_changed(names):
        nonlocal changed
        changed = names

    sm.operators_removed.connect(on_removed)
    sm.operators_added.connect(on_added)
    sm.operators_changed.connect(on_changed)

    sm.set_script(dedent("""\
        def two():
            return 2

        def pow(x, y):
            return x ** y

        def mult(a, b):
            return a * b
        """))

    assert added == [OperatorRef(sm, "two")]
    assert removed == [OperatorRef(sm, "one")]
    assert changed == [OperatorRef(sm, "pow")]




@pytest.mark.parametrize("source, expected_state", [
    ("", "VALID"),
    ("value = 1", "VALID"),
    ("def one(): return 1", "VALID")
])
def test_initial_module_state(source, expected_state):
    module = ScriptModuleRT("tools")
    module.set_script(source)
    assert module.get_state() == expected_state, f"Expected state {expected_state}, but got {module.get_state()}"

# REVIEW UNNECESSARY / REMOVE: the syntax-diagnostic test above already sets
# invalid source on a fresh module and checks the same error-state expectation.
def test_initial_module_state_with_error():
    module = ScriptModuleRT("tools")
    module.set_script("broken(:")
    assert isinstance(module.get_state(), SyntaxError)

from collections import Counter
# REVIEW SIMPLIFY: keep valid/error/recovery transitions. Repeated valid edits
# and exact counts for successive error objects prescribe a notification policy.
# Despite its name, this test reads state after the call, not inside the observer;
# observer-visible committed state is covered by the later observer test.
def test_state_changed_reports_committed_state_only_on_transitions():
    valid_source = "def one(): return 1"
    module = ScriptModuleRT("tools")
    module.set_script(valid_source)
    assert module.get_state() == "VALID"

    counter = 0
    def increment_counter():
        nonlocal counter
        counter += 1
    module.state_changed.connect(increment_counter)

    module.set_script(valid_source + "\n# valid edit")
    assert module.get_state() == "VALID"
    assert counter == 0, f"valid to valid transition should not trigger state_changed"

    module.set_script(valid_source + "\n# another valid edit")
    assert module.get_state() == "VALID"
    assert counter == 0, f"valid to valid transition should not trigger state_changed"

    module.set_script("def broken(:")
    assert isinstance(module.get_state(), SyntaxError)
    assert counter == 1, f"valid to invalid transition should trigger state_changed"

    module.set_script("def broken(hello")
    assert isinstance(module.get_state(), SyntaxError)
    assert counter == 2, f"erros message of state has changed, therefor a state change should have been triggered"

    module.set_script(valid_source)
    assert module.get_state() == "VALID"
    assert counter == 3, f"Expected counter to be 2, but got {counter}"


@pytest.mark.parametrize("invalid_script", ["def broken(:", "raise RuntimeError('broken')"])
def test_failed_script_emits_removed_operator_refs(invalid_script):
    module = ScriptModuleRT("tools")
    module.set_script("def one(): return 1")
    removed = []
    module.operators_removed.connect(removed.append)
    module.set_script(invalid_script)
    assert removed == [[OperatorRef(module, "one")]]
    assert removed[0][0].get_value() is None

@pytest.mark.parametrize("module_class", [ScriptModuleRT, ImportModuleRT])
@pytest.mark.parametrize("source, error_type", [
    ("def broken(:", SyntaxError),
    ("raise RuntimeError('broken')", RuntimeError),
    ("__all__ = ['missing']", AttributeError),
    ("__all__ = None", TypeError),
])
# REVIEW SIMPLIFY: retain committed state visible to every observer and recovery;
# exact state/removed/script signal order unnecessarily constrains implementation.
# Specific error classes need review, not deletion of this live-editing scenario.
def test_script_errors_notify_observers_after_committing(
    module_class: type[ScriptModuleRT], source: str, error_type: type[Exception]
) -> None:
    module = module_class()
    module.set_script("def one(): return 1")
    observed: list[tuple[str, str, object, list[OperatorRef]]] = []

    def record(signal: str) -> None:
        observed.append((signal, module.get_script(), module.get_state(), list(module.operators())))

    module.state_changed.connect(lambda: record("state"))
    module.operators_removed.connect(lambda _: record("removed"))
    module.script_changed.connect(lambda: record("script"))
    module.set_script(source)

    error = module.get_state()
    assert isinstance(error, error_type)
    assert observed == [(signal, source, error, []) for signal in ("state", "removed", "script")]

    module.set_script("def recovered(): return 2")
    assert module.get_state() == "VALID"
    assert OperatorRef(module, "recovered")() == 2


# REVIEW UNNECESSARY / DEFER: monkeypatches four internal components and demands
# transaction-like rollback for arbitrary implementation bugs. This couples the
# suite to the architecture; retain public script-error/recovery tests instead.
@pytest.mark.parametrize("component", [
    "ModuleType", "_get_all_callables_from_script", "ast_functions_diff", "FunctionOperator",
])
def test_runtime_bugs_propagate_without_committing(
    monkeypatch: pytest.MonkeyPatch, component: str
) -> None:
    module = ScriptModuleRT()
    source = "def one(): return 1\ndef two(): return 2"
    module.set_script(source)
    operators = {ref.name: ref.get_value() for ref in module.operators()}
    notifications: list[str] = []
    module.state_changed.connect(lambda: notifications.append("state"))
    module.script_changed.connect(lambda: notifications.append("script"))
    module.operators_added.connect(lambda _: notifications.append("added"))
    module.operators_removed.connect(lambda _: notifications.append("removed"))
    module.operators_changed.connect(lambda _: notifications.append("changed"))
    bug = RuntimeError("runtime implementation bug")

    def fail(*args: object, **kwargs: object) -> None:
        raise bug

    monkeypatch.setattr(script_module, component, fail)
    with pytest.raises(RuntimeError) as caught:
        module.set_script("def two(): return 3")

    assert caught.value is bug
    assert module.get_script() == source
    assert module.get_state() == "VALID"
    assert {ref.name: ref.get_value() for ref in module.operators()} == operators
    assert notifications == []


# REVIEW SIMPLIFY: propagating interrupts is useful; complete rollback of all
# module state on process-control exceptions need not be a development contract.
@pytest.mark.parametrize("exception_name", ["KeyboardInterrupt", "SystemExit"])
def test_script_interrupts_propagate_without_committing(exception_name: str) -> None:
    module = ScriptModuleRT()
    source = "def one(): return 1"
    module.set_script(source)
    exception_type = KeyboardInterrupt if exception_name == "KeyboardInterrupt" else SystemExit

    with pytest.raises(exception_type):
        module.set_script(f"raise {exception_name}()")

    assert module.get_script() == source
    assert module.get_state() == "VALID"
    assert OperatorRef(module, "one")() == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
