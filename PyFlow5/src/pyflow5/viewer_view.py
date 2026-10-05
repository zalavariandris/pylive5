from enum import StrEnum



from pyflow5.details_view import DetailsView
from pyflow5.pygraphrt_graphmodel import PyGraphRTGraphModel
from pygraphrt.graph_executor import ExecutionFailure, ExecutionSuccess
from qdageditor5.adapters.nodes_list_model_adapter import NodesListModelAdapter
from qdageditor5.adapters.nodes_list_selection_model_adapter import NodesListSelectionModelAdapter
from qdageditor5.models.graph_selection_model import GraphSelectionModel
from qtpy.QtCore import (
    QAbstractItemModel,
    QItemSelection,
    QItemSelectionModel,
    QModelIndex,
    Qt,
    Signal,
    Slot
)

from qtpy.QtWidgets import (
    QCheckBox,
    QLabel,
    QHBoxLayout,
    QVBoxLayout, 
    QWidget
)


import myqtx
import pygraphrt as rt


class Viewer(DetailsView):
    class SelectionBehaviour(StrEnum):
        FirstSelected = "first"
        LastSelected = "last"
        Current = "current"

    def __init__(self, parent=None)->None:
        super().__init__(parent)
        self.setBodyWidget(myqtx.DisplayWidget())
        
    def showCurrentEvent(self):
        print(f"Viewer->_update_display {{current_nodename={self._current_index}}}")
        if self._current_index.isValid() is False:
            self._viewer_lock_switch.setText("-no node selected-")
            self._body_widget.clear()
            return
        
        if self._model is None: 
            self._viewer_lock_switch.setText("! no model !")
            self._body_widget.clear()
            return

        result = self._model.data(self._current_index, PyGraphRTGraphModel.ExecutionRole)
        
        self._body_widget.display(result)

