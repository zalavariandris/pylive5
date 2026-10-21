from pyflow5.views.pyflow5_documentwindow import PyFlow5DocumentWindow

def launch_pyflow5():
    from qtpy.QtWidgets import QApplication
    import sys
    app = QApplication(sys.argv)
    window = PyFlow5DocumentWindow()
    window.setWindowTitle("PyFlow5 - DirectionalGraphView5")
    window.show()
    sys.exit(app.exec_())
    

if __name__ == "__main__":
    launch_pyflow5()
