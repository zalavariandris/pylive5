import json
from pathlib import Path
from typing import Any

import pytest
from pytestqt.qtbot import QtBot

from pyflow5.pyflow5_document import PyFlowDocument
from pygraphrt.abstract_module_rt import OperatorRef
from pygraphrt.graph_rt import NodeRef
from qtpy.QtCore import QPointF

@pytest.fixture
def graph():
    # Setup code for creating a graph instance
    graph = PyFlowDocument().graph

    script_module_1 = {
        
    }
    yield graph
    # Teardown code if necessary
    pass