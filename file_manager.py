"""Main window: tree panel + up to 4 file panels, menus, shortcuts and settings."""

import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QGuiApplication, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QStatusBar,
)

from app_dialogs import AboutDialog, CommandPalette, ShortcutListDialog
from panels import FilePanel
from search_utils import search_history
from settings import load_settings, save_settings
from settings_dialog import SettingsDialog
from shortcuts import ACTIONS, action, key_for
from theme import build_palette, build_stylesheet
from transfer_ui import OperationQueue, QueueWindow, format_bytes
from tree_panel import TreePanel
from undo import undo_stack

# A13: which panels each layout shows.
LAYOUTS = {
    "1": ("單一面板", (0,)),
    "2h": ("左右兩欄", (0, 1)),
    "2v": ("上下兩列", (0, 2)),
    "3": ("三面板", (0, 1, 2)),
    "4": ("四面板", (0, 1, 2, 3)),
}


class FileManagerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CatFileManager")
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self.settings = load_settings()
        self.prefs = self.settings["prefs"]
        self.active_panel_id = self.settings.get("active_panel", 0)
        self._save_warned = False

        self.queue = OperationQueue(self)
        self.queue_window = QueueWindow(self.queue, self)

        self._build_ui()
        self._build_menus()
        self._build_shortcuts()
        self._apply_prefs(self.prefs)
        self._restore_state()

        search_history.load(self.prefs.get("search_history", []))
        search_history.changed.connect(self._on_search_history_changed)
        QGuiApplication.styleHints().colorSchemeChanged.connect(self._on_system_theme_changed)

    # --- UI ---

    def _build_ui(self):
        self.tree_panel = TreePanel()
        self.tree_panel.path_selected.connect(self._on_tree_path_selected)
        self.tree_panel.favorites_changed.connect(self._on_favorites_changed)
        self.tree_panel.status_message.connect(self._show_status)

        self.panels: list[FilePanel] = []
        for i in range(4):
            panel = FilePanel(i, self.queue)
            panel.activated.connect(self._set_active_panel)
            panel.status_message.connect(self._show_status)
            panel.selection_changed.connect(self._update_status_bar)
            panel.add_to_favorites.connect(self._add_to_favorites)
            panel.path_changed.connect(self._schedule_auto_save)
            self.panels.append(panel)
        for panel in self.panels:
            panel.other_panels = [p for p in self.panels if p is not panel]

        # Debounce timer for auto-saving state (avoids excessive writes)
        self._auto_save_timer = QTimer(self)
        self._auto_save_timer.setSingleShot(True)
        self._auto_save_timer.setInterval(1000)
        self._auto_save_timer.timeout.connect(self._save_state)

        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.addWidget(self.tree_panel)
        self.vert_splitter = QSplitter(Qt.Orientation.Vertical)
        self.top_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.top_splitter.addWidget(self.panels[0])
        self.top_splitter.addWidget(self.panels[1])
        self.bottom_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.bottom_splitter.addWidget(self.panels[2])
        self.bottom_splitter.addWidget(self.panels[3])
        self.vert_splitter.addWidget(self.top_splitter)
        self.vert_splitter.addWidget(self.bottom_splitter)
        self.main_splitter.addWidget(self.vert_splitter)
        self.setCentralWidget(self.main_splitter)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_panel_label = QLabel("面板 1")
        self.status_items_label = QLabel("")
        self.status_selected_label = QLabel("")
        self.status_link_label = QLabel("")  # G01
        self.status_link_label.setObjectName("dimText")
        self.status_path_label = QLabel("")
        self.status_author_label = QLabel("製作者：黃政文")
        self.status_author_label.setObjectName("dimText")
        self.status_bar.addWidget(self.status_panel_label)
        self.status_bar.addWidget(self.status_items_label, 1)
        self.status_bar.addWidget(self.status_selected_label, 1)
        self.status_bar.addWidget(self.status_link_label, 2)
        self.status_bar.addPermanentWidget(self.status_path_label)
        self.status_bar.addPermanentWidget(self.status_author_label)

    def _menu_action(self, menu, action_id: str, label: str = "") -> QAction:
        """Menu entry that runs a registry action; shows the key without binding it.

        Keys are bound by QShortcut objects (panel / window), so menu actions
        must not register the same key a second time (Qt would report it as
        ambiguous and run neither).
        """
        act = QAction(label or action(action_id).label, self)
        act.triggered.connect(lambda checked=False: self.run_action(action_id))
        menu.addAction(act)
        self._menu_actions[action_id] = act
        return act

    def _build_menus(self):
        self._menu_actions: dict[str, QAction] = {}
        bar = self.menuBar()

        m = bar.addMenu("檔案(&F)")
        for aid in ("new_folder", "new_textfile", "open_cmd", "open_powershell", "open_terminal"):
            self._menu_action(m, aid)
        m.addSeparator()
        self._menu_action(m, "settings", "設定…")
        m.addSeparator()
        m.addAction("結束", self.close)

        m = bar.addMenu("編輯(&E)")
        for aid in ("undo", None, "cut", "copy", "paste", None, "rename", "delete"):
            if aid is None:
                m.addSeparator()
            else:
                self._menu_action(m, aid)
        self._menu_action(m, "delete_permanent")
        m.addSeparator()
        for aid in ("copy_path", "select_all", "select_same_type"):
            self._menu_action(m, aid)
        m.aboutToShow.connect(self._update_undo_label)

        m = bar.addMenu("檢視(&V)")
        layout_menu = m.addMenu("面板版面")
        self._layout_group = QActionGroup(self)
        self._layout_actions: dict[str, QAction] = {}
        for key, (label, _) in LAYOUTS.items():
            act = QAction(label, self, checkable=True)
            act.triggered.connect(lambda checked=False, k=key: self._set_layout(k))
            self._layout_group.addAction(act)
            layout_menu.addAction(act)
            self._layout_actions[key] = act
        m.addSeparator()
        self._menu_action(m, "view_details")
        self._menu_action(m, "view_icons")
        m.addSeparator()
        self._menu_action(m, "toggle_hidden", "顯示隱藏檔").setCheckable(True)
        self._menu_action(m, "toggle_extensions", "顯示副檔名").setCheckable(True)
        m.addSeparator()
        m.addAction("檔案操作視窗", self.queue_window.show)

        m = bar.addMenu("搜尋(&S)")
        self._menu_action(m, "search")
        self._menu_action(m, "search_recursive")
        m.addSeparator()
        self._menu_action(m, "command_palette", "命令面板…")

        m = bar.addMenu("說明(&H)")
        self._menu_action(m, "shortcut_list")
        self._menu_action(m, "about")

    def _build_shortcuts(self):
        self._window_shortcuts: dict[str, QShortcut] = {}
        for a in ACTIONS:
            if a.scope == "window":
                sc = QShortcut(self)
                sc.setContext(Qt.ShortcutContext.WindowShortcut)
                sc.activated.connect(lambda aid=a.id: self.run_action(aid))
                self._window_shortcuts[a.id] = sc

    def _apply_shortcut_keys(self):
        overrides = self.prefs.get("shortcuts", {})
        for aid, sc in self._window_shortcuts.items():
            sc.setKey(QKeySequence(key_for(aid, overrides)))
        for aid, act in self._menu_actions.items():
            key = key_for(aid, overrides)
            base = act.text().split("\t")[0]
            native = QKeySequence(key).toString(QKeySequence.SequenceFormat.NativeText)
            act.setText(f"{base}\t{native}" if key else base)

    # --- Preferences ---

    def _apply_prefs(self, prefs: dict):
        self.prefs = prefs
        self.settings["prefs"] = prefs
        app = QApplication.instance()
        app.setPalette(build_palette(prefs["theme"]))
        app.setStyleSheet(
            build_stylesheet(prefs["theme"], prefs["font_family"], prefs["font_size"])
        )
        for panel in self.panels:
            panel.apply_prefs(prefs)
        self._apply_shortcut_keys()
        self._menu_actions["toggle_hidden"].setChecked(prefs["show_hidden"])
        self._menu_actions["toggle_extensions"].setChecked(prefs["show_extensions"])
        self._set_layout(prefs.get("layout", "4"), save=False)

    def _update_prefs(self, **changes):
        self._apply_prefs({**self.prefs, **changes})
        self._schedule_auto_save()

    def _on_system_theme_changed(self, _scheme=None):
        if self.prefs["theme"] == "system":
            self._apply_prefs(self.prefs)

    def _on_search_history_changed(self, items: list):
        self.prefs["search_history"] = list(items)
        self._schedule_auto_save()

    def _open_settings(self):
        dlg = SettingsDialog(self.prefs, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._apply_prefs(dlg.prefs())
            self._save_state()

    # --- Layout (A13) ---

    def _visible_ids(self) -> tuple[int, ...]:
        return LAYOUTS.get(self.prefs.get("layout", "4"), LAYOUTS["4"])[1]

    def _set_layout(self, key: str, save: bool = True):
        if key not in LAYOUTS:
            key = "4"
        self.prefs["layout"] = key
        shown = LAYOUTS[key][1]
        for panel in self.panels:
            panel.setVisible(panel.panel_id in shown)
        self.top_splitter.setVisible(0 in shown or 1 in shown)
        self.bottom_splitter.setVisible(2 in shown or 3 in shown)
        self._layout_actions[key].setChecked(True)
        if self.active_panel_id not in shown:
            self._set_active_panel(shown[0])
        if save:
            self._schedule_auto_save()

    def _cycle_panel(self, step: int):
        ids = self._visible_ids()
        pos = ids.index(self.active_panel_id) if self.active_panel_id in ids else 0
        self._focus_panel(ids[(pos + step) % len(ids)])

    def _focus_panel(self, panel_id: int):
        if panel_id not in self._visible_ids():
            self._show_status(f"面板 {panel_id + 1} 在目前版面中沒有顯示")
            return
        self._set_active_panel(panel_id)
        self.panels[panel_id].view().setFocus()

    # --- Actions ---

    def run_action(self, action_id: str):
        a = action(action_id)
        if a.scope == "panel":
            self.panels[self.active_panel_id].run_action(action_id)
            return
        handlers = {
            "undo": self._undo,
            "next_panel": lambda: self._cycle_panel(1),
            "prev_panel": lambda: self._cycle_panel(-1),
            "panel_1": lambda: self._focus_panel(0),
            "panel_2": lambda: self._focus_panel(1),
            "panel_3": lambda: self._focus_panel(2),
            "panel_4": lambda: self._focus_panel(3),
            "toggle_hidden": lambda: self._update_prefs(show_hidden=not self.prefs["show_hidden"]),
            "toggle_extensions": lambda: self._update_prefs(
                show_extensions=not self.prefs["show_extensions"]
            ),
            "command_palette": self._open_command_palette,
            "shortcut_list": lambda: ShortcutListDialog(
                self.prefs.get("shortcuts", {}), self
            ).exec(),
            "settings": self._open_settings,
            "about": lambda: AboutDialog(self).exec(),
        }
        handler = handlers.get(action_id)
        if handler:
            handler()

    def _open_command_palette(self):
        palette = CommandPalette(self.prefs.get("shortcuts", {}), self)
        if palette.exec() == QDialog.DialogCode.Accepted and palette.chosen():
            # Run after the palette has closed so focus is back on the panel.
            chosen = palette.chosen()
            QTimer.singleShot(0, lambda: self.run_action(chosen))

    def _update_undo_label(self):
        label = undo_stack.peek_label()
        act = self._menu_actions["undo"]
        key = act.text().split("\t", 1)[1] if "\t" in act.text() else ""
        text = f"復原：{label}" if label else "復原（沒有可復原的操作）"
        act.setText(f"{text}\t{key}" if key else text)
        act.setEnabled(bool(label))

    def _undo(self):
        if self.queue.is_busy():
            self._show_status("檔案操作進行中，完成後才能復原")
            return
        result = undo_stack.undo()
        if result is None:
            self._show_status("沒有可復原的操作")
            return
        label, errors = result
        for panel in self.panels:
            panel._refresh()
        if errors:
            self._show_status(f"復原「{label}」時有 {len(errors)} 個錯誤：{errors[0]}")
        else:
            self._show_status(f"已復原：{label}")

    # --- State ---

    def _restore_state(self):
        s = self.settings
        w = s.get("window", {})
        self.setGeometry(
            w.get("x", 100), w.get("y", 100), w.get("width", 1400), w.get("height", 800)
        )

        # I03: last-used folders, or the fixed folders chosen in settings
        last = s.get("panels", {})
        fixed = self.prefs.get("startup_paths", [])
        use_fixed = self.prefs.get("startup_mode") == "fixed"
        views = s.get("panel_views", {})
        for i, panel in enumerate(self.panels):
            path = fixed[i] if use_fixed and i < len(fixed) and fixed[i] else last.get(str(i), "")
            panel.open_nearest(path)  # J06: missing drive -> nearest existing folder
            if isinstance(views.get(str(i)), dict):
                panel.restore_view_state(views[str(i)])

        for key, splitter in (
            ("splitter_vertical", self.vert_splitter),
            ("splitter_top", self.top_splitter),
            ("splitter_bottom", self.bottom_splitter),
            ("splitter_tree", self.tree_panel.splitter),
        ):
            if s.get(key):
                splitter.setSizes(s[key])
        self.main_splitter.setSizes(s.get("splitter_main") or [250, 1150])

        self.tree_panel.favorites.load_favorites(s.get("favorites", []))
        self._set_active_panel(self.active_panel_id)

    def _schedule_auto_save(self, _panel_id: int = 0):
        """Restart the debounce timer so state is saved 1s after the last change."""
        self._auto_save_timer.start()

    def _save_state(self):
        geo = self.geometry()
        self.settings["window"] = {
            "x": geo.x(),
            "y": geo.y(),
            "width": geo.width(),
            "height": geo.height(),
        }
        self.settings["panels"] = {str(p.panel_id): p.current_path() for p in self.panels}
        self.settings["panel_views"] = {str(p.panel_id): p.view_state() for p in self.panels}
        self.settings["splitter_main"] = self.main_splitter.sizes()
        self.settings["splitter_vertical"] = self.vert_splitter.sizes()
        self.settings["splitter_top"] = self.top_splitter.sizes()
        self.settings["splitter_bottom"] = self.bottom_splitter.sizes()
        self.settings["splitter_tree"] = self.tree_panel.splitter.sizes()
        self.settings["active_panel"] = self.active_panel_id
        self.settings["favorites"] = self.tree_panel.favorites.get_favorites()
        self.settings["prefs"] = self.prefs
        self._write_settings()

    def _write_settings(self):
        """J04: tell the user (once per session) when settings can't be saved."""
        error = save_settings(self.settings)
        if error is None:
            self._save_warned = False
            return
        self._show_status(f"設定儲存失敗：{error}")
        if not self._save_warned:
            self._save_warned = True
            QMessageBox.warning(
                self,
                "設定儲存失敗",
                f"無法儲存設定，關閉程式後這次的變更會遺失。\n\n{error}",
            )

    def _on_favorites_changed(self, favorites: list):
        self.settings["favorites"] = favorites
        self._write_settings()

    def _add_to_favorites(self, path: str):
        self.tree_panel.favorites.add_favorite(path)
        self._show_status(f"已加入我的最愛：{os.path.basename(path) or path}")

    def _set_active_panel(self, panel_id: int):
        self.active_panel_id = panel_id
        for panel in self.panels:
            panel.set_active(panel.panel_id == panel_id)
        self._update_status_bar(panel_id)

    def _update_status_bar(self, panel_id: int):
        if panel_id != self.active_panel_id:
            return
        panel = self.panels[panel_id]
        selected = panel.get_selected_count()
        self.status_panel_label.setText(f"  面板 {panel_id + 1}  ")
        self.status_items_label.setText(f"  {panel.get_file_count()} 個項目  ")
        if selected > 0:
            size = format_bytes(panel.get_selected_total_size())
            self.status_selected_label.setText(f"  已選取 {selected} 個項目 ({size})  ")
        else:
            self.status_selected_label.setText("")
        target = panel.selected_link_target()
        self.status_link_label.setText(f"  連結目標：{target}" if target else "")
        current_path = panel.current_path()
        display_path = "..." + current_path[-57:] if len(current_path) > 60 else current_path
        self.status_path_label.setText(f"  {display_path}  ")

    def _on_tree_path_selected(self, path: str):
        self.panels[self.active_panel_id].navigate_to(path)

    def _show_status(self, message: str):
        self.status_bar.showMessage(message, 5000)

    def closeEvent(self, event):
        if self.queue.is_busy():
            reply = QMessageBox.question(
                self,
                "檔案操作進行中",
                "還有檔案操作沒有完成，關閉會中斷它。確定要關閉嗎？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self.queue.shutdown()
        self._save_state()
        super().closeEvent(event)
