import pytest
from qtpy.QtCore import QCoreApplication, QEvent, QThread
from qtpy.QtTest import QTest

from pygraphrt.graph_rt import GraphRT
from pygraphrt.script_module_rt import ScriptModuleRT
from pygraphrt.import_module_rt import ImportModuleRT
from pygraphrt.watch import watch

from pygraphrt.graph_rt_serialize import _to_dict

def test_script_module_serialization():
    from textwrap import dedent
    source = dedent("""\
    def value():
        return 1
    """)
    script_module = ScriptModuleRT("tools", source)
    serialized = _to_dict(script_module)
    assert serialized == {"source": "def value():\n    return 1\n"}

def test_import_module_serialization():
    import_module = ImportModuleRT("tools", "tools.py")
    serialized = _to_dict(import_module)

    serialized = _to_dict(import_module)
    assert serialized == {"file": "tools.py"}

if __name__ == "__main__":
    pytest.main([__file__, "-v"])