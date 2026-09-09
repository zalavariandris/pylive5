from textwrap import dedent
import pytest
from pygraphrt.imports_rt import (
    ImportRT, 
    imports_from_script, 
    imports_to_script
)

class Test_Script2ImportsRT:
    def test_simple_imports(self):
        simple_imports = dedent("""\
        import functools
        import os.path
        """)

        actuel_imports = imports_from_script(simple_imports)
        expected_imports = [
            ImportRT(module="functools"),
            ImportRT(module="os.path")
        ]
        assert actuel_imports == expected_imports

    def test_multi_object_imports(self):
        script = dedent("""\
        from pathlib import (
            Path,
            PurePath as Pure
        )
        """)

        actual_imports = imports_from_script(script)
        expected_imports = [
            ImportRT(module="pathlib", name="Path"),
            ImportRT(module="pathlib", name="PurePath", alias="Pure"),
        ]

        assert actual_imports == expected_imports

    def test_simple_alias_imports(self):
        alias_imports = dedent("""\
        import os as operating_system
        import numpy as np
        import os.path as path
        import os, sys as system
        """)

        actual_imports = imports_from_script(alias_imports)
        expected_imports = [
            ImportRT(module="os", alias="operating_system"),
            ImportRT(module="numpy", alias="np"),
            ImportRT(module="os.path", alias="path"),
            ImportRT(module="os"),
            ImportRT(module="sys", alias="system"),
        ]

        assert actual_imports == expected_imports

    def test_submodule_imports(self):
        submodule_imports = dedent("""\
        from pathlib import Path
        from pathlib import Path as FilePath
        from os.path import join, dirname as parent
        from pathlib import (
            Path,
            PurePath as Pure
        )
        """)

        actual_imports = imports_from_script(submodule_imports)
        expected_imports = [
            ImportRT(module="pathlib", name="Path"),
            ImportRT(module="pathlib", name="Path", alias="FilePath"),
            ImportRT(module="os.path", name="join"),
            ImportRT(module="os.path", name="dirname", alias="parent"),
            ImportRT(module="pathlib", name="Path"),
            ImportRT(module="pathlib", name="PurePath", alias="Pure")
        ]

        assert actual_imports == expected_imports
        actual_script = imports_to_script(actual_imports)
        assert actual_script == submodule_imports.strip()

    @pytest.mark.xfail("Group imports are not yet supported")
    def test_group_imports(self):
        group_imports = dedent("""\
        from pathlib import (
            Path,
            PurePath as Pure
        )
        """)

        actual_imports = imports_from_script(group_imports)
        expected_imports = [
            ImportRT(module="pathlib", name="Path"),
            ImportRT(module="pathlib", name="PurePath", alias="Pure"),
        ]

        assert actual_imports == expected_imports

    def test_star_imports(self):
        star_imports = dedent("""\
        from math import *
        """)

        actual_imports = imports_from_script(star_imports)
        expected_imports = [
            ImportRT(module="math", name="*"),
        ]

        assert actual_imports == expected_imports

    def test_simple_alias_imports(self):
        alias_imports = dedent("""\
        import os as operating_system
        import numpy as np
        import os.path as path
        import os, sys as system
        """)

        actual_imports = imports_from_script(alias_imports)
        expected_imports = [
            ImportRT("os", alias="operating_system"),
            ImportRT("numpy", alias="np"),
            ImportRT("os.path", alias="path"),
            ImportRT("os"),
            ImportRT("sys", alias="system"),
        ]

        assert actual_imports == expected_imports

    def test_relative_imports(self):
        relative_imports = dedent("""\
        from . import sibling
        from .sibling import value as local_value
        from .. import parent
        from ...package.module import value
        """)

        actual_imports = imports_from_script(relative_imports)
        expected_imports = [
            ImportRT(module=".", name="sibling"),
            ImportRT(module=".sibling", name="value", alias="local_value"),
            ImportRT(module="..", name="parent"),
            ImportRT(module="...package.module", name="value"),
        ]

        assert actual_imports == expected_imports   
    
class Test_ScriptFromImportsRT:
    def test_example(self):
        imports = [
            ImportRT(module="os"),
            ImportRT(module="sys", alias="system"),
        ]

        actual_script = imports_to_script(imports)

        expected_script = dedent("""\
        import os
        import sys as system
        """).strip()
        assert actual_script == expected_script

# @pytest.skip(reason="Skipping test for imports_to_script")
# def test_imports_to_script(script):
#     ...

# @pytest.skip(reason="Skipping test for imports_to_script")
# def test_imports_from_script_extracts_only_top_level_imports_without_execution():
#     script = dedent("""
#         import nonexistent_dependency as dep
#         from ..helpers import first, second as other
#         def function():
#             import local_dependency
#         if False:
#             import conditional_dependency
#         raise RuntimeError("Do not execute")
#     """)
#     imports = imports_from_script(script)
#     assert [(m._module, m._name, m._alias) for m in imports] == [
#         ("nonexistent_dependency", None, "dep"),
#         ("..helpers", "first", None),
#         ("..helpers", "second", "other"),
#     ]


# @pytest.skip(reason="Skipping test for imports_from_script without imports")
# def test_imports_from_script_without_imports(script):
#     assert imports_from_script(script) == []

# @pytest.skip(reason="Skipping test for imports_from_script with invalid syntax")
# def test_imports_from_script_rejects_invalid_syntax():
#     with pytest.raises(SyntaxError):
#         imports_from_script("from os import")


if __name__ == "__main__":
    pytest.main([__file__, "-vv"])
