from qtpy.QtWidgets import QDialog, QWidget, QVBoxLayout, QPushButton, QLineEdit, QLabel
from qtpy.QtCore import QStringListModel

from myqtx.qpathedit import QPathEdit
from myqtx.selection_dialog import SelectionDialog
from myqtx.qfloatslider import QFloatSlider
from myqtx.color_editor_widget import ColorEdit
from myqtx.colorwheel import ColorWheel


class WidgetLibrary(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Widget Library")
        self.setMinimumSize(400, 300)

        self._layout = QVBoxLayout(self)
        self.setLayout(self._layout)


        self._layout.addWidget(QPathEdit())
        self._layout.addWidget(QFloatSlider())
        self._layout.addWidget(ColorEdit())
        self._layout.addWidget(ColorWheel())

        open_btn = QPushButton("Open Selection Dialog")
        @open_btn.clicked.connect
        def open_dialog():
            example_list_model = QStringListModel(["Item 1", "Item 2", "Item 3"])
            dialog = SelectionDialog(example_list_model, self)
            try:
                if dialog.exec() == QDialog.DialogCode.Accepted:
                    selected_index = dialog.selected_index()
                    open_btn.setText(f"Selected: {selected_index.data()}")
            finally:
                dialog.deleteLater()
        self._layout.addWidget(open_btn)
        self._layout.addStretch(1)
        


if __name__ == "__main__":
    from qtpy.QtWidgets import QApplication
    app = QApplication([])
    window = WidgetLibrary()
    window.show()
    app.exec() 
