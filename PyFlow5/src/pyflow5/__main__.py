from pyflow5.pyflow5_window import PyFlow5Window

if __name__ == "__main__":
    from qtpy.QtWidgets import QApplication
    import sys
    app = QApplication(sys.argv)
    window = PyFlow5Window(use_session=True)
    window.setWindowTitle("PyFlow5 - DirectionalGraphView5")
    window.show()
    sys.exit(app.exec_())
    