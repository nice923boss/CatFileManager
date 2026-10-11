"""Left-side shared directory tree panel with favorites."""

import os
import subprocess
import ctypes

from PySide6.QtWidgets import (
    QTreeView, QVBoxLayout, QWidget, QLabel, QFileSystemModel,
    QListWidget, QListWidgetItem, QMenu, QSplitter, QInputDialog,
    QMessageBox,
)
from PySide6.QtCore import Signal, QDir, Qt
from PySide6.QtGui import QAction

from link_icon import LinkAwareIconProvider


class FavoritesWidget(QWidget):
    """Customizable quick-access favorites list."""

    path_selected = Signal(str)
    favorites_changed = Signal(list)  # emits updated list for saving

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QLabel("  \u2605 \u6211\u7684\u6700\u611b")
        header.setStyleSheet(
            "background-color: #2d2d2d; color: #e8b84b; "
            "padding: 6px 4px; font-size: 13px; font-weight: bold;"
        )
        layout.addWidget(header)

        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet("QListWidget { font-size: 14px; } QListWidget::item { padding: 4px 2px; }")
        self.list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._show_context_menu)
        self.list_widget.itemClicked.connect(self._on_item_clicked)
        self.list_widget.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.list_widget.model().rowsMoved.connect(self._on_reorder)

        layout.addWidget(self.list_widget)

        self._favorites: list[dict] = []  # [{"name": "...", "path": "..."}]

    def load_favorites(self, favorites: list):
        """Load favorites from settings."""
        self._favorites = []
        self.list_widget.clear()
        for fav in favorites:
            if isinstance(fav, dict) and "path" in fav:
                name = fav.get("name", os.path.basename(fav["path"]) or fav["path"])
                self._favorites.append({"name": name, "path": fav["path"]})
                item = QListWidgetItem(f"  \u2606 {name}")
                item.setToolTip(fav["path"])
                self.list_widget.addItem(item)
            elif isinstance(fav, str):
                name = os.path.basename(fav) or fav
                self._favorites.append({"name": name, "path": fav})
                item = QListWidgetItem(f"  \u2606 {name}")
                item.setToolTip(fav)
                self.list_widget.addItem(item)

    def get_favorites(self) -> list[dict]:
        """Return current favorites list for saving."""
        # Rebuild from widget order (supports drag reorder)
        result = []
        for i in range(self.list_widget.count()):
            if i < len(self._favorites):
                result.append(self._favorites[i])
        return result

    def add_favorite(self, path: str, name: str = ""):
        """Add a path to favorites."""
        # Check for duplicates
        for fav in self._favorites:
            if os.path.normpath(fav["path"]) == os.path.normpath(path):
                return  # already exists

        if not name:
            name = os.path.basename(path) or path
        entry = {"name": name, "path": path}
        self._favorites.append(entry)
        item = QListWidgetItem(f"  \u2606 {name}")
        item.setToolTip(path)
        self.list_widget.addItem(item)
        self.favorites_changed.emit(self.get_favorites())

    def _on_item_clicked(self, item: QListWidgetItem):
        idx = self.list_widget.row(item)
        if 0 <= idx < len(self._favorites):
            path = self._favorites[idx]["path"]
            if os.path.isdir(path):
                self.path_selected.emit(path)

    def _on_reorder(self):
        # Rebuild _favorites list to match new widget order
        new_favs = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            tooltip = item.toolTip()
            # Find matching favorite
            for fav in self._favorites:
                if fav["path"] == tooltip:
                    new_favs.append(fav)
                    break
        self._favorites = new_favs
        self.favorites_changed.emit(self.get_favorites())

    def _show_context_menu(self, pos):
        item = self.list_widget.itemAt(pos)
        menu = QMenu(self)

        if item:
            idx = self.list_widget.row(item)

            act_rename = QAction("\u91cd\u65b0\u547d\u540d", self)
            act_rename.triggered.connect(lambda: self._rename_favorite(idx))
            menu.addAction(act_rename)

            act_remove = QAction("\u79fb\u9664", self)
            act_remove.triggered.connect(lambda: self._remove_favorite(idx))
            menu.addAction(act_remove)

            menu.addSeparator()

        act_add = QAction("\u65b0\u589e\u8cc7\u6599\u593e...", self)
        act_add.triggered.connect(self._add_favorite_dialog)
        menu.addAction(act_add)

        menu.exec(self.list_widget.viewport().mapToGlobal(pos))

    def _rename_favorite(self, idx: int):
        if 0 <= idx < len(self._favorites):
            old_name = self._favorites[idx]["name"]
            new_name, ok = QInputDialog.getText(
                self, "\u91cd\u65b0\u547d\u540d", "\u65b0\u540d\u7a31\uff1a", text=old_name
            )
            if ok and new_name:
                self._favorites[idx]["name"] = new_name
                self.list_widget.item(idx).setText(f"  \u2606 {new_name}")
                self.favorites_changed.emit(self.get_favorites())

    def _remove_favorite(self, idx: int):
        if 0 <= idx < len(self._favorites):
            self._favorites.pop(idx)
            self.list_widget.takeItem(idx)
            self.favorites_changed.emit(self.get_favorites())

    def _add_favorite_dialog(self):
        from PySide6.QtWidgets import QFileDialog
        path = QFileDialog.getExistingDirectory(self, "\u9078\u64c7\u8cc7\u6599\u593e")
        if path:
            self.add_favorite(path)


class RecycleBinWidget(QWidget):
    """Recycle Bin entry with right-click to empty."""

    status_message = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.label = QLabel("  \ud83d\uddd1 \u8cc7\u6e90\u56de\u6536\u7b52")
        self.label.setStyleSheet(
            "background-color: #252526; color: #cccccc; "
            "padding: 8px 4px; font-size: 13px;"
        )
        self.label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.label.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.label.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.label)

        self.setFixedHeight(36)

    def _show_context_menu(self, pos):
        menu = QMenu(self)

        act_open = QAction("\u958b\u555f\u8cc7\u6e90\u56de\u6536\u7b52", self)
        act_open.triggered.connect(self._open_recycle_bin)
        menu.addAction(act_open)

        menu.addSeparator()

        act_empty = QAction("\u6e05\u7a7a\u8cc7\u6e90\u56de\u6536\u7b52", self)
        act_empty.triggered.connect(self._empty_recycle_bin)
        menu.addAction(act_empty)

        menu.exec(self.label.mapToGlobal(pos))

    def _open_recycle_bin(self):
        subprocess.Popen('explorer.exe shell:RecycleBinFolder', shell=True)

    def _empty_recycle_bin(self):
        reply = QMessageBox.question(
            self,
            "\u6e05\u7a7a\u8cc7\u6e90\u56de\u6536\u7b52",
            "\u78ba\u5b9a\u8981\u6e05\u7a7a\u8cc7\u6e90\u56de\u6536\u7b52\u55ce\uff1f\u6b64\u64cd\u4f5c\u7121\u6cd5\u5fa9\u539f\u3002",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                # SHEmptyRecycleBin flags: no confirmation(1) + no progress(2) + no sound(4)
                SHERB_NOCONFIRMATION = 0x00000001
                SHERB_NOPROGRESSUI = 0x00000002
                SHERB_NOSOUND = 0x00000004
                flags = SHERB_NOCONFIRMATION | SHERB_NOPROGRESSUI | SHERB_NOSOUND
                ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, flags)
                self.status_message.emit("\u8cc7\u6e90\u56de\u6536\u7b52\u5df2\u6e05\u7a7a")
            except Exception as e:
                self.status_message.emit(f"\u6e05\u7a7a\u5931\u6557\uff1a{e}")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._open_recycle_bin()
        super().mousePressEvent(event)


class TreePanel(QWidget):
    """Directory tree with favorites section above."""

    path_selected = Signal(str)
    favorites_changed = Signal(list)
    status_message = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Vertical splitter: favorites on top, tree on bottom
        self.splitter = QSplitter(Qt.Orientation.Vertical)

        # Favorites
        self.favorites = FavoritesWidget()
        self.favorites.path_selected.connect(self.path_selected.emit)
        self.favorites.favorites_changed.connect(self.favorites_changed.emit)
        self.splitter.addWidget(self.favorites)

        # Directory tree
        tree_container = QWidget()
        tree_layout = QVBoxLayout(tree_container)
        tree_layout.setContentsMargins(0, 0, 0, 0)
        tree_layout.setSpacing(0)

        header = QLabel("  \u76ee\u9304")
        header.setStyleSheet(
            "background-color: #2d2d2d; color: #cccccc; "
            "padding: 6px 4px; font-size: 13px; font-weight: bold;"
        )
        tree_layout.addWidget(header)

        self.tree = QTreeView()
        self.tree.setHeaderHidden(True)
        self.tree.setAnimated(True)
        self.tree.setIndentation(16)

        self.model = QFileSystemModel()
        self._icon_provider = LinkAwareIconProvider()  # keep a ref; model does not own it
        self.model.setIconProvider(self._icon_provider)
        self.model.setFilter(QDir.Filter.AllDirs | QDir.Filter.NoDotAndDotDot | QDir.Filter.Drives)
        self.model.setRootPath("")

        self.tree.setModel(self.model)
        for col in range(1, self.model.columnCount()):
            self.tree.hideColumn(col)

        self.tree.clicked.connect(self._on_clicked)
        tree_layout.addWidget(self.tree)

        self.splitter.addWidget(tree_container)
        self.splitter.setSizes([150, 500])

        layout.addWidget(self.splitter)

        # Recycle Bin at the bottom
        self.recycle_bin = RecycleBinWidget()
        self.recycle_bin.status_message.connect(self.status_message.emit)
        layout.addWidget(self.recycle_bin)

    def _on_clicked(self, index):
        path = self.model.filePath(index)
        if path:
            self.path_selected.emit(path)
