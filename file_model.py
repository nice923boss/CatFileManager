"""Custom file system model that correctly lists all files including .lnk shortcuts.

Qt's QFileSystemModel has a known bug where it treats .lnk files as symlinks
and silently drops them if the target resolution fails. This model uses
os.scandir() directly to avoid that issue.

Large directories are scanned in a background thread to prevent UI freezing.
"""

import ctypes
import os
import re
import time

from PySide6.QtCore import (
    QAbstractItemModel,
    QFileSystemWatcher,
    QMimeData,
    QModelIndex,
    Qt,
    QThread,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QFileIconProvider

from link_icon import with_link_overlay

_FILE_ATTRIBUTE_HIDDEN = 0x2
_FILE_ATTRIBUTE_SYSTEM = 0x4
_icon_provider = QFileIconProvider()

_NUM_RE = re.compile(r"(\d+)")


def _natural_key(name: str) -> list:
    """Build a human-friendly sort key so "2" comes before "10".

    Split the name into alternating text/number chunks ("01image" ->
    ["", 1, "image"]) and turn digit runs into ints. re.split with one
    capturing group always alternates text/number, so even indices stay str
    and odd indices stay int and the lists compare without type clashes.
    """
    return [int(chunk) if i & 1 else chunk for i, chunk in enumerate(_NUM_RE.split(name.lower()))]


def _format_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    elif size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    else:
        return f"{size / (1024 * 1024 * 1024):.2f} GB"


def _is_hidden(path: str) -> bool:
    try:
        attrs = ctypes.windll.kernel32.GetFileAttributesW(path)
        if attrs != -1 and (attrs & _FILE_ATTRIBUTE_HIDDEN or attrs & _FILE_ATTRIBUTE_SYSTEM):
            return True
    except (OSError, ValueError):
        pass
    return False


def _resolve_lnk_icon(lnk_path: str) -> QIcon | None:
    """Get the icon of the .lnk target using Windows Shell COM."""
    try:
        import win32com.client

        shell = win32com.client.Dispatch("WScript.Shell")
        sc = shell.CreateShortCut(lnk_path)
        target = sc.TargetPath
        if target and os.path.exists(target):
            from PySide6.QtCore import QFileInfo

            return _icon_provider.icon(QFileInfo(target))
        icon_loc = sc.IconLocation
        if icon_loc and "," in icon_loc:
            ico_path = icon_loc.rsplit(",", 1)[0].strip()
            if ico_path and os.path.exists(ico_path):
                from PySide6.QtCore import QFileInfo

                return _icon_provider.icon(QFileInfo(ico_path))
    except Exception:
        pass
    return None


class FileEntry:
    __slots__ = ("name", "path", "is_dir", "size", "modified", "ext", "is_link", "_icon")

    def __init__(
        self,
        name: str,
        path: str,
        is_dir: bool,
        size: int,
        modified: float,
        ext: str,
        is_link: bool = False,
    ):
        self.name = name
        self.path = path
        self.is_dir = is_dir
        self.size = size
        self.modified = modified
        self.ext = ext
        self.is_link = is_link  # NTFS junction or symlink
        self._icon: QIcon | None = None


class _ScanWorker(QThread):
    """Background thread for scanning directories."""

    done = Signal(list)  # list[FileEntry]

    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self._path = path

    def run(self):
        entries = []
        try:
            with os.scandir(self._path) as it:
                for entry in it:
                    try:
                        full_path = entry.path
                        if _is_hidden(full_path):
                            continue
                        name = entry.name
                        is_dir = entry.is_dir(follow_symlinks=False)
                        if name.lower().endswith(".lnk"):
                            is_dir = False
                        stat = entry.stat(follow_symlinks=False)
                        size = stat.st_size
                        modified = stat.st_mtime
                        ext = os.path.splitext(name)[1]
                        is_link = entry.is_junction() or entry.is_symlink()
                        entries.append(
                            FileEntry(name, full_path, is_dir, size, modified, ext, is_link)
                        )
                    except OSError:
                        continue
        except OSError:
            pass
        self.done.emit(entries)


class DirectoryModel(QAbstractItemModel):
    """A flat table model that lists files in a single directory.

    Uses os.scandir() in a background thread for large directories.
    """

    COLUMNS = ["Name", "Size", "Type", "Date Modified"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entries: list[FileEntry] = []
        self._root_path = ""
        self._sort_column = 0
        self._sort_order = Qt.SortOrder.AscendingOrder
        self._scan_worker: _ScanWorker | None = None
        self._icon_cache: dict[str, QIcon] = {}

        self._watcher = QFileSystemWatcher(self)
        self._watcher.directoryChanged.connect(self._on_dir_changed)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(300)
        self._refresh_timer.timeout.connect(self._reload)

    def root_path(self) -> str:
        return self._root_path

    def set_root_path(self, path: str):
        path = os.path.normpath(path)
        if path == self._root_path:
            return
        watched = self._watcher.directories()
        if watched:
            self._watcher.removePaths(watched)
        self._root_path = path
        if os.path.isdir(path):
            self._watcher.addPath(path)
        self._reload()

    def refresh(self):
        self._reload()

    def file_path(self, index: QModelIndex) -> str:
        if not index.isValid():
            return ""
        row = index.row()
        if 0 <= row < len(self._entries):
            return self._entries[row].path
        return ""

    def is_dir(self, index: QModelIndex) -> bool:
        if not index.isValid():
            return False
        row = index.row()
        if 0 <= row < len(self._entries):
            return self._entries[row].is_dir
        return False

    def file_name(self, index: QModelIndex) -> str:
        if not index.isValid():
            return ""
        row = index.row()
        if 0 <= row < len(self._entries):
            return self._entries[row].name
        return ""

    # --- QAbstractItemModel interface ---

    def rowCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return len(self._entries)

    def columnCount(self, parent=QModelIndex()):
        return len(self.COLUMNS)

    def index(self, row, column=0, parent=QModelIndex()):
        if parent.isValid() or row < 0 or row >= len(self._entries):
            return QModelIndex()
        return self.createIndex(row, column)

    def parent(self, index):
        return QModelIndex()

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row, col = index.row(), index.column()
        if row < 0 or row >= len(self._entries):
            return None
        entry = self._entries[row]

        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                if entry.name.lower().endswith(".lnk"):
                    return entry.name[:-4]
                return entry.name
            elif col == 1:
                if entry.is_dir:
                    return ""
                return _format_size(entry.size)
            elif col == 2:
                if entry.is_dir:
                    return "\u8cc7\u6599\u593e"
                if entry.name.lower().endswith(".lnk"):
                    return "\u6377\u5f91"
                return entry.ext.upper()[1:] if entry.ext else ""
            elif col == 3:
                try:
                    return time.strftime("%Y/%m/%d %H:%M", time.localtime(entry.modified))
                except (OSError, ValueError):
                    return ""
        elif role == Qt.ItemDataRole.DecorationRole and col == 0:
            return self._get_icon(entry)

        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            if 0 <= section < len(self.COLUMNS):
                return self.COLUMNS[section]
        return None

    def sort(self, column, order=Qt.SortOrder.AscendingOrder):
        self._sort_column = column
        self._sort_order = order
        self.beginResetModel()
        self._apply_sort()
        self.endResetModel()

    def flags(self, index):
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.isValid():
            base |= Qt.ItemFlag.ItemIsDragEnabled
        return base

    # --- Drag-and-drop MIME support ---

    def mimeTypes(self) -> list[str]:
        return ["text/uri-list"]

    def mimeData(self, indexes):
        mime = QMimeData()
        seen: set[str] = set()
        urls: list[QUrl] = []
        for idx in indexes:
            if idx.column() != 0:
                continue
            path = self.file_path(idx)
            if path:
                normalized = os.path.normpath(path)
                if normalized not in seen:
                    seen.add(normalized)
                    urls.append(QUrl.fromLocalFile(normalized))
        mime.setUrls(urls)
        return mime

    def supportedDragActions(self):
        return Qt.DropAction.CopyAction | Qt.DropAction.MoveAction

    # --- Internal ---

    def _get_icon(self, entry: FileEntry) -> QIcon:
        if entry._icon is not None:
            return entry._icon

        if entry.is_dir:
            icon = _icon_provider.icon(QFileIconProvider.IconType.Folder)
        elif entry.name.lower().endswith(".lnk"):
            # Try to get icon from shortcut target
            cached = self._icon_cache.get(entry.path)
            if cached is not None:
                entry._icon = cached
                return cached
            icon = _resolve_lnk_icon(entry.path)
            if icon is None:
                icon = _icon_provider.icon(QFileIconProvider.IconType.File)
            self._icon_cache[entry.path] = icon
        else:
            from PySide6.QtCore import QFileInfo

            icon = _icon_provider.icon(QFileInfo(entry.path))

        if entry.is_link:
            icon = with_link_overlay(icon)

        entry._icon = icon
        return icon

    def _on_dir_changed(self, path: str):
        self._refresh_timer.start()

    def _reload(self):
        # Cancel previous scan if still running
        if self._scan_worker is not None and self._scan_worker.isRunning():
            self._scan_worker.done.disconnect()
            self._scan_worker = None

        if not self._root_path or not os.path.isdir(self._root_path):
            self.beginResetModel()
            self._entries.clear()
            self.endResetModel()
            return

        worker = _ScanWorker(self._root_path)
        worker.done.connect(self._on_scan_done)
        self._scan_worker = worker
        worker.start()

    def _on_scan_done(self, entries: list[FileEntry]):
        self.beginResetModel()
        self._entries = entries
        self._apply_sort()
        self.endResetModel()
        self._scan_worker = None

    def _apply_sort(self):
        col = self._sort_column
        reverse = self._sort_order == Qt.SortOrder.DescendingOrder

        # Name: true name order, folders and files intermixed, numeric-aware.
        # Sort on the displayed name (.lnk stripped) so order matches the column.
        if col == 0:

            def name_key(e: FileEntry):
                name = e.name
                if name.lower().endswith(".lnk"):
                    name = name[:-4]
                return _natural_key(name)

            self._entries.sort(key=name_key, reverse=reverse)
            return

        # Date Modified: strict time order, no folder/file grouping.
        if col == 3:
            self._entries.sort(key=lambda e: e.modified, reverse=reverse)
            return

        # Size / Type: folders stay grouped at the top in BOTH directions.
        # `reverse` must apply to the column value only, never to the
        # folder-first grouping -- otherwise a descending sort flips the
        # whole (dir_priority, value) tuple and sinks folders below files.
        # Sort by the value first (honoring direction), then stable-sort by
        # dir_priority ascending so folders stay on top regardless of order.
        if col == 1:

            def value_key(e: FileEntry):
                return e.size
        else:  # col == 2 (Type)

            def value_key(e: FileEntry):
                return e.ext.lower()

        self._entries.sort(key=value_key, reverse=reverse)
        self._entries.sort(key=lambda e: 0 if e.is_dir else 1)
