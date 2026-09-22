from qtpy.QtCore import QModelIndex, QPersistentModelIndex
from qtpy.QtWidgets import QDialog, QDialogButtonBox

from pyflow5.module_operator_tree_model import ModuleOperatorTreeModel
from myqtx.selection_dialog import SelectionDialog
from pygraphrt.abstract_module_rt import OperatorRef
from pygraphrt.local_module import LocalModuleRT, FunctionOperator
from pygraphrt.script_module import ScriptModuleRT


def test_tree_structure_and_local_updates(qtmodeltester):
    local = LocalModuleRT()
    script = ScriptModuleRT("tools", "def one(): return 1")
    model = ModuleOperatorTreeModel([local, script])
    qtmodeltester.check(model)
    parent = model.index(0, 0)
    assert model.rowCount() == 2
    assert model.data(model.index(1, 0)) == "tools"
    assert not model.index(0, 1).isValid()
    assert model.data(QModelIndex()) is None
    inserted = []
    changed = []
    model.rowsInserted.connect(lambda *args: inserted.append(args))
    model.dataChanged.connect(lambda *args: changed.append(args))

    @local.op()
    def one():
        return 1

    child = model.index(0, 0, parent)
    assert model.parent(child) == parent
    assert model.rowCount(child) == 0
    assert child.data(model.OperatorRole) == one
    assert child.data(model.ModuleRole) is local
    assert model.index(0, 0, model.index(1, 0)).data(model.OperatorRole) != one
    assert len(inserted) == 1
    persistent = QPersistentModelIndex(child)
    changed.clear()
    local.update_operator(one, FunctionOperator(lambda: 2))
    assert changed
    assert persistent.data(model.OperatorRole).get_value()() == 2
    local.remove_operator(one)
    assert not persistent.isValid()
    assert model.rowCount(parent) == 0


def test_script_updates_and_module_detachment(qtmodeltester):
    module = ScriptModuleRT("tools", "def one(): return 1")
    model = ModuleOperatorTreeModel([module])
    qtmodeltester.check(model)
    parent = model.index(0, 0)
    persistent = QPersistentModelIndex(model.index(0, 0, parent))
    module.set_script("def one(): return 2\ndef two(): return 2")
    assert persistent.isValid()
    assert persistent.data(model.OperatorRole).get_value()() == 2
    assert model.rowCount(parent) == 2
    module.set_script("def two(): return 3")
    assert not persistent.isValid()
    assert model.index(0, 0, parent).data() == "two"
    module.set_script("def broken(:")
    assert model.rowCount(parent) == 0
    module.set_script("def recovered(): return 4")
    assert model.index(0, 0, parent).data() == "recovered"
    model.removeModule(module)
    module.set_script("def ignored(): return 5")
    assert model.rowCount() == 0
    model.addModule(module)
    model.addModule(module)
    assert model.rowCount() == 1
    model.setModules([])
    module.set_script("")
    assert model.rowCount() == 0


def test_picker_requires_an_operator_and_handles_removal(qtbot):
    module = ScriptModuleRT("tools", "def one(): return 1")
    model = ModuleOperatorTreeModel([module])
    dialog = SelectionDialog(model)
    qtbot.addWidget(dialog)
    dialog._operator_tree.setCurrentIndex(model.index(0, 0))
    dialog.accept()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert not dialog._buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
    dialog._operator_tree.setCurrentIndex(model.index(0, 0, model.index(0, 0)))
    module.set_script("")
    assert not dialog._buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()


def test_window_picker_creates_node_from_reference(qtbot, monkeypatch):
    from qtpy.QtCore import QPointF
    from pyflow5.pyflow5_window import PyFlow5Window
    window = PyFlow5Window()
    qtbot.addWidget(window)
    selected = []

    def choose(dialog):
        selected.append(dialog.selected_operator())
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(SelectionDialog, "exec", choose)
    window.openOperatorDialog(scene_pos=QPointF(12, 34))
    node = window._G.nodes()[0]
    assert node.get_operator() == selected[0]
    assert window._graph_model.nodePosition(node.get_name()) == QPointF(12, 34)
