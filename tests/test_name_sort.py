"""Tests for true name-based sorting in DirectoryModel.

The Name column must sort folders and files together by name, with
human-friendly numeric ordering, instead of forcing all folders to the top.
So "01image.png", "02doc.txt", "03folder/" stay in 01/02/03 order even though
03 is a folder, and "2" sorts before "10".

Other columns (Size, Type) keep folder-first grouping, which this also pins.
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

# Make the project root importable when pytest is run from anywhere.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import file_model  # noqa: E402
from file_model import FileEntry, _natural_key  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _entry(name: str, is_dir: bool = False, size: int = 0, modified: float = 0.0):
    ext = "" if is_dir else os.path.splitext(name)[1]
    return FileEntry(name, f"C:\\{name}", is_dir, size, modified, ext)


def _sorted_names(qapp, entries, column, order=None):
    from PySide6.QtCore import Qt

    if order is None:
        order = Qt.SortOrder.AscendingOrder
    model = file_model.DirectoryModel()
    model._entries = list(entries)
    model.sort(column, order)
    return [e.name for e in model._entries]


# --- _natural_key (pure helper) -------------------------------------------


def test_natural_key_splits_text_and_numbers():
    assert _natural_key("01image") == ["", 1, "image"]
    assert _natural_key("file") == ["file"]


def test_natural_key_orders_numbers_numerically():
    assert _natural_key("2") < _natural_key("10")
    assert _natural_key("file2") < _natural_key("file10")


# --- Name column: folders and files intermix by number -------------------


def test_name_sort_intermixes_folders_and_files_by_number(qapp):
    # The bug: a folder used to jump to the top regardless of its number.
    entries = [
        _entry("03folder", is_dir=True),  # listed first to reproduce the bug
        _entry("01image.png"),
        _entry("02doc.txt"),
    ]
    assert _sorted_names(qapp, entries, 0) == ["01image.png", "02doc.txt", "03folder"]


def test_name_sort_intermixes_chinese_prefixed_names(qapp):
    entries = [
        _entry("03資料夾", is_dir=True),
        _entry("01圖檔.png"),
        _entry("02文件檔.txt"),
    ]
    assert _sorted_names(qapp, entries, 0) == ["01圖檔.png", "02文件檔.txt", "03資料夾"]


def test_name_sort_is_numeric_not_lexical(qapp):
    entries = [_entry("10.txt"), _entry("2.txt"), _entry("1.txt")]
    assert _sorted_names(qapp, entries, 0) == ["1.txt", "2.txt", "10.txt"]


def test_name_sort_uses_displayed_name_for_shortcuts(qapp):
    # ".lnk" is hidden in the Name column, so it must not affect order:
    # "03app.lnk" displays as "03app" and must sort before "03docs.txt".
    entries = [_entry("03docs.txt"), _entry("03app.lnk")]
    assert _sorted_names(qapp, entries, 0) == ["03app.lnk", "03docs.txt"]


def test_name_sort_descending_reverses_intermixed_order(qapp):
    from PySide6.QtCore import Qt

    entries = [
        _entry("03folder", is_dir=True),
        _entry("01image.png"),
        _entry("02doc.txt"),
    ]
    names = _sorted_names(qapp, entries, 0, Qt.SortOrder.DescendingOrder)
    assert names == ["03folder", "02doc.txt", "01image.png"]


# --- Other columns keep folder-first grouping (regression guard) ----------


def test_size_sort_still_groups_folders_first(qapp):
    entries = [
        _entry("big.bin", size=5000),
        _entry("zfolder", is_dir=True),
        _entry("small.txt", size=10),
    ]
    # Folders (size shown blank) stay grouped ahead of files when sorting by Size.
    assert _sorted_names(qapp, entries, 1)[0] == "zfolder"


def test_size_sort_descending_keeps_folders_on_top(qapp):
    from PySide6.QtCore import Qt

    # The bug: descending Size flipped the whole (dir_priority, size) tuple,
    # so folders sank below files. Folder-first grouping must survive both
    # directions; only the size value reverses.
    entries = [
        _entry("big.bin", size=5000),
        _entry("zfolder", is_dir=True),
        _entry("small.txt", size=10),
    ]
    names = _sorted_names(qapp, entries, 1, Qt.SortOrder.DescendingOrder)
    assert names[0] == "zfolder"
    # Files below the folder are ordered by descending size.
    assert names[1:] == ["big.bin", "small.txt"]
