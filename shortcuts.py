"""Keyboard-shortcut registry (H01, H02, H06).

Every command the user can bind lives here once. Panels and the main window
look up the effective key (user override or default) by action id, the F1
list and the command palette read the same table.
"""

from typing import NamedTuple

from PySide6.QtGui import QKeySequence


class Action(NamedTuple):
    id: str
    label: str
    default_key: str
    scope: str  # "panel" = acts on the active panel, "window" = global


ACTIONS: tuple[Action, ...] = (
    # File operations
    Action("copy", "複製", "Ctrl+C", "panel"),
    Action("cut", "剪下", "Ctrl+X", "panel"),
    Action("paste", "貼上", "Ctrl+V", "panel"),
    Action("delete", "刪除（移至資源回收筒）", "Delete", "panel"),
    Action("delete_permanent", "永久刪除", "Shift+Delete", "panel"),
    Action("rename", "重新命名", "F2", "panel"),
    Action("new_folder", "新增資料夾", "Ctrl+Shift+N", "panel"),
    Action("new_textfile", "新增記事本", "Ctrl+N", "panel"),
    Action("copy_path", "複製路徑", "Ctrl+Shift+C", "panel"),
    Action("undo", "復原上一個操作", "Ctrl+Z", "window"),
    # Selection / opening
    Action("select_all", "全選", "Ctrl+A", "panel"),
    Action("select_same_type", "選取同類型檔案", "Ctrl+Shift+T", "panel"),
    Action("open", "開啟", "Return", "panel"),
    Action("preview", "快速預覽", "Space", "panel"),
    # Navigation
    Action("go_up", "上一層", "Backspace", "panel"),
    Action("back", "上一頁", "Alt+Left", "panel"),
    Action("forward", "下一頁", "Alt+Right", "panel"),
    Action("focus_path", "輸入路徑", "Ctrl+L", "panel"),
    Action("refresh", "重新整理", "F5", "panel"),
    Action("next_panel", "切換到下一個面板", "Tab", "window"),
    Action("prev_panel", "切換到上一個面板", "Shift+Tab", "window"),
    Action("panel_1", "跳到面板 1", "Ctrl+1", "window"),
    Action("panel_2", "跳到面板 2", "Ctrl+2", "window"),
    Action("panel_3", "跳到面板 3", "Ctrl+3", "window"),
    Action("panel_4", "跳到面板 4", "Ctrl+4", "window"),
    # Search
    Action("search", "篩選目前資料夾", "Ctrl+F", "panel"),
    Action("search_recursive", "搜尋子資料夾", "Ctrl+Shift+F", "panel"),
    # View
    Action("view_details", "詳細資料檢視", "Ctrl+Shift+1", "panel"),
    Action("view_icons", "大圖示檢視", "Ctrl+Shift+2", "panel"),
    Action("toggle_hidden", "顯示／隱藏隱藏檔", "Ctrl+H", "window"),
    Action("toggle_extensions", "顯示／隱藏副檔名", "", "window"),
    # Open externally
    Action("open_cmd", "在此開啟 CMD", "", "panel"),
    Action("open_powershell", "在此開啟 PowerShell", "", "panel"),
    Action("open_terminal", "在此開啟 Windows Terminal", "", "panel"),
    # App
    Action("command_palette", "命令面板", "Ctrl+Shift+P", "window"),
    Action("shortcut_list", "快捷鍵一覽", "F1", "window"),
    Action("settings", "設定", "Ctrl+,", "window"),
    Action("about", "關於 CatFileManager", "", "window"),
)

_BY_ID = {a.id: a for a in ACTIONS}


def action(action_id: str) -> Action:
    return _BY_ID[action_id]


def key_for(action_id: str, overrides: dict[str, str]) -> str:
    """Effective key sequence text ("" = unbound)."""
    if action_id in overrides:
        return overrides[action_id]
    return _BY_ID[action_id].default_key


def find_conflicts(overrides: dict[str, str]) -> dict[str, list[str]]:
    """Key text -> action ids bound to it, only for keys used more than once."""
    used: dict[str, list[str]] = {}
    for a in ACTIONS:
        key = key_for(a.id, overrides)
        if key:
            # Normalise spellings ("Delete" vs "Del") before comparing.
            norm = QKeySequence(key).toString(QKeySequence.SequenceFormat.PortableText)
            used.setdefault(norm.lower(), []).append(a.id)
    return {k: ids for k, ids in used.items() if len(ids) > 1}
