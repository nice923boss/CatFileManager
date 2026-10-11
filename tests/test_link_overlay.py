"""Tests for the NTFS junction / symlink arrow overlay.

Junction folders (e.g. C:\\Users\\Clare\\Downloads\\AI Project -> F:\\AI Project)
must be detected during the directory scan and drawn with an Explorer-style
arrow badge, so they are distinguishable from real folders.
"""

import os
import subprocess
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from file_model import _ScanWorker  # noqa: E402
from link_icon import with_link_overlay  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _make_junction(link: str, target: str):
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", link, target],
        check=True, capture_output=True,
    )


def test_scan_marks_junction_as_link_dir(qapp, tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (tmp_path / "plain.txt").write_text("x")
    _make_junction(str(tmp_path / "jct"), str(real))

    entries = {}
    worker = _ScanWorker(str(tmp_path))
    worker.done.connect(lambda found: entries.update({e.name: e for e in found}))
    worker.run()  # synchronous; no thread needed for the test

    assert entries["jct"].is_dir and entries["jct"].is_link
    assert entries["real"].is_dir and not entries["real"].is_link
    assert not entries["plain.txt"].is_link


def test_overlay_changes_bottom_left_pixels(qapp):
    from PySide6.QtGui import QColor, QIcon, QPixmap

    base_pm = QPixmap(32, 32)
    base_pm.fill(QColor("#e8b84b"))
    base = QIcon(base_pm)

    out = with_link_overlay(base).pixmap(32, 32).toImage()
    before = base_pm.toImage()

    assert out.pixelColor(4, 28) != before.pixelColor(4, 28)  # badge area
    assert out.pixelColor(28, 4) == before.pixelColor(28, 4)  # untouched corner


def test_link_target_resolves_junction_only(tmp_path):
    from link_icon import link_target

    real = tmp_path / "real"
    real.mkdir()
    _make_junction(str(tmp_path / "jct"), str(real))

    assert os.path.normcase(link_target(str(tmp_path / "jct"))) == os.path.normcase(str(real))
    assert link_target(str(real)) is None
