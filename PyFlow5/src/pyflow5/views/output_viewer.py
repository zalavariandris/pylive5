from .base_details_view import BaseDetailsView
from ..models.pygraphrt_graphmodel import PyGraphRTGraphModel
from qtpy.QtCore import Qt, QModelIndex
from qtpy.QtWidgets import QWidget
import myqtx


class OutputViewer(BaseDetailsView):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setBodyWidget(myqtx.widgets.DisplayWidget(channel_axis=-1))
        
    def showCurrentRootEvent(self, index: QModelIndex, roles: list[int] = []):
        relevant_roles = (
            Qt.ItemDataRole.DisplayRole,
            PyGraphRTGraphModel.ErrorRole,
            Qt.ItemDataRole.EditRole,
            PyGraphRTGraphModel.OutputRole,
        )
        if roles and not any(role in relevant_roles for role in roles):
            return

        if index.isValid() is False:
            self._lock_switch.setText("-no node selected-")
            self._body_widget.clear()
            return
        
        if self._model is None: 
            self._lock_switch.setText("! no model !")
            self._body_widget.clear()
            return

        label_index = index.siblingAtColumn(0)
        self._lock_switch.setText(str(label_index.data(Qt.ItemDataRole.DisplayRole)))
        if not label_index.parent().isValid():
            result = label_index.data(PyGraphRTGraphModel.ErrorRole)
            if result is None:
                result = label_index.data(PyGraphRTGraphModel.OutputRole)
        else:
            value_index = label_index.siblingAtColumn(1)
            # EditRole preserves the inlet's Python value.
            result = value_index.data(Qt.ItemDataRole.EditRole)
            if result is None:
                result = value_index.data(Qt.ItemDataRole.DisplayRole)
        try:
            self._body_widget.display(result)
        except Exception as e:
            import traceback
            error_traceback = traceback.format_exc()
            self._body_widget.display(f"{e}\n{error_traceback}")
