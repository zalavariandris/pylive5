"""Display data from the terminal using the shared, automatically started stage."""

import numpy as np
from qtpy.QtWidgets import QApplication

from myqtx.cmdstage.data import HTML, Image, ImageCompare, Markdown
from myqtx.displaywidget import DisplayWidget

from vfxops.io import read_image
imgA = read_image("assets/SMPTE_Color_Bars.png")
imgB = read_image("assets/IMG_0885.JPG")
app = QApplication([])
display_widget = DisplayWidget()
display_widget.display(ImageCompare(imgA, imgB))
display_widget.show()
app.exec()
