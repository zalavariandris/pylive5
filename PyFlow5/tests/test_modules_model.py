import json
from pathlib import Path
from typing import Any

import pytest
from pytestqt.qtbot import QtBot

from pyflow5.pyflow5_document import PyFlowDocument
from pygraphrt import NodeRef
from qtpy.QtCore import QPointF

@pytest.fixture
def graph():
    pass