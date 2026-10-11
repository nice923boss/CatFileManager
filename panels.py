"""File panel widget: shows one folder with a path bar, search bar and two views.

`FilePanel` is assembled from focused modules:
  * :mod:`panel_widgets`      breadcrumb / file views
  * :mod:`search_bar`         filter and search entry (D01-D07)
  * :mod:`panel_context_menu` right-click menu (mixin)
  * :mod:`panel_actions`      file operations + external launching (mixin)
  * :mod:`shell_utils`        Windows shell / registry helpers
This module keeps the panel core: construction, navigation/history, filtering,
selection, view modes and the keyboard-shortcut registry hookup.
"""

import ctypes
import json
import os
import subprocess

from PySide6.QtCore import QItemSelection, QItemSelectionModel, QModelIndex, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from clipboard_state import file_clipboard
from file_model import DirectoryModel
from link_icon import link_target
from panel_actions import FilePanelActionsMixin
from panel_context_menu import FilePanelContextMenuMixin
from panel_widgets import BreadcrumbBar, _FileIconView, _FileTreeView
from search_bar import SearchBar
from search_dialog import SearchResultsDialog
from settings import DEFAULT_PREFS
from shell_utils import _SHELLEXECUTEINFO, _resolve_lnk_target
from shortcuts import ACTIONS, key_for
from theme import colors, resolve_theme

DEFAULT_WIDTHS = (280, 80, 70, 140)
VIEW_MODES = ("details", "icons")
QUICKLOOK_URL = "https://github.com/QL-Win/QuickLook"


def _quicklook_exe() -> str:
    candidates = (
        os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Programs\QuickLook\QuickLook.exe"),
        os.path.join(os.environ.get("ProgramFiles", ""), r"QuickLook\QuickLook.exe"),
    )
    return next((c for c in candidates if os.path.isfile(c)), "")


class FilePanel(FilePanelActionsMixin, FilePanelContextMenuMixin, QWidget):
    """Single file browser panel with path bar and file list."""

    activated = Signal(int)
    status_message = Signal(str)
    selection_changed = Signal(int)
    add_to_favorites = Signal(str)
    path_changed = Signal(int)

    def __init__(self, panel_id: int, queue, parent=None):
        super().__init__(parent)
        self.panel_id = panel_id
        self.queue = queue  # transfer_ui.OperationQueue shared by all panels
        self.prefs = json.loads(json.dumps(DEFAULT_PREFS))
        self.is_active = False
        self._workers = []  # zip / hash threads (panel_actions)
        self._history: list[str] = []
        self._history_index = -1
        self._navigating_history = False
        self._view_mode = "details"
        self._matcher = None  # current name filter
        self._hidden_rows: set[int] = set()
        self._pending_select = ""  # path to select once the folder has loaded
        self.other_panels: list[FilePanel] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        self.header = QLabel(f"  面板 {panel_id + 1}")
        self.header.setObjectName("panelHeader")
        self.header.setProperty("active", False)
        layout.addWidget(self.header)

        nav_bar = QHBoxLayout()
        nav_bar.setSpacing(2)
        self.btn_back = self._nav_button("◀", "上一頁", self._go_back)
        self.btn_forward = self._nav_button("▶", "下一頁", self._go_forward)
        self.btn_up = self._nav_button("↑", "上一層", self._go_up)
        self.btn_back.setEnabled(False)
        self.btn_forward.setEnabled(False)
        for btn in (self.btn_back, self.btn_forward, self.btn_up):
            nav_bar.addWidget(btn)
        self.breadcrumb = BreadcrumbBar()
        self.breadcrumb.path_clicked.connect(self.navigate_to)
        nav_bar.addWidget(self.breadcrumb, 1)
        layout.addLayout(nav_bar)

        self.search_bar = SearchBar()
        self.search_bar.filter_changed.connect(self._apply_filter)
        self.search_bar.search_requested.connect(self._open_search)
        self.search_bar.closed.connect(lambda: self._apply_filter(None))
        layout.addWidget(self.search_bar)

        self.model = DirectoryModel(self)
        self.tree = _FileTreeView()
        self.tree.setRootIsDecorated(False)
        self.tree.setSortingEnabled(True)
        self.tree.setModel(self.model)
        for col, width in enumerate(DEFAULT_WIDTHS):
            self.tree.setColumnWidth(col, width)
        self.icons = _FileIconView()
        self.icons.setModel(self.model)
        self.icons.setSelectionModel(self.tree.selectionModel())
        for view in (self.tree, self.icons):
            view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
            view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            view.customContextMenuRequested.connect(self._show_context_menu)
            view.doubleClicked.connect(self._on_double_click)
            view.files_dropped.connect(self._on_files_dropped)
            view.clicked.connect(lambda _idx: self._on_click())
            # Clicks on empty space don't emit `clicked`; still activate the panel.
            view.pressed_anywhere.connect(lambda: self.activated.emit(self.panel_id))
        self.stack = QStackedWidget()
        self.stack.addWidget(self.tree)
        self.stack.addWidget(self.icons)
        layout.addWidget(self.stack, 1)

        self.tree.selectionModel().selectionChanged.connect(
            lambda: self.selection_changed.emit(self.panel_id)
        )
        self.model.modelReset.connect(self._on_model_reset)
        self.model.layoutChanged.connect(self._sync_hidden_rows)
        self.model.scan_progress.connect(self._on_scan_progress)
        self.model.scan_finished.connect(self._on_scan_finished)
        self.model.root_missing.connect(self._on_root_missing)

        # Slow-click rename: click an already-selected file to rename
        self._rename_pending_path: str | None = None
        self._rename_timer = QTimer(self)
        self._rename_timer.setSingleShot(True)
        self._rename_timer.setInterval(500)
        self._rename_timer.timeout.connect(self._on_rename_timer)

        self._shortcuts: dict[str, QShortcut] = {}
        for a in ACTIONS:
            if a.scope == "panel":
                sc = QShortcut(self)
                sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
                sc.activated.connect(lambda aid=a.id: self.run_action(aid))
                self._shortcuts[a.id] = sc
        self.apply_shortcuts({})

    def _nav_button(self, text: str, tip: str, slot) -> QPushButton:
        btn = QPushButton(text)
        btn.setFixedWidth(32)
        btn.setToolTip(tip)
        btn.clicked.connect(slot)
        return btn

    # --- Preferences / view state ---

    def apply_shortcuts(self, overrides: dict[str, str]) -> None:
        for action_id, sc in self._shortcuts.items():
            sc.setKey(QKeySequence(key_for(action_id, overrides)))

    def apply_prefs(self, prefs: dict) -> None:
        self.prefs = prefs
        palette = colors(resolve_theme(prefs["theme"]))
        type_colors = None
        if prefs["color_by_type"]:
            type_colors = {k: palette[k] for k in ("image", "video", "archive", "exec", "broken")}
        self.model.set_view_options(
            prefs["show_hidden"], prefs["show_extensions"], type_colors, palette["text"]
        )
        self.apply_shortcuts(prefs.get("shortcuts", {}))

    def view_state(self) -> dict:
        """A07: column widths, sort and view mode, saved per panel."""
        header = self.tree.header()
        col, order = self.model.sort_state()
        return {
            "widths": [header.sectionSize(i) for i in range(self.model.columnCount())],
            "sort": [col, order.value],
            "view": self._view_mode,
        }

    def restore_view_state(self, state: dict) -> None:
        widths = state.get("widths") or []
        for col, width in enumerate(widths[: self.model.columnCount()]):
            if isinstance(width, int) and width > 10:
                self.tree.setColumnWidth(col, width)
        sort = state.get("sort")
        if isinstance(sort, list) and len(sort) == 2:
            col, order = sort
            if 0 <= col < self.model.columnCount() and order in (0, 1):
                self.tree.sortByColumn(col, Qt.SortOrder(order))
        mode = state.get("view", "details")
        self.set_view_mode(mode if mode in VIEW_MODES else "details")

    def view(self) -> QAbstractItemView:
        return self.icons if self._view_mode == "icons" else self.tree

    def set_view_mode(self, mode: str) -> None:
        """A02: details list or large icons with thumbnails."""
        rows = self._selected_rows()
        self._view_mode = mode
        icons = mode == "icons"
        self.model.set_icon_size(_FileIconView.ICON_SIZE if icons else 16)
        self.stack.setCurrentWidget(self.view())
        self._select_rows(rows)

    def set_active(self, active: bool) -> None:
        self.is_active = active
        self.header.setProperty("active", active)
        self.header.style().unpolish(self.header)
        self.header.style().polish(self.header)

    # --- Actions (shortcut registry) ---

    def run_action(self, action_id: str) -> None:
        self._cancel_pending_rename()
        here = self.current_path()
        handlers = {
            "copy": lambda: self._to_clipboard("copy"),
            "cut": lambda: self._to_clipboard("cut"),
            "paste": self._paste,
            "delete": lambda: self._with_selection(self._delete),
            "delete_permanent": lambda: self._with_selection(self._delete_permanent),
            "rename": self._rename_selected,
            "new_folder": lambda: self._new_folder(here),
            "new_textfile": lambda: self._new_textfile(here),
            "copy_path": lambda: self._with_selection(self._copy_path),
            "select_all": lambda: self._select_rows(self._visible_rows()),
            "select_same_type": self._select_same_type,
            "open": self._open_selected,
            "preview": self._preview,
            "go_up": self._go_up,
            "back": self._go_back,
            "forward": self._go_forward,
            "focus_path": self._focus_breadcrumb_edit,
            "refresh": self._shortcut_refresh,
            "search": lambda: self.search_bar.activate("filter"),
            "search_recursive": lambda: self.search_bar.activate("recursive"),
            "view_details": lambda: self.set_view_mode("details"),
            "view_icons": lambda: self.set_view_mode("icons"),
            "open_cmd": lambda: self._open_cmd(here),
            "open_powershell": lambda: self._open_powershell(here),
            "open_terminal": lambda: self._open_terminal(here),
        }
        handler = handlers.get(action_id)
        if handler:
            handler()

    def _with_selection(self, func) -> None:
        selected = self._get_selected_paths()
        if selected:
            func(selected)

    def _to_clipboard(self, op: str) -> None:
        selected = self._get_selected_paths()
        if selected:
            file_clipboard.set(selected, op)
            verb = "剪下" if op == "cut" else "複製"
            self.status_message.emit(f"已{verb} {len(selected)} 個項目")

    def _copy_files_to_clipboard(self, paths: list[str]) -> None:
        file_clipboard.set(paths, "copy")
        self.status_message.emit(f"已複製 {len(paths)} 個檔案到剪貼簿")

    def _paste(self) -> None:
        paths, op = file_clipboard.contents()
        dest = self.current_path()
        if not paths or not dest:
            return
        if op == "cut":
            self._move_to(paths, dest)
            file_clipboard.clear()
        else:
            self._copy_to(paths, dest)

    def _rename_selected(self) -> None:
        selected = self._get_selected_paths()
        if len(selected) == 1:
            self._rename(selected[0])
        elif len(selected) > 1:
            self._batch_rename()

    def _open_selected(self) -> None:
        rows = self._selected_rows()
        if len(rows) == 1:
            index = self.model.index(rows[0], 0)
            self._open_item(self.model.file_path(index), index)

    def _shortcut_refresh(self) -> None:
        self.model.refresh()
        self.status_message.emit("已重新整理")

    def _focus_breadcrumb_edit(self) -> None:
        edit = self.breadcrumb.line_edit()
        edit.setFocus()
        edit.selectAll()

    def _preview(self) -> None:
        """Space: QuickLook preview; explain where to get it when missing (E02)."""
        selected = self._get_selected_paths()
        if len(selected) != 1:
            return
        exe = _quicklook_exe()
        if not exe:
            self.status_message.emit(f"預覽需要免費工具 QuickLook，可到 {QUICKLOOK_URL} 下載安裝")
            return
        try:
            subprocess.Popen([exe, os.path.normpath(selected[0])])
        except OSError as e:
            self.status_message.emit(f"QuickLook 開啟失敗：{e}")

    def _select_same_type(self) -> None:
        """H07: select every visible item with the same extension as the selection."""
        entries = self.model.entries()
        rows = self._selected_rows()
        if not rows:
            return

        def kind(row: int) -> str:
            e = entries[row]
            return "<dir>" if e.is_dir else e.ext.lower()

        wanted = {kind(r) for r in rows}
        self._select_rows([r for r in self._visible_rows() if kind(r) in wanted])

    # --- Selection ---

    def _visible_rows(self) -> list[int]:
        return [r for r in range(self.model.rowCount()) if r not in self._hidden_rows]

    def _selected_rows(self) -> list[int]:
        """Selected rows in display order; rows hidden by the filter never count."""
        rows = {i.row() for i in self.tree.selectionModel().selectedIndexes()}
        return sorted(rows - self._hidden_rows)

    def _select_rows(self, rows: list[int]) -> None:
        selection = QItemSelection()
        last_col = self.model.columnCount() - 1
        rows = sorted(rows)
        start = 0
        while start < len(rows):  # one range per run of consecutive rows
            end = start
            while end + 1 < len(rows) and rows[end + 1] == rows[end] + 1:
                end += 1
            selection.select(
                self.model.index(rows[start], 0), self.model.index(rows[end], last_col)
            )
            start = end + 1
        flags = QItemSelectionModel.SelectionFlag.ClearAndSelect
        self.tree.selectionModel().select(selection, flags)
        if rows:
            current = self.model.index(rows[0], 0)
            self.tree.selectionModel().setCurrentIndex(
                current, QItemSelectionModel.SelectionFlag.NoUpdate
            )
            self.view().scrollTo(current)

    def _get_selected_paths(self) -> list[str]:
        entries = self.model.entries()
        return [entries[r].path for r in self._selected_rows()]

    def selected_link_target(self) -> str:
        """G01: where the single selected junction / symlink / shortcut points."""
        selected = self._get_selected_paths()
        if len(selected) != 1:
            return ""
        path = selected[0]
        if path.lower().endswith(".lnk"):
            target = _resolve_lnk_target(path)
            return "" if target == path else target
        return link_target(path) or ""

    def get_file_count(self) -> int:
        return self.model.rowCount() - len(self._hidden_rows)

    def get_selected_count(self) -> int:
        return len(self._selected_rows())

    def get_selected_total_size(self) -> int:
        entries = self.model.entries()
        return sum(entries[r].size for r in self._selected_rows() if not entries[r].is_dir)

    # --- Filter (D02, D06) and searches (D01, D04, D05) ---

    def _apply_filter(self, matcher) -> None:
        self._matcher = matcher
        hidden: set[int] = set()
        if matcher is not None:
            hidden = {r for r, e in enumerate(self.model.entries()) if not matcher(e.name)}
        for row in hidden ^ self._hidden_rows:
            self.tree.setRowHidden(row, QModelIndex(), row in hidden)
            self.icons.setRowHidden(row, row in hidden)
        self._hidden_rows = hidden
        total = self.model.rowCount()
        self.search_bar.set_count(total - len(hidden), total)
        self.selection_changed.emit(self.panel_id)

    def _on_model_reset(self) -> None:
        # A reset clears the views' hidden rows; apply the filter to the new rows.
        self._hidden_rows = set()
        self._apply_filter(self._matcher)

    def _sync_hidden_rows(self) -> None:
        # After sorting the views keep hiding the same items, now at other rows.
        self._hidden_rows = {
            r for r in range(self.model.rowCount()) if self.tree.isRowHidden(r, QModelIndex())
        }

    def _open_search(self, mode: str, text: str, regex: bool) -> None:
        root = self.current_path()
        if mode != "everything" and not root:
            return
        es_path = self.prefs.get("everything_path", "")
        SearchResultsDialog(self, mode, root, text, regex, es_path).show()

    # --- Loading (J03, J06) ---

    def _on_scan_progress(self, count: int) -> None:
        self.status_message.emit(f"面板 {self.panel_id + 1} 正在載入… 已讀取 {count} 項")

    def _on_scan_finished(self) -> None:
        if self._pending_select:
            path, self._pending_select = self._pending_select, ""
            self._select_path(path)
        self.selection_changed.emit(self.panel_id)

    def _on_root_missing(self, path: str) -> None:
        # Let the current signal finish before navigating away.
        QTimer.singleShot(0, lambda: self._recover_missing(path))

    def _recover_missing(self, path: str) -> None:
        if self.current_path() != path or os.path.isdir(path):
            return
        target = self.open_nearest(path)
        self.status_message.emit(
            f"面板 {self.panel_id + 1} 的資料夾已無法存取（{path}），已改顯示 {target}"
        )

    def open_nearest(self, path: str) -> str:
        """Open `path`, or its closest existing parent, or the home folder."""
        p = os.path.normpath(path) if path else ""
        while p and not os.path.isdir(p):
            parent = os.path.dirname(p)
            p = "" if parent == p else parent
        target = p or os.path.expanduser("~")
        self.navigate_to(target)
        return target

    def reveal(self, path: str) -> None:
        """Show the folder that contains `path` and select it."""
        folder = os.path.normcase(os.path.dirname(os.path.normpath(path)))
        if folder == os.path.normcase(self.current_path()):
            if self.model.is_loading():
                self._pending_select = path
            else:
                self._select_path(path)
            return
        self._pending_select = path
        self.navigate_to(os.path.dirname(os.path.normpath(path)))

    def _select_path(self, path: str) -> None:
        key = os.path.normcase(os.path.normpath(path))
        for row, e in enumerate(self.model.entries()):
            if os.path.normcase(os.path.normpath(e.path)) == key:
                if row in self._hidden_rows:
                    self.search_bar._close()
                self._select_rows([row])
                self.view().setFocus()
                return

    # --- Navigation ---

    def _refresh(self) -> None:
        self.model.refresh()

    def navigate_to(self, path: str) -> None:
        if not os.path.isdir(path):
            return
        path = os.path.normpath(path)
        self._rename_timer.stop()
        self._rename_pending_path = None
        if self.search_bar.isVisible() and os.path.normcase(path) != os.path.normcase(
            self.current_path()
        ):
            self.search_bar._close()
        self.tree._fallback_dir = path
        self.icons._fallback_dir = path
        self.model.set_root_path(path)
        self.breadcrumb.set_path(path)
        self.selection_changed.emit(self.panel_id)
        self.path_changed.emit(self.panel_id)

        if not self._navigating_history:
            if self._history_index < len(self._history) - 1:
                self._history = self._history[: self._history_index + 1]
            if not self._history or self._history[-1] != path:
                self._history.append(path)
                self._history_index = len(self._history) - 1
        self._update_nav_buttons()

    def current_path(self) -> str:
        return self.model.root_path()

    def _on_click(self) -> None:
        self.activated.emit(self.panel_id)
        self.selection_changed.emit(self.panel_id)

        selected = self._get_selected_paths()
        if len(selected) != 1:
            # Multi-select or no selection: cancel any pending rename
            self._rename_timer.stop()
            self._rename_pending_path = None
            return

        path = selected[0]
        if self._rename_pending_path == path:
            # Second click on the same already-selected item: arm rename timer
            # (the delay lets a double-click cancel it)
            self._rename_timer.start()
        else:
            self._rename_timer.stop()
            self._rename_pending_path = path

    def _cancel_pending_rename(self) -> None:
        self._rename_timer.stop()
        self._rename_pending_path = None

    def _on_rename_timer(self) -> None:
        path = self._rename_pending_path
        self._rename_pending_path = None
        # Something else started after the click (delete confirmation, context
        # menu, keyboard selection change): don't stack a rename dialog on it.
        if QApplication.activeModalWidget() or QApplication.activePopupWidget():
            return
        if self._get_selected_paths() != [path]:
            return
        if path and os.path.lexists(path):
            self._rename(path)

    def _go_back(self) -> None:
        if self._history_index > 0:
            self._history_index -= 1
            self._navigating_history = True
            self.navigate_to(self._history[self._history_index])
            self._navigating_history = False
        self.activated.emit(self.panel_id)

    def _go_forward(self) -> None:
        if self._history_index < len(self._history) - 1:
            self._history_index += 1
            self._navigating_history = True
            self.navigate_to(self._history[self._history_index])
            self._navigating_history = False
        self.activated.emit(self.panel_id)

    def _update_nav_buttons(self) -> None:
        self.btn_back.setEnabled(self._history_index > 0)
        self.btn_forward.setEnabled(self._history_index < len(self._history) - 1)

    def _go_up(self) -> None:
        current = self.current_path()
        parent = os.path.dirname(current)
        if parent and parent != current:
            self.navigate_to(parent)
        self.activated.emit(self.panel_id)

    def _open_item(self, path: str, index: QModelIndex) -> None:
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
                self._shell_open(path)
        else:
            self._shell_open(path)

    def _shell_open(self, path: str) -> None:
        """Open a file via ShellExecuteExW so SmartScreen / UAC prompts appear."""
        sei = _SHELLEXECUTEINFO()
        sei.cbSize = ctypes.sizeof(sei)
        sei.fMask = 0x00000040  # SEE_MASK_NOCLOSEPROCESS
        sei.hwnd = int(self.window().winId())
        sei.lpVerb = "open"
        sei.lpFile = os.path.normpath(path)
        sei.lpDirectory = os.path.dirname(os.path.normpath(path))
        sei.nShow = 1  # SW_SHOWNORMAL
        # use_last_error so get_last_error() reliably reflects ShellExecuteExW.
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        if not shell32.ShellExecuteExW(ctypes.byref(sei)):
            err = ctypes.get_last_error()
            name = os.path.basename(path)
            if err == 1223:  # ERROR_CANCELLED: the user dismissed the UAC / SmartScreen prompt
                self.status_message.emit(f"已取消開啟：{name}")
            else:
                self.status_message.emit(f"開啟失敗（錯誤碼 {err}）：{name}")

    def _on_double_click(self, index: QModelIndex) -> None:
        self._rename_timer.stop()
        self._rename_pending_path = None
        self._open_item(self.model.file_path(index), index)
        self.activated.emit(self.panel_id)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        self.activated.emit(self.panel_id)
