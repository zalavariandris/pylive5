from pygraphrt.operator_rt import ParameterRT
import pytest
from textwrap import dedent
from pygraphrt.script_module_rt import ScriptModuleRT
from pygraphrt.graph_rt import GraphRT

def test_script_module_rt_initialization():
    sm = ScriptModuleRT("mathy", dedent("""\
    def one():
        return 1

    def pow(x):
        return x ** 2

    def mult(a, b):
        return a * b
    """))
    assert sm is not None

    assert sm.operators().keys() == {"one", "pow", "mult"}

    mult_op = sm.operators()['mult']
    assert list(mult_op.get_parameters().values()) == [ParameterRT("a"), ParameterRT("b")]

    G = GraphRT()
    G.add_modules([sm])
    assert sm in G.modules()

def test_updating_script():
    sm = ScriptModuleRT("mathy", dedent("""\
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

    assert set(sm.operators().keys()) == {"two", "pow", "mult"}

from qtpy.QtTest import QSignalSpy
def test_updating_script_signals():
    sm = ScriptModuleRT("mathy", dedent("""\
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

    assert added == ["two"]
    assert removed == ["one"]
    assert changed == ["pow"]

if __name__ == "__main__":
    pytest.main([__file__])