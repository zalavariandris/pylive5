from pyflow5.base_details_view import BaseDetailsView
from pyflow5.pygraphrt_graphmodel import PyGraphRTGraphModel
import myqtx


class Viewer(BaseDetailsView):
    def __init__(self, parent=None)->None:
        super().__init__(parent)
        self.setBodyWidget(myqtx.DisplayWidget())
        
    def showCurrentRootEvent(self):
        print(f"Viewer->_update_display {{current_nodename={self._current_root}}}")
        if self._current_root.isValid() is False:
            self._viewer_lock_switch.setText("-no node selected-")
            self._body_widget.clear()
            return
        
        if self._model is None: 
            self._viewer_lock_switch.setText("! no model !")
            self._body_widget.clear()
            return

        result = self._model.data(self._current_root, PyGraphRTGraphModel.ExecutionRole)
        
        self._body_widget.display(result)
