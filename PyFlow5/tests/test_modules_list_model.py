from qtpy.QtCore import QPersistentModelIndex, Qt

from pyflow5.module_operator_tree_model import ModuleOperatorTreeModel
from pyflow5.modules_list_model import ModulesListModel
from pygraphrt.local_module import LocalModuleRT
from pygraphrt.script_module import ScriptModuleRT


def test_shared_modules_and_flat_proxy(qtmodeltester):
    local = LocalModuleRT()
    script = ScriptModuleRT("tools", "def one(): return 1")
    source = ModuleOperatorTreeModel([local, script])
    proxy = ModulesListModel(source)
    qtmodeltester.check(source)
    qtmodeltester.check(proxy)
    assert proxy.rowCount() == 1
    assert proxy.rowCount(proxy.index(0, 0)) == 0
    assert proxy.index(0, 0).data(proxy.ModuleRole) is script
    assert proxy.flags(proxy.index(0, 0)) & Qt.ItemFlag.ItemIsSelectable

    added = ScriptModuleRT("added", "def two(): return 2")
    proxy.addModule(added)
    assert source.index(2, 0).data(source.ModuleRole) is added
    assert source.index(0, 0, source.index(2, 0)).data() == "two"
    persistent = QPersistentModelIndex(proxy.index(1, 0))
    source.removeModule(script)
    assert persistent.isValid()
    assert persistent.row() == 0
    proxy.removeModule(0)
    assert not persistent.isValid()
    assert source.rowCount() == 1
    source.setModules([script])
    assert proxy.rowCount() == 1
    assert proxy.index(0, 0).data(proxy.ModuleRole) is script


def test_edits_and_runtime_notifications(qtmodeltester):
    script = ScriptModuleRT("tools", "def one(): return 1")
    source = ModuleOperatorTreeModel([script])
    proxy = ModulesListModel(source)
    qtmodeltester.check(source)
    qtmodeltester.check(proxy)
    index = proxy.index(0, 0)
    assert proxy.setData(index, "renamed", proxy.NameRole)
    assert source.index(0, 0).data() == "renamed"
    assert proxy.setData(index, "def two(): return 2", proxy.CodeRole)
    assert source.index(0, 0, source.index(0, 0)).data() == "two"
    changes = []
    proxy.dataChanged.connect(lambda first, last, roles: changes.append(roles))
    script.set_script("# no operators")
    assert source.rowCount(source.index(0, 0)) == 0
    assert index.data(proxy.CodeRole) == "# no operators"
    assert [proxy.CodeRole] in changes
    child = source.index(0, 0, source.index(0, 0))
    assert not source.setData(child, "ignored", source.CodeRole)


def test_document_additions_use_shared_source(qapp):
    from pyflow5.pyflow5_document import PyFlowDocument

    document = PyFlowDocument()
    source = document.operatormodel()
    proxy = document.modulesmodel()
    assert proxy.sourceModel() is source
    document.addNewScriptModule("new_script")
    index = proxy.index(proxy.rowCount() - 1, 0)
    assert proxy.setData(index, "def added(): return 1", proxy.CodeRole)
    parent = source.index(source.rowCount() - 1, 0)
    assert source.index(0, 0, parent).data() == "added"
    assert "new_script" in [module["name"] for module in document.todict()["modules"].values()]
