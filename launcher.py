from pyflow5.pyflow5_window import PyFlow5Window

def launch_pyflow5():
    from qtpy.QtWidgets import QApplication
    import sys
    app = QApplication(sys.argv)
    window = PyFlow5Window()
    window.setWindowTitle("PyFlow5 - DirectionalGraphView5")
    window.show()
    sys.exit(app.exec_())
    

if __name__ == "__main__":
    launch_pyflow5()
