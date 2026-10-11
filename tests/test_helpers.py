import os

from PySide6.QtCore import Qt

from panel_context_menu import CONTEXT_MENU_ITEMS, ordered_menu_ids
from panel_widgets import drop_operation, expand_user_path
from shortcuts import find_conflicts
from transfer_ui import format_bytes

NONE = Qt.KeyboardModifier.NoModifier
CTRL = Qt.KeyboardModifier.ControlModifier
SHIFT = Qt.KeyboardModifier.ShiftModifier


def test_drop_operation_follows_explorer_rules():
    assert drop_operation([r"C:\a.txt"], r"C:\dest", NONE) == "move"
    assert drop_operation([r"C:\a.txt"], r"D:\dest", NONE) == "copy"
    assert drop_operation([r"C:\a.txt"], r"C:\dest", CTRL) == "copy"
    assert drop_operation([r"C:\a.txt"], r"D:\dest", SHIFT) == "move"


def test_expand_user_path_quotes_vars_and_home(monkeypatch):
    monkeypatch.setenv("CATFM_TEST_DIR", r"C:\Temp")
    assert expand_user_path(r'  "C:\Windows\System32"  ') == r"C:\Windows\System32"
    assert expand_user_path(r"%CATFM_TEST_DIR%\x") == r"C:\Temp\x"
    assert expand_user_path("~") == os.path.normpath(os.path.expanduser("~"))
    assert expand_user_path("   ") == ""


def test_expand_user_path_shell_folder():
    assert os.path.isdir(expand_user_path("shell:Desktop"))
    assert expand_user_path("shell:NoSuchFolder") == ""


def test_ordered_menu_ids_drops_unknown_and_appends_new():
    known = [i for i, _ in CONTEXT_MENU_ITEMS]
    order = ["properties", "bogus", known[0]]
    result = ordered_menu_ids(order)
    assert result[:2] == ["properties", known[0]]
    assert sorted(result) == sorted(known)


def test_find_conflicts_normalises_key_spelling():
    # Default delete binding is "Delete"; "Del" is the same key.
    overrides = {"copy": "Del"}
    conflicts = find_conflicts(overrides)
    assert any("copy" in ids for ids in conflicts.values())
    assert find_conflicts({}) == {}


def test_format_bytes():
    assert format_bytes(512) == "512 B"
    assert format_bytes(1536) == "1.5 KB"
    assert format_bytes(3 * 1024**3) == "3.0 GB"
