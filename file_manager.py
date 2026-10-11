"""Main window — assembles tree panel + 4 file panels."""

import os

from PySide6.QtWidgets import QMainWindow, QSplitter, QStatusBar, QLabel
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon

from tree_panel import TreePanel
from panels import FilePanel
from settings import load_settings, save_settings
from theme import DARK_THEME


def _format_size(size_bytes: int) -> str:
    """Format byte size to human readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


class FileManagerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CatFileManager")
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self.setStyleSheet(DARK_THEME)

        self.settings = load_settings()
        self.active_panel_id = self.settings.get("active_panel", 0)

        self._build_ui()
        self._restore_state()

    def _build_ui(self):
        # Tree panel (left)
        self.tree_panel = TreePanel()
        self.tree_panel.path_selected.connect(self._on_tree_path_selected)
        self.tree_panel.favorites_changed.connect(self._on_favorites_changed)
        self.tree_panel.status_message.connect(self._show_status)

        # 4 file panels
        self.panels: list[FilePanel] = []
        for i in range(4):
            panel = FilePanel(i)
            panel.activated.connect(self._set_active_panel)
            panel.status_message.connect(self._show_status)
            panel.selection_changed.connect(self._update_status_bar)
            panel.add_to_favorites.connect(self._add_to_favorites)
            self.panels.append(panel)

        # Wire up cross-panel references and auto-save on navigation
        for panel in self.panels:
            panel.other_panels = [p for p in self.panels if p.panel_id != panel.panel_id]
            panel.path_changed.connect(self._schedule_auto_save)

        # Debounce timer for auto-saving state (avoids excessive writes)
        self._auto_save_timer = QTimer()
        self._auto_save_timer.setSingleShot(True)
        self._auto_save_timer.setInterval(1000)
        self._auto_save_timer.timeout.connect(self._save_state)

        # Layout: main splitter (tree | panels_area)
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)

        # Tree on the left
        self.main_splitter.addWidget(self.tree_panel)

        # Panels area: vertical splitter (top_row | bottom_row)
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

        # Status bar with multiple sections
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        self.status_panel_label = QLabel("\u9762\u677f 1")
        self.status_items_label = QLabel("")
        self.status_selected_label = QLabel("")
        self.status_path_label = QLabel("")
        self.status_author_label = QLabel("\u88fd\u4f5c\u8005\uff1a\u9ec3\u653f\u6587")

        self.status_bar.addWidget(self.status_panel_label)
        self.status_bar.addWidget(self.status_items_label, 1)
        self.status_bar.addWidget(self.status_selected_label, 1)
        self.status_bar.addPermanentWidget(self.status_path_label)
        self.status_bar.addPermanentWidget(self.status_author_label)

        # Set initial active panel
        self._set_active_panel(self.active_panel_id)

    def _restore_state(self):
        s = self.settings

        # Window geometry
        w = s.get("window", {})
        self.setGeometry(w.get("x", 100), w.get("y", 100),
                         w.get("width", 1400), w.get("height", 800))

        # Panel paths
        panels_cfg = s.get("panels", {})
        for i, panel in enumerate(self.panels):
            path = panels_cfg.get(str(i), "")
            if path:
                panel.navigate_to(path)

        # Splitter sizes
        if s.get("splitter_main"):
            self.main_splitter.setSizes(s["splitter_main"])
        else:
            self.main_splitter.setSizes([250, 1150])

        if s.get("splitter_vertical"):
            self.vert_splitter.setSizes(s["splitter_vertical"])

        if s.get("splitter_top"):
            self.top_splitter.setSizes(s["splitter_top"])

        if s.get("splitter_bottom"):
            self.bottom_splitter.setSizes(s["splitter_bottom"])

        if s.get("splitter_tree"):
            self.tree_panel.splitter.setSizes(s["splitter_tree"])

        # Favorites
        self.tree_panel.favorites.load_favorites(s.get("favorites", []))

        # Initial status bar
        self._update_status_bar(self.active_panel_id)

    def _schedule_auto_save(self, _panel_id: int = 0):
        """Restart the debounce timer so state is saved 1s after last navigation."""
        self._auto_save_timer.start()

    def _save_state(self):
        geo = self.geometry()
        self.settings["window"] = {
            "x": geo.x(),
            "y": geo.y(),
            "width": geo.width(),
            "height": geo.height(),
        }
        self.settings["panels"] = {
            str(i): panel.current_path() for i, panel in enumerate(self.panels)
        }
        self.settings["splitter_main"] = self.main_splitter.sizes()
        self.settings["splitter_vertical"] = self.vert_splitter.sizes()
        self.settings["splitter_top"] = self.top_splitter.sizes()
        self.settings["splitter_bottom"] = self.bottom_splitter.sizes()
        self.settings["splitter_tree"] = self.tree_panel.splitter.sizes()
        self.settings["active_panel"] = self.active_panel_id
        self.settings["favorites"] = self.tree_panel.favorites.get_favorites()
        save_settings(self.settings)

    def _on_favorites_changed(self, favorites: list):
        """Save favorites immediately when changed."""
        self.settings["favorites"] = favorites
        save_settings(self.settings)

    def _add_to_favorites(self, path: str):
        """Add a folder to favorites from panel right-click."""
        self.tree_panel.favorites.add_favorite(path)
        self._show_status(f"\u5df2\u52a0\u5165\u6211\u7684\u6700\u611b\uff1a{os.path.basename(path) or path}")

    def _set_active_panel(self, panel_id: int):
        self.active_panel_id = panel_id
        for panel in self.panels:
            panel.set_active(panel.panel_id == panel_id)
        self._update_status_bar(panel_id)

    def _update_status_bar(self, panel_id: int):
        """Update status bar with current panel info (like Q-Dir)."""
        panel = self.panels[panel_id]
        total = panel.get_file_count()
        selected = panel.get_selected_count()
        current_path = panel.current_path()

        self.status_panel_label.setText(f"  \u9762\u677f {panel_id + 1}  ")

        self.status_items_label.setText(f"  {total} \u500b\u9805\u76ee  ")

        if selected > 0:
            size = panel.get_selected_total_size()
            size_str = _format_size(size)
            self.status_selected_label.setText(
                f"  \u5df2\u9078\u53d6 {selected} \u500b\u9805\u76ee ({size_str})  "
            )
        else:
            self.status_selected_label.setText("")

        # Show abbreviated path
        if len(current_path) > 60:
            display_path = "..." + current_path[-57:]
        else:
            display_path = current_path
        self.status_path_label.setText(f"  {display_path}  ")

    def _on_tree_path_selected(self, path: str):
        self.panels[self.active_panel_id].navigate_to(path)

    def _show_status(self, message: str):
        self.status_bar.showMessage(message, 5000)

    def closeEvent(self, event):
        self._save_state()
        super().closeEvent(event)
