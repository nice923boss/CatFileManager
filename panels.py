"""File panel widget — shows files in a directory with path bar.

`FilePanel` is assembled from focused modules:
  * :mod:`panel_widgets`      — breadcrumb / search / tree-view widgets
  * :mod:`panel_context_menu` — right-click menu (mixin)
  * :mod:`panel_actions`      — file operations + external launching (mixin)
  * :mod:`shell_utils`        — Windows shell / registry helpers
  * :mod:`file_dialogs`       — progress / hash dialogs
This module keeps the panel core: construction, navigation/history, search,
selection, keyboard shortcuts and the shared cross-panel clipboard state.
"""

import ctypes
import os
import subprocess

from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QPushButton, QTreeView,
    QVBoxLayout, QWidget,
)
from PySide6.QtCore import (
    Qt, Signal, QModelIndex, QMimeData, QUrl, QTimer, QThread,
)
from PySide6.QtGui import QKeySequence, QShortcut

from file_model import DirectoryModel
from panel_widgets import _FileTreeView, BreadcrumbBar, SearchBar
from shell_utils import _SHELLEXECUTEINFO, _resolve_lnk_target
from panel_actions import FilePanelActionsMixin
from panel_context_menu import FilePanelContextMenuMixin


# --- Shared clipboard across all panels ---
_shared_clipboard_paths: list[str] = []
_shared_clipboard_op: str = ""  # "copy" or "cut"


class FilePanel(FilePanelActionsMixin, FilePanelContextMenuMixin, QWidget):
    """Single file browser panel with path bar and file list."""

    activated = Signal(int)
    status_message = Signal(str)
    selection_changed = Signal(int)
    add_to_favorites = Signal(str)
    path_changed = Signal(int)

    def __init__(self, panel_id: int, parent=None):
        super().__init__(parent)
        self.panel_id = panel_id
        self.is_active = False
        self._workers: list[QThread] = []
        self._history: list[str] = []
        self._history_index = -1
        self._navigating_history = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        self.header = QLabel(f"  面板 {panel_id + 1}")
        self.header.setStyleSheet(
            "background-color: #2d2d2d; color: #888888; "
            "padding: 4px; font-size: 12px; font-weight: bold;"
        )
        layout.addWidget(self.header)

        # Navigation buttons + breadcrumb
        nav_bar = QHBoxLayout()
        nav_bar.setSpacing(2)

        self.btn_back = QPushButton("◀")
        self.btn_back.setFixedWidth(32)
        self.btn_back.setToolTip("上一頁")
        self.btn_back.clicked.connect(self._go_back)
        self.btn_back.setEnabled(False)
        nav_bar.addWidget(self.btn_back)

        self.btn_forward = QPushButton("▶")
        self.btn_forward.setFixedWidth(32)
        self.btn_forward.setToolTip("下一頁")
        self.btn_forward.clicked.connect(self._go_forward)
        self.btn_forward.setEnabled(False)
        nav_bar.addWidget(self.btn_forward)

        self.btn_up = QPushButton("↑")
        self.btn_up.setFixedWidth(32)
        self.btn_up.setToolTip("上一層")
        self.btn_up.clicked.connect(self._go_up)
        nav_bar.addWidget(self.btn_up)

        self.breadcrumb = BreadcrumbBar()
        self.breadcrumb.path_clicked.connect(self.navigate_to)
        nav_bar.addWidget(self.breadcrumb, 1)

        layout.addLayout(nav_bar)

        # Search bar (hidden by default)
        self.search_bar = SearchBar()
        self.search_bar.search_changed.connect(self._on_search)
        self.search_bar.closed.connect(self._on_search_close)
        layout.addWidget(self.search_bar)

        # File list
        self.tree = _FileTreeView()
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(False)
        self.tree.setSortingEnabled(True)
        self.tree.setSelectionMode(QTreeView.SelectionMode.ExtendedSelection)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        self.tree.doubleClicked.connect(self._on_double_click)
        self.tree.files_dropped.connect(self._on_files_dropped)

        self.model = DirectoryModel()
        self.tree.setModel(self.model)
        self.tree.setColumnWidth(0, 280)
        self.tree.setColumnWidth(1, 80)
        self.tree.setColumnWidth(2, 70)
        self.tree.setColumnWidth(3, 140)

        layout.addWidget(self.tree)

        self.tree.clicked.connect(lambda: self._on_click())
        # Clicks on empty space inside the tree don't emit `clicked`; make sure
        # they still activate this panel.
        self.tree.pressed_anywhere.connect(
            lambda: self.activated.emit(self.panel_id)
        )
        self.tree.selectionModel().selectionChanged.connect(
            lambda: self.selection_changed.emit(self.panel_id)
        )

        self.other_panels: list["FilePanel"] = []

        # Slow-click rename: click an already-selected file to rename
        self._rename_pending_path: str | None = None
        self._rename_timer = QTimer(self)
        self._rename_timer.setSingleShot(True)
        self._rename_timer.setInterval(500)
        self._rename_timer.timeout.connect(self._on_rename_timer)

        self._setup_shortcuts()

    # --- Shortcuts ---

    def _setup_shortcuts(self):
        shortcuts = [
            ("Ctrl+C", self._shortcut_copy),
            ("Ctrl+X", self._shortcut_cut),
            ("Ctrl+V", self._shortcut_paste),
            ("Delete", self._shortcut_delete),
            ("F2", self._shortcut_rename),
            ("Ctrl+A", self._shortcut_select_all),
            ("Return", self._shortcut_open),
            ("Backspace", self._go_up),
            ("Alt+Left", self._go_back),
            ("Alt+Right", self._go_forward),
            ("Ctrl+Shift+C", self._shortcut_copy_path),
            ("Ctrl+L", self._focus_breadcrumb_edit),
            ("Ctrl+F", self._shortcut_search),
            ("F5", self._shortcut_refresh),
            ("Space", self._shortcut_preview),
        ]
        for key, handler in shortcuts:
            sc = QShortcut(QKeySequence(key), self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(handler)

    def _shortcut_copy(self):
        global _shared_clipboard_paths, _shared_clipboard_op
        selected = self._get_selected_paths()
        if selected:
            _shared_clipboard_paths = selected
            _shared_clipboard_op = "copy"
            self._set_clipboard_files(selected)
            self.status_message.emit(f"已複製 {len(selected)} 個項目")

    def _shortcut_cut(self):
        global _shared_clipboard_paths, _shared_clipboard_op
        selected = self._get_selected_paths()
        if selected:
            _shared_clipboard_paths = selected
            _shared_clipboard_op = "cut"
            self._set_clipboard_files(selected)
            self.status_message.emit(f"已剪下 {len(selected)} 個項目")

    def _shortcut_paste(self):
        global _shared_clipboard_paths, _shared_clipboard_op
        if not _shared_clipboard_paths:
            clipboard = QApplication.clipboard()
            mime = clipboard.mimeData()
            if mime and mime.hasUrls():
                paths = [url.toLocalFile() for url in mime.urls() if url.isLocalFile()]
                if paths:
                    _shared_clipboard_paths = paths
                    _shared_clipboard_op = "copy"
        if not _shared_clipboard_paths:
            return
        dest = self.current_path()
        if not dest:
            return
        if _shared_clipboard_op == "cut":
            self._move_to(_shared_clipboard_paths, dest)
            _shared_clipboard_paths = []
            _shared_clipboard_op = ""
        else:
            self._copy_to(_shared_clipboard_paths, dest)

    def _shortcut_delete(self):
        selected = self._get_selected_paths()
        if selected:
            self._delete(selected)

    def _shortcut_rename(self):
        selected = self._get_selected_paths()
        if len(selected) == 1:
            self._rename(selected[0])
        elif len(selected) > 1:
            self._batch_rename()

    def _shortcut_select_all(self):
        self.tree.selectAll()

    def _shortcut_open(self):
        selected = self._get_selected_paths()
        if len(selected) == 1:
            self._open_item(selected[0], self.tree.selectionModel().selectedRows()[0])

    def _shortcut_copy_path(self):
        selected = self._get_selected_paths()
        if selected:
            self._copy_path(selected)

    def _shortcut_refresh(self):
        self._refresh()
        self.status_message.emit("已重新整理")

    def _shortcut_search(self):
        self.search_bar.activate()

    def _focus_breadcrumb_edit(self):
        self.breadcrumb._line_edit.setFocus()
        self.breadcrumb._line_edit.selectAll()

    _QUICKLOOK_PATH = os.path.join(
        os.path.expanduser("~"),
        r"AppData\Local\Programs\QuickLook\QuickLook.exe"
    )

    def _shortcut_preview(self):
        selected = self._get_selected_paths()
        if len(selected) == 1 and os.path.exists(self._QUICKLOOK_PATH):
            subprocess.Popen([self._QUICKLOOK_PATH, os.path.normpath(selected[0])])

    # --- Search ---

    def _on_search(self, text: str):
        """Hide rows that don't match the search text."""
        text_lower = text.lower()
        for row in range(self.model.rowCount()):
            idx = self.model.index(row, 0)
            name = self.model.file_name(idx).lower()
            self.tree.setRowHidden(row, QModelIndex(), text_lower not in name)

    def _on_search_close(self):
        """Show all rows again."""
        for row in range(self.model.rowCount()):
            self.tree.setRowHidden(row, QModelIndex(), False)

    # --- Navigation ---

    def _refresh(self):
        self.model.refresh()

    def _set_clipboard_files(self, paths: list[str]):
        mime = QMimeData()
        urls = [QUrl.fromLocalFile(os.path.normpath(p)) for p in paths]
        mime.setUrls(urls)
        mime.setText("\n".join(os.path.normpath(p) for p in paths))
        QApplication.clipboard().setMimeData(mime)

    def _copy_files_to_clipboard(self, paths: list[str]):
        self._set_clipboard_files(paths)
        self.status_message.emit(f"已複製 {len(paths)} 個檔案到剪貼簿")

    def navigate_to(self, path: str):
        if not os.path.isdir(path):
            return
        self._rename_timer.stop()
        self._rename_pending_path = None
        self.model.set_root_path(path)
        self.breadcrumb.set_path(path)
        self.selection_changed.emit(self.panel_id)
        self.path_changed.emit(self.panel_id)

        if not self._navigating_history:
            if self._history_index < len(self._history) - 1:
                self._history = self._history[:self._history_index + 1]
            if not self._history or self._history[-1] != path:
                self._history.append(path)
                self._history_index = len(self._history) - 1

        self._update_nav_buttons()

    def current_path(self) -> str:
        return self.model.root_path()

    def get_file_count(self) -> int:
        return self.model.rowCount()

    def get_selected_count(self) -> int:
        return len(self.tree.selectionModel().selectedRows())

    def get_selected_total_size(self) -> int:
        total = 0
        for idx in self.tree.selectionModel().selectedRows():
            path = self.model.file_path(idx)
            if path and os.path.isfile(path):
                try:
                    total += os.path.getsize(path)
                except OSError:
                    pass
        return total

    def set_active(self, active: bool):
        self.is_active = active
        if active:
            self.header.setStyleSheet(
                "background-color: #264f78; color: #ffffff; "
                "padding: 4px; font-size: 12px; font-weight: bold;"
            )
        else:
            self.header.setStyleSheet(
                "background-color: #2d2d2d; color: #888888; "
                "padding: 4px; font-size: 12px; font-weight: bold;"
            )

    def _on_click(self):
        self.activated.emit(self.panel_id)
        self.selection_changed.emit(self.panel_id)

        selected = self._get_selected_paths()
        if len(selected) != 1:
            # Multi-select or no selection — cancel any pending rename
            self._rename_timer.stop()
            self._rename_pending_path = None
            return

        path = selected[0]
        if self._rename_pending_path == path:
            # Second click on the same already-selected item — arm rename timer
            # (the timer adds a delay so double-click can cancel it)
            self._rename_timer.start()
        else:
            # First click selecting this item — just remember it
            self._rename_timer.stop()
            self._rename_pending_path = path

    def _on_rename_timer(self):
        """Fired after slow-click delay — trigger rename."""
        path = self._rename_pending_path
        self._rename_pending_path = None
        if path and os.path.exists(path):
            self._rename(path)

    def _go_back(self):
        if self._history_index > 0:
            self._history_index -= 1
            self._navigating_history = True
            self.navigate_to(self._history[self._history_index])
            self._navigating_history = False
        self.activated.emit(self.panel_id)

    def _go_forward(self):
        if self._history_index < len(self._history) - 1:
            self._history_index += 1
            self._navigating_history = True
            self.navigate_to(self._history[self._history_index])
            self._navigating_history = False
        self.activated.emit(self.panel_id)

    def _update_nav_buttons(self):
        self.btn_back.setEnabled(self._history_index > 0)
        self.btn_forward.setEnabled(self._history_index < len(self._history) - 1)

    def _go_up(self):
        current = self.current_path()
        parent = os.path.dirname(current)
        if parent and parent != current:
            self.navigate_to(parent)
        self.activated.emit(self.panel_id)

    def _open_item(self, path: str, index: QModelIndex):
        """Open a file or navigate into a directory. Resolves .lnk targets."""
        if not path:
            return
        if self.model.is_dir(index):
            self.navigate_to(path)
        elif path.lower().endswith(".lnk"):
            target = _resolve_lnk_target(path)
            if os.path.isdir(target):
                self.navigate_to(target)
            else:
                self._shell_open(os.path.normpath(path))
        else:
            self._shell_open(os.path.normpath(path))

    def _shell_open(self, path: str) -> None:
        """Open a file via ShellExecuteExW so SmartScreen / UAC prompts appear."""
        hwnd = int(self.window().winId())
        sei = _SHELLEXECUTEINFO()
        sei.cbSize = ctypes.sizeof(sei)
        sei.fMask = 0x00000040  # SEE_MASK_NOCLOSEPROCESS
        sei.hwnd = hwnd
        sei.lpVerb = "open"
        sei.lpFile = os.path.normpath(path)
        sei.lpDirectory = os.path.dirname(os.path.normpath(path))
        sei.nShow = 1  # SW_SHOWNORMAL
        # use_last_error so get_last_error() reliably reflects ShellExecuteExW.
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        if not shell32.ShellExecuteExW(ctypes.byref(sei)):
            err = ctypes.get_last_error()
            name = os.path.basename(path)
            if err == 1223:  # ERROR_CANCELLED — user dismissed the UAC / SmartScreen prompt
                self.status_message.emit(f"已取消開啟：{name}")
            else:
                self.status_message.emit(f"開啟失敗（錯誤碼 {err}）：{name}")

    def _on_double_click(self, index: QModelIndex):
        # Cancel any pending slow-click rename
        self._rename_timer.stop()
        self._rename_pending_path = None

        path = self.model.file_path(index)
        self._open_item(path, index)
        self.activated.emit(self.panel_id)

    def _get_selected_paths(self) -> list[str]:
        indexes = self.tree.selectionModel().selectedRows()
        return [self.model.file_path(idx) for idx in indexes]

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        self.activated.emit(self.panel_id)
