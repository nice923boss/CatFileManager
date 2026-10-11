import os
import subprocess
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def make_junction(link, target) -> None:
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)], check=True, capture_output=True
    )


def set_hidden(path) -> None:
    subprocess.run(["attrib", "+h", str(path)], check=True, capture_output=True)


def pytest_sessionfinish(session, exitstatus):
    # The app stops the icon thread on aboutToQuit, which tests never emit; a
    # QThread still running at interpreter exit aborts the process (0xC0000409).
    loader = sys.modules.get("icon_loader")
    if loader is not None and loader._instance is not None:
        loader._instance.stop()
