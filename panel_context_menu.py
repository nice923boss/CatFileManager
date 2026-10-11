"""Right-click context menu construction for FilePanel (mixin).

Every entry has an id in :data:`CONTEXT_MENU_ITEMS`; the user can hide entries
and change their order in the settings dialog (F04). Separators are entries
too, so the user decides where the groups break.
"""

import os
import subprocess

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu

from link_icon import link_target
from shell_utils import (
    _get_open_with_apps,
    _get_send_to_items,
    _remove_open_with_app,
    _resolve_lnk_target,
    _show_file_properties,
)

SEPARATOR_PREFIX = "sep_"

# (id, label shown in the settings dialog), in the default order.
CONTEXT_MENU_ITEMS = (
    ("open_cmd", "在此開啟 CMD"),
    ("open_powershell", "在此開啟 PowerShell"),
    ("open_terminal", "在此開啟 Windows Terminal"),
    ("new_folder", "新增資料夾"),
    ("new_textfile", "新增記事本"),
    ("sep_1", "分隔線"),
    ("open_real", "開啟實際位置（連結）"),
    ("open_in_panel", "在面板 N 開啟"),
    ("open_with", "開啟方式"),
    ("run_as_admin", "以系統管理員身分開啟"),
    ("send_to", "傳送到"),
    ("sep_2", "分隔線"),
    ("copy_to", "複製到"),
    ("move_to", "移動到"),
    ("sep_3", "分隔線"),
    ("delete", "刪除（移至資源回收筒）"),
    ("delete_permanent", "永久刪除"),
    ("zip", "壓縮成 ZIP"),
    ("extract", "解壓縮全部"),
    ("rename", "重新命名"),
    ("sep_4", "分隔線"),
    ("copy_path", "複製路徑"),
    ("copy_as", "複製為（檔名、正斜線路徑、含引號路徑）"),
    ("hash", "計算哈希值"),
    ("shortcut", "建立捷徑"),
    ("new_link", "建立 Junction／符號連結"),
    ("sep_5", "分隔線"),
    ("favorite", "加入我的最愛"),
    ("sep_6", "分隔線"),
    ("properties", "內容"),
)

_VIDEO_EXTS = {
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv",
    ".webm", ".m4v", ".mpg", ".mpeg", ".ts", ".vob",
}  # fmt: skip
_ARCHIVE_SIMPLE_EXTS = {".zip", ".7z", ".rar", ".tar", ".gz", ".bz2", ".xz", ".tgz"}
_ARCHIVE_COMPOUND_EXTS = (".tar.gz", ".tar.bz2", ".tar.xz")


def ordered_menu_ids(order: list[str]) -> list[str]:
    """The user's saved order, with unknown ids dropped and new ids appended."""
    known = [item_id for item_id, _ in CONTEXT_MENU_ITEMS]
    ids = [i for i in order if i in known]
    return ids + [i for i in known if i not in ids]


class _OpenWithMenu(QMenu):
    """Open-With submenu whose registry-sourced entries can be right-clicked to
    remove them from the list.

    QMenu never emits ``customContextMenuRequested`` for a right-click: as a
    popup it consumes mouse events itself for navigation and produces no
    context-menu event, so ``Qt.ContextMenuPolicy.CustomContextMenu`` has no
    effect on it. We therefore intercept the right-button press/release
    directly. Entries that carry a ``data()`` value are treated as removable;
    fixed entries (default / notepad / choose) carry none and pass through.
    """

    def __init__(self, title, parent, on_remove, ext):
        super().__init__(title, parent)
        self._on_remove = on_remove  # callable(menu, action, global_pos, ext)
        self._ext = ext
        self._pending = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            action = self.actionAt(event.position().toPoint())
            if action is not None and action.data():
                # Swallow the press so the menu does not track it as a click;
                # otherwise the matching release could trigger the app. Defer
                # the removal prompt to release (mirrors right-button timing).
                self._pending = (action, event.globalPosition().toPoint())
                event.accept()
                return
        self._pending = None
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton and self._pending:
            action, global_pos = self._pending
            self._pending = None
            event.accept()
            self._on_remove(self, action, global_pos, self._ext)
            return
        super().mouseReleaseEvent(event)


class FilePanelContextMenuMixin:
    """Builds the file-list right-click menu and its Open-With submenu actions.

    Designed to be mixed into :class:`FilePanel`; every method relies on
    attributes/methods provided by the host panel (``self.view()``, ``self.model``,
    ``self.other_panels``, ``self._copy_to`` …) resolved via the final MRO.
    """

    def _show_context_menu(self, pos):
        self.activated.emit(self.panel_id)
        selected = self._get_selected_paths()
        here = self.current_path()
        hidden = set(self.prefs.get("context_menu_hidden", []))

        menu = QMenu(self)
        pending_separator = False
        for item_id in ordered_menu_ids(self.prefs.get("context_menu_order", [])):
            if item_id in hidden:
                continue
            if item_id.startswith(SEPARATOR_PREFIX):
                pending_separator = True
                continue
            entries = self._menu_entries(item_id, selected, here)
            if not entries:
                continue
            if pending_separator and not menu.isEmpty():
                menu.addSeparator()
            pending_separator = False
            for entry in entries:
                if isinstance(entry, QMenu):
                    menu.addMenu(entry)
                else:
                    menu.addAction(entry)
        if not menu.isEmpty():
            menu.exec(self.view().viewport().mapToGlobal(pos))

    def _action(self, label: str, slot) -> QAction:
        act = QAction(label, self)
        act.triggered.connect(lambda checked=False: slot())
        return act

    def _target_panels(self) -> list:
        return [p for p in self.other_panels if p.isVisible() and p.current_path()]

    def _menu_entries(self, item_id: str, selected: list[str], here: str) -> list:
        """QActions / QMenus for one item id; empty when it doesn't apply."""
        single = selected[0] if len(selected) == 1 else ""
        sel = list(selected)

        # Items that act on the current folder (shown with or without selection)
        if item_id == "open_cmd":
            return [self._action("在此開啟 CMD", lambda: self._open_cmd(here))]
        if item_id == "open_powershell":
            return [self._action("在此開啟 PowerShell", lambda: self._open_powershell(here))]
        if item_id == "open_terminal":
            return [self._action("在此開啟 Windows Terminal", lambda: self._open_terminal(here))]
        if item_id == "new_folder":
            return [self._action("新增資料夾", lambda: self._new_folder(here))]
        if item_id == "new_textfile":
            return [self._action("新增記事本", lambda: self._new_textfile(here))]

        if not selected:
            return []

        if item_id == "open_real":
            target = link_target(single) if single else None
            if target and os.path.isdir(target):
                label = f"開啟實際位置（{target}）"
                return [self._action(label, lambda: self.navigate_to(target))]
            return []
        if item_id == "open_in_panel":
            return self._open_in_panel_entries(single)
        if item_id == "open_with":
            return [self._open_with_menu(single)] if single and os.path.isfile(single) else []
        if item_id == "run_as_admin":
            if single and os.path.isfile(single):
                return [self._action("以系統管理員身分開啟", lambda: self._run_as_admin(single))]
            return []
        if item_id == "send_to":
            return [self._send_to_menu(sel)]
        if item_id in ("copy_to", "move_to"):
            return [self._transfer_menu(item_id, sel)]
        if item_id == "delete":
            return [self._action("刪除（移至資源回收筒）", lambda: self._delete(sel))]
        if item_id == "delete_permanent":
            return [self._action("永久刪除（不經資源回收筒）", lambda: self._delete_permanent(sel))]
        if item_id == "zip":
            return [self._action("壓縮成 ZIP", lambda: self._compress_to_zip(sel))]
        if item_id == "extract":
            archives = [
                p
                for p in sel
                if os.path.isfile(p)
                and (
                    os.path.splitext(p)[1].lower() in _ARCHIVE_SIMPLE_EXTS
                    or p.lower().endswith(_ARCHIVE_COMPOUND_EXTS)
                )
            ]
            if archives:
                return [self._action("解壓縮全部", lambda: self._extract_archive(archives))]
            return []
        if item_id == "rename":
            if single:
                return [self._action("重新命名", lambda: self._rename(single))]
            return [self._action("批次重新命名（含序號）", self._batch_rename)]
        if item_id == "copy_path":
            return [self._action("複製路徑", lambda: self._copy_path(sel))]
        if item_id == "copy_as":
            sub = QMenu("複製為", self)
            for label, variant in (
                ("檔名", "name"),
                ("正斜線路徑（C:/…）", "slash"),
                ('含引號路徑（"C:\\…"）', "quoted"),
            ):
                sub.addAction(
                    self._action(label, lambda v=variant: self._copy_text_variant(sel, v))
                )
            return [sub]
        if item_id == "hash":
            files = [p for p in sel if os.path.isfile(p)]
            return (
                [self._action("計算哈希值", lambda: self._calculate_hash(files))] if files else []
            )
        if item_id == "shortcut":
            return (
                [self._action("建立捷徑", lambda: self._create_shortcut(single))] if single else []
            )
        if item_id == "new_link":
            if not single:
                return []
            sub = QMenu("建立連結", self)
            if os.path.isdir(single):
                sub.addAction(
                    self._action(
                        "Junction（資料夾，免權限）", lambda: self._create_link(single, "junction")
                    )
                )
            sub.addAction(self._action("符號連結", lambda: self._create_link(single, "symlink")))
            return [sub]
        if item_id == "favorite":
            return [
                self._action(
                    f"★ 加入我的最愛：{os.path.basename(f) or f}",
                    lambda f=f: self.add_to_favorites.emit(f),
                )
                for f in sel
                if os.path.isdir(f)
            ]
        if item_id == "properties":
            act = self._action("內容", lambda: _show_file_properties(single))
            act.setEnabled(bool(single))
            return [act]
        return []

    def _open_in_panel_entries(self, single: str) -> list:
        """B06: open the selected folder (or a link's target folder) in another panel."""
        if not single:
            return []
        folder = link_target(single) or single
        if single.lower().endswith(".lnk"):
            folder = _resolve_lnk_target(single)
        if not os.path.isdir(folder):
            return []

        def open_in(panel) -> None:
            panel.navigate_to(folder)
            panel.activated.emit(panel.panel_id)

        return [
            self._action(f"在面板 {p.panel_id + 1} 開啟", lambda p=p: open_in(p))
            for p in self.other_panels
            if p.isVisible()
        ]

    def _transfer_menu(self, item_id: str, sel: list[str]) -> QMenu:
        title = "複製到" if item_id == "copy_to" else "移動到"
        slot = self._copy_to if item_id == "copy_to" else self._move_to
        sub = QMenu(title, self)
        for panel in self._target_panels():
            dest = panel.current_path()
            label = f"面板 {panel.panel_id + 1}  ({os.path.basename(dest) or dest})"
            sub.addAction(self._action(label, lambda d=dest: slot(sel, d)))
        sub.setEnabled(not sub.isEmpty())
        return sub

    def _send_to_menu(self, sel: list[str]) -> QMenu:
        send_to_menu = QMenu("傳送到", self)
        send_to_menu.addAction(
            self._action("剪貼簿（複製檔案）", lambda: self._copy_files_to_clipboard(sel))
        )
        send_to_menu.addSeparator()

        video_files = [
            p for p in sel if os.path.isfile(p) and os.path.splitext(p)[1].lower() in _VIDEO_EXTS
        ]
        if video_files:
            send_to_menu.addAction(
                self._action("HandBrake", lambda: self._open_with_handbrake(video_files[0]))
            )
            send_to_menu.addSeparator()

        for display, shortcut_path in _get_send_to_items():
            send_to_menu.addAction(
                self._action(display, lambda s=shortcut_path: self._send_to(s, sel))
            )
        return send_to_menu

    def _open_with_menu(self, file_path: str) -> QMenu:
        ext = os.path.splitext(file_path)[1].lower()
        apps = _get_open_with_apps(ext)

        # Right-click a registry-sourced app entry to remove it.
        open_with_menu = _OpenWithMenu("開啟方式", self, self._open_with_remove, ext)
        open_with_menu.addAction(self._action("預設程式", lambda: self._shell_open(file_path)))
        open_with_menu.addSeparator()
        open_with_menu.addAction(
            self._action("記事本", lambda: subprocess.Popen(["notepad.exe", file_path]))
        )
        if apps:
            open_with_menu.addSeparator()
            for app_name, app_cmd in apps[:10]:
                act_app = self._action(app_name, lambda c=app_cmd: self._open_with(c, file_path))
                # Marks this as a removable, registry-sourced entry;
                # fixed entries above carry no data().
                act_app.setData(app_name)
                open_with_menu.addAction(act_app)
        open_with_menu.addSeparator()
        open_with_menu.addAction(
            self._action("選擇其他程式...", lambda: self._open_with_dialog(file_path))
        )
        return open_with_menu

    def _open_with_remove(self, menu: QMenu, action: QAction, global_pos, ext: str):
        """Offer to remove a right-clicked Open-With entry from the list."""
        app_name = action.data()
        if not app_name:
            return
        ctx = QMenu(menu)
        ctx.addAction(f"從清單移除「{app_name}」")
        # ctx holds a single item; exec() returns it when chosen or None when
        # dismissed, so a non-None result unambiguously means "remove".
        if ctx.exec(global_pos) is not None:
            if _remove_open_with_app(ext, app_name):
                menu.removeAction(action)
                self.status_message.emit(f"已移除「{app_name}」")
            else:
                self.status_message.emit(f"無法移除「{app_name}」")
