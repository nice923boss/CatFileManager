"""Right-click context menu construction for FilePanel (mixin)."""

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
    _show_file_properties,
)


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
    attributes/methods provided by the host panel (``self.tree``, ``self.model``,
    ``self.other_panels``, ``self._copy_to`` …) resolved via the final MRO.
    """

    def _show_context_menu(self, pos):
        self.activated.emit(self.panel_id)

        menu = QMenu(self)
        selected = self._get_selected_paths()
        current_dir = self.current_path()

        act_cmd = QAction("在此開啟 CMD", self)
        act_cmd.triggered.connect(lambda: self._open_cmd(current_dir))
        menu.addAction(act_cmd)

        # New folder
        act_new_folder = QAction("新增資料夾", self)
        act_new_folder.triggered.connect(lambda: self._new_folder(current_dir))
        menu.addAction(act_new_folder)

        # New text file (notepad)
        act_new_txt = QAction("新增記事本", self)
        act_new_txt.triggered.connect(lambda: self._new_textfile(current_dir))
        menu.addAction(act_new_txt)

        menu.addSeparator()

        if selected:
            target = link_target(selected[0]) if len(selected) == 1 else None
            if target and os.path.isdir(target):
                act_real = QAction(f"開啟實際位置（{target}）", self)
                act_real.triggered.connect(lambda checked=False, p=target: self.navigate_to(p))
                menu.addAction(act_real)
                menu.addSeparator()

            if len(selected) == 1 and os.path.isfile(selected[0]):
                ext = os.path.splitext(selected[0])[1].lower()
                apps = _get_open_with_apps(ext)

                # Right-click a registry-sourced app entry to remove it.
                open_with_menu = _OpenWithMenu("開啟方式", self, self._open_with_remove, ext)

                act_default = QAction("預設程式", self)
                file_path = selected[0]
                act_default.triggered.connect(
                    lambda checked=False, p=file_path: self._shell_open(p)
                )
                open_with_menu.addAction(act_default)

                open_with_menu.addSeparator()

                act_notepad = QAction("記事本", self)
                act_notepad.triggered.connect(
                    lambda checked=False, p=file_path: subprocess.Popen(["notepad.exe", p])
                )
                open_with_menu.addAction(act_notepad)

                if apps:
                    open_with_menu.addSeparator()
                    for app_name, app_cmd in apps[:10]:
                        act_app = QAction(app_name, self)
                        # Marks this as a removable, registry-sourced entry;
                        # fixed entries above carry no data().
                        act_app.setData(app_name)
                        act_app.triggered.connect(
                            lambda checked=False, c=app_cmd, p=file_path: self._open_with(c, p)
                        )
                        open_with_menu.addAction(act_app)

                open_with_menu.addSeparator()
                act_choose = QAction("選擇其他程式...", self)
                act_choose.triggered.connect(
                    lambda checked=False, p=file_path: self._open_with_dialog(p)
                )
                open_with_menu.addAction(act_choose)

                menu.addMenu(open_with_menu)

                act_admin = QAction("以系統管理員身分開啟", self)
                act_admin.triggered.connect(
                    lambda checked=False, p=file_path: self._run_as_admin(p)
                )
                menu.addAction(act_admin)

            send_to_menu = QMenu("傳送到", self)
            act_clip = QAction("剪貼簿（複製檔案）", self)
            paths_copy = list(selected)
            act_clip.triggered.connect(
                lambda checked=False, p=paths_copy: self._copy_files_to_clipboard(p)
            )
            send_to_menu.addAction(act_clip)
            send_to_menu.addSeparator()

            # HandBrake for video files
            _VIDEO_EXTS = {
                ".mp4",
                ".mkv",
                ".avi",
                ".mov",
                ".wmv",
                ".flv",
                ".webm",
                ".m4v",
                ".mpg",
                ".mpeg",
                ".ts",
                ".vob",
            }
            video_files = [
                p
                for p in selected
                if os.path.isfile(p) and os.path.splitext(p)[1].lower() in _VIDEO_EXTS
            ]
            if video_files:
                act_handbrake = QAction("HandBrake", self)
                act_handbrake.triggered.connect(
                    lambda checked=False, p=video_files: self._open_with_handbrake(p[0])
                )
                send_to_menu.addAction(act_handbrake)
                send_to_menu.addSeparator()

            send_to_items = _get_send_to_items()
            for display, shortcut_path in send_to_items:
                act_send = QAction(display, self)
                act_send.triggered.connect(
                    lambda checked=False, s=shortcut_path, p=paths_copy: self._send_to(s, p)
                )
                send_to_menu.addAction(act_send)
            menu.addMenu(send_to_menu)

            menu.addSeparator()

            copy_menu = QMenu("複製到", self)
            for panel in self.other_panels:
                target_path = panel.current_path()
                label = (
                    f"面板 {panel.panel_id + 1}  ({os.path.basename(target_path) or target_path})"
                )
                act_copy = QAction(label, self)
                act_copy.triggered.connect(
                    lambda checked=False, s=list(selected), d=target_path: self._copy_to(s, d)
                )
                copy_menu.addAction(act_copy)
            menu.addMenu(copy_menu)

            move_menu = QMenu("移動到", self)
            for panel in self.other_panels:
                target_path = panel.current_path()
                label = (
                    f"面板 {panel.panel_id + 1}  ({os.path.basename(target_path) or target_path})"
                )
                act_move = QAction(label, self)
                act_move.triggered.connect(
                    lambda checked=False, s=list(selected), d=target_path: self._move_to(s, d)
                )
                move_menu.addAction(act_move)
            menu.addMenu(move_menu)

            menu.addSeparator()

            act_del = QAction("刪除（移至資源回收筒）", self)
            act_del.triggered.connect(lambda: self._delete(selected))
            menu.addAction(act_del)

            act_zip = QAction("壓縮成 ZIP", self)
            zip_paths = list(selected)
            act_zip.triggered.connect(lambda checked=False, p=zip_paths: self._compress_to_zip(p))
            menu.addAction(act_zip)

            _ARCHIVE_SIMPLE_EXTS = {".zip", ".7z", ".rar", ".tar", ".gz", ".bz2", ".xz", ".tgz"}
            _ARCHIVE_COMPOUND_EXTS = (".tar.gz", ".tar.bz2", ".tar.xz")
            archives = [
                p
                for p in selected
                if os.path.isfile(p)
                and (
                    os.path.splitext(p)[1].lower() in _ARCHIVE_SIMPLE_EXTS
                    or p.lower().endswith(_ARCHIVE_COMPOUND_EXTS)
                )
            ]
            if archives:
                act_extract = QAction("解壓縮全部", self)
                act_extract.triggered.connect(
                    lambda checked=False, p=list(archives): self._extract_archive(p)
                )
                menu.addAction(act_extract)

            if len(selected) == 1:
                act_rename = QAction("重新命名", self)
                act_rename.triggered.connect(lambda: self._rename(selected[0]))
                menu.addAction(act_rename)
            else:
                act_batch = QAction("批次重新命名（含序號）", self)
                act_batch.triggered.connect(self._batch_rename)
                menu.addAction(act_batch)

            menu.addSeparator()

            act_path = QAction("複製路徑", self)
            act_path.triggered.connect(lambda: self._copy_path(selected))
            menu.addAction(act_path)

            files_only = [p for p in selected if os.path.isfile(p)]
            if files_only:
                act_hash = QAction("計算哈希值", self)
                hash_paths = list(files_only)
                act_hash.triggered.connect(
                    lambda checked=False, p=hash_paths: self._calculate_hash(p)
                )
                menu.addAction(act_hash)

            if len(selected) == 1:
                act_shortcut = QAction("建立捷徑", self)
                act_shortcut.triggered.connect(
                    lambda checked=False, p=selected[0]: self._create_shortcut(p)
                )
                menu.addAction(act_shortcut)

            folders = [p for p in selected if os.path.isdir(p)]
            if folders:
                menu.addSeparator()
                for folder in folders:
                    folder_name = os.path.basename(folder) or folder
                    act_fav = QAction(f"★ 加入我的最愛：{folder_name}", self)
                    act_fav.triggered.connect(
                        lambda checked=False, p=folder: self.add_to_favorites.emit(p)
                    )
                    menu.addAction(act_fav)

            menu.addSeparator()
            act_props = QAction("內容", self)
            if len(selected) == 1:
                act_props.triggered.connect(
                    lambda checked=False, p=selected[0]: _show_file_properties(p)
                )
            else:
                act_props.setEnabled(False)
            menu.addAction(act_props)

        menu.exec(self.tree.viewport().mapToGlobal(pos))

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
