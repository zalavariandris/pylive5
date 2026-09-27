from textwrap import dedent

import pytest
from pygraphrt.graph_state_rt import GraphStateRT
from pygraphrt.script_module import ScriptModuleRT
from pygraphrt.watch import Watcher

def test_watch_triggers_when_scriptmodule_update():
    # setup
    sm = ScriptModuleRT()
    sm.set_script(dedent("""
    def foo() -> int:
        return 42
    """))
    sm._evaluate()
    op  =sm.get_operator_by_name("foo")

    G = GraphStateRT()
    node = G._create_node(op)

    counter = 0
    def tracker():
        nonlocal counter
        counter += 1
        print(f"Tracked event: {counter}")
    w = Watcher(G, node, tracker)

    # act
    sm.set_script(dedent("""
    def foo(val) -> int:
        return val
    """))
    sm._evaluate()

    # assert
    assert counter == 1
    