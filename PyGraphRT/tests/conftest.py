import os
from time import monotonic

import pytest
from qtpy.QtCore import QCoreApplication, QEvent
from qtpy.QtTest import QTest


@pytest.hookimpl(trylast=True)
def pytest_configure(config: pytest.Config) -> None:
    """Use project-local temporary files, avoiding inaccessible system pytest caches."""
    if config.option.basetemp or "PYTEST_DEBUG_TEMPROOT" in os.environ:
        return
    if config.cache is None:
        return

    patch = pytest.MonkeyPatch()
    patch.setenv("PYTEST_DEBUG_TEMPROOT", str(config.cache.mkdir("tmp")))
    config.add_cleanup(patch.undo)


@pytest.fixture(scope="session")
def qt_app():
    app = QCoreApplication.instance() or QCoreApplication([])
    yield app
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


@pytest.fixture
def wait_until(qt_app):
    def wait(condition, timeout_ms=3000):
        deadline = monotonic() + timeout_ms / 1000
        while not condition() and monotonic() < deadline:
            QTest.qWait(10)
        assert condition(), "Timed out waiting for a file change to be processed"

    return wait
