from qtpy.QtWidgets import QApplication, QPushButton, QWidget, QHBoxLayout, QVBoxLayout

from myqtx.widgets import DisplayWidget



if __name__ == "__main__":
    app = QApplication([])

    display_widget = DisplayWidget()
    import numpy as np

    window = QWidget()
    layout = QHBoxLayout()
    sidebar_layout = QVBoxLayout()
    for data_name, data_value in {
        "text": "Hello",
        "image": np.random.normal(0.5,0.1,(156, 256,3)).astype(np.float32), # random image with np 
        "exception": Exception("This is an exception"),
        "html": DisplayWidget.HTML("<b>Bold HTML</b>"),
        "markdown": DisplayWidget.Markdown("# Bold Markdown\n\nParagraph _italic_ **bold**!\n"),
        "image_compare": DisplayWidget.ImageCompare(
            np.random.normal(0.5,0.1,(156, 256,3)).astype(np.float32), 
            np.random.normal(0.5,0.1,(156, 256,3)).astype(np.float32)
        )
    }.items():
        btn = QPushButton(data_name)
        def on_press(data_value=data_value):
            display_widget.display(data_value)

        btn.pressed.connect(on_press)
        sidebar_layout.addWidget(btn)
        
    sidebar_layout.addStretch()
    
    layout.addLayout(sidebar_layout)
    layout.addWidget(display_widget)

    window.setLayout(layout)
    window.show()
    app.exec()
