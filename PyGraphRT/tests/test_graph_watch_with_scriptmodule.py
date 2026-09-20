# import pytest
# import pygraphrt as rt
# from textwrap import dedent


# @pytest.mark.parametrize(
#     "a_value, b_value, unused_value, expected_changes",
#     [(10, 2, 0, 1), (10, 20, 0, 1), (1, 2, 10, 0)],
#     ids=["one-function", "multiple-functions", "unrelated-function"],
# )
# def test_script_module_function_changed(a_value, b_value, unused_value, expected_changes):
#     from pygraphrt.script_module_rt import ScriptModuleRT
#     sm = ScriptModuleRT("mathy", dedent("""
#     def A():
#         return 1

#     def B():
#         return 2

#     def add(a, b):
#         return a + b

#     def unused():
#         return 0
#     """))

#     G = rt.GraphRT()
#     G.add_modules([sm])

#     A=G.node()(sm.operators()['A'])
#     B=G.node()(sm.operators()['B'])
#     out = G.node(A, B)(sm.operators()['add'])

#     track_changes = []

#     def callback():
#         track_changes.append("changed")

#     watcher = rt.watch(G, out, callback)

#     assert G.execute(out) == 3

#     sm.set_script(dedent(f"""
#     def A():
#         return {a_value}

#     def B():
#         return {b_value}

#     def add(a, b):
#         return a + b

#     def unused():
#         return {unused_value}
#     """))

#     assert len(track_changes) == expected_changes
#     assert G.execute(out) == a_value + b_value

#     watcher.stop()