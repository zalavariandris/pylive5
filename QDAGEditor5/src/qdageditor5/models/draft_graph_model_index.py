from typing import Any

from qtpy.QtCore import Qt
import weakref

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from qdageditor5.models.abstract_dag_model import NodeName

class GraphModelIndex:
    def __init__(self, model, name: NodeName):
        super().__init__()
        self._model:weakref.ref = weakref.ref(model)
        self._name:NodeName = name

    def isValid(self):
        model = self._model()
        return model is not None\
            and self._name is not None\
            and self._name in model.nodes()

    def flags(self):
        model = self._model()
        if model is None:
            return Qt.ItemFlag.NoItemFlags
        
        return model.flags(self._name)

    def model(self):
        return self._model()

    def name(self):
        return self._name

    def nodeData(self, role:Qt.ItemDataRole=Qt.ItemDataRole.DisplayRole)->Any:
        model = self._model()
        if model is None:
            return None
        
        return model.nodeData(self._name, role)

    def __hash__(self)->int:
        return hash((self._model(), self._name))

    def __eq__(self, other)->bool:
        if not isinstance(other, GraphModelIndex):
            return False
        return self._model() == other._model() and self._name == other._name
    