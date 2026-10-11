from PySide6.QtCore import Qt

from settings import DEFAULT_PREFS
from settings_dialog import SettingsDialog
from tree_panel import FavoritesWidget


def test_settings_dialog_round_trips_defaults(qapp):
    prefs = dict(DEFAULT_PREFS)
    assert SettingsDialog(prefs).prefs() == prefs


def test_settings_dialog_round_trips_custom_values(qapp, tmp_path):
    prefs = {
        **DEFAULT_PREFS,
        "theme": "light",
        "font_size": 16,
        "layout": "2h",
        "show_hidden": True,
        "startup_mode": "fixed",
        "startup_paths": [str(tmp_path), "", "", ""],
        "verify_after_copy": True,
        "shortcuts": {"refresh": "Ctrl+R"},
        "context_menu_hidden": ["properties"],
        "search_history": ["*.jpg"],
    }
    dlg = SettingsDialog(prefs)
    assert dlg.prefs() == prefs
    assert prefs["theme"] == "light"  # input dict untouched


def test_favorites_flag_missing_paths(qapp, tmp_path):
    gone = str(tmp_path / "gone")
    fav = FavoritesWidget()
    fav.load_favorites([{"name": "家", "path": str(tmp_path)}, {"name": "舊", "path": gone}])
    ok_item, missing_item = fav.list_widget.item(0), fav.list_widget.item(1)
    assert "找不到" not in ok_item.text()
    assert "找不到" in missing_item.text()
    assert missing_item.data(Qt.ItemDataRole.UserRole) == gone

    messages = []
    fav.status_message.connect(messages.append)
    fav._on_item_clicked(missing_item)
    assert messages == [f"找不到資料夾：{gone}"]

    (tmp_path / "gone").mkdir()
    fav.refresh_status()
    assert "找不到" not in fav.list_widget.item(1).text()
