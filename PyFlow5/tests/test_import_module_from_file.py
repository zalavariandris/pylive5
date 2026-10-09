# This is a functionality test.
# we wanna make sure, when importing a module from a file, functions defined in that file can be used as operators.
from pathlib import Path
import pytest
from qtpy.QtCore import QPointF, Qt
from pytestqt.qtbot import QtBot

from pyflow5.pyflow5_document import PyFlowDocument
import pygraphrt as rt

from textwrap import dedent
def test_import_module_from_file(tmp_path):
    module_file = tmp_path / "module_v01.py"
    module_file.write_text(
        dedent(
            """\
            def is_this():
                return 'is_this?'

            def buum():
                return 'Boooooom'
            """
        )
    )
    document = PyFlowDocument()
    document.importModule(module_file)
    assert document.modules_model.rowCount()>0
    module_index = document.modules_model.index(0,0)
    assert module_index.isValid()
    assert module_index.data(Qt.ItemDataRole.DisplayRole).endswith("module_v01.py")

    # get the operators from the imported module
    assert document.modules_model.rowCount(module_index) ==2
    # oparator names match the functions defined in the module
    operator_names = [document.modules_model.index(row, 0, module_index).data(Qt.ItemDataRole.DisplayRole)
                      for row in range(document.modules_model.rowCount(module_index))]
    assert "is_this" in operator_names
    assert "buum" in operator_names

def test_import_vfxops():
    module_file = Path("vfxops/src/vfxops/vfxops.py")
    assert module_file.exists()

    document = PyFlowDocument()
    document.importModule(module_file)
    assert document.modules_model.rowCount()>0
    module_index = document.modules_model.index(0,0)
    assert module_index.isValid()
    assert module_index.data(Qt.ItemDataRole.DisplayRole).endswith("vfxops.py")

    # get the operators from the imported module
    assert document.modules_model.rowCount(module_index) > 0
    # oparator names match the functions defined in the module
    operator_names = [document.modules_model.index(row, 0, module_index).data(Qt.ItemDataRole.DisplayRole)
                      for row in range(document.modules_model.rowCount(module_index))]
    assert "is_this" in operator_names
    assert "buum" in operator_names


if __name__ == "__main__":
    pytest.main([__file__])
