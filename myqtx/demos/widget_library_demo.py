from qtpy.QtWidgets import QDialog, QListView, QWidget, QVBoxLayout, QPushButton, QLineEdit, QLabel
from qtpy.QtCore import QItemSelection, QItemSelectionModel, QStringListModel

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

        self._layout.addWidget(self.create_listview())

    def create_listview(self):
        """ QListView, demonstrating selection and focus visibilty """
        listview = QListView()
        model = QStringListModel([f"Item {i}" for i in range(1, 10)])
        selection = QItemSelectionModel(model)
        
        listview.setSelectionMode(QListView.SelectionMode.MultiSelection)
        
        listview.setModel(model)
        listview.setSelectionModel(selection)

        selection.setCurrentIndex(model.index(1, 0), QItemSelectionModel.SelectionFlag.Current)
        selection.select(QItemSelection(model.index(3, 0), model.index(6, 0)), QItemSelectionModel.SelectionFlag.Select)

        print(selection.currentIndex().row())
        print([index.row() for index in selection.selectedIndexes()])

        def print_selection_state():
            from textwrap import dedent

            print(dedent(f"""
                Current index:    {selection.currentIndex().row()}
                Selected indexes: {[index.row() for index in selection.selectedIndexes()]}
            """))
        selection.currentChanged.connect(lambda current, previous: print_selection_state())
        selection.selectionChanged.connect(lambda selected, deselected: print_selection_state())
        return listview


        


if __name__ == "__main__":
    from qtpy.QtWidgets import QApplication
    app = QApplication([])
    app.setStyle("Fusion") # note: without the fusion style, the currect index is not visible at all.
    
    window = WidgetLibrary()
    window.show()
    app.exec() 
