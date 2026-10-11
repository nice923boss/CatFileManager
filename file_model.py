"""Custom file system model that correctly lists all files including .lnk shortcuts.

Qt's QFileSystemModel has a known bug where it treats .lnk files as symlinks
and silently drops them if the target resolution fails. This model uses
os.scandir() directly to avoid that issue.

Directories are scanned and sorted in a background thread, and per-file icons
(.exe, .ico, .lnk …) are fetched in another background thread, so huge
folders never freeze the UI.
"""

import os
import re
import stat as stat_mod
import time
from collections import OrderedDict

from PySide6.QtCore import (
    QAbstractItemModel,
    QFileInfo,
    QFileSystemWatcher,
    QMimeData,
    QModelIndex,
    Qt,
    QThread,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import QColor, QIcon, QImage, QPixmap
from PySide6.QtWidgets import QFileIconProvider

from file_types import category
from icon_loader import icon_loader
from link_icon import link_target, with_link_overlay
from shell_utils import _resolve_lnk_target

_HIDDEN_MASK = stat_mod.FILE_ATTRIBUTE_HIDDEN | stat_mod.FILE_ATTRIBUTE_SYSTEM
_icon_provider = QFileIconProvider()

# Extensions whose icon differs per file; everything else shares one icon per
# extension, which turns thousands of shell calls into a handful (J01).
_PER_FILE_ICON_EXTS = frozenset(
    {".exe", ".ico", ".lnk", ".url", ".cur", ".ani", ".scr", ".cpl", ".msc"}
)

# Per-file icons are shared across folders and panels with an LRU cap (J02).
_FILE_ICON_CACHE_MAX = 1024
_file_icon_cache: OrderedDict[str, QIcon] = OrderedDict()
_ext_icon_cache: dict[str, QIcon] = {}
_folder_icon: QIcon | None = None

_SCAN_PROGRESS_EVERY = 5000

# Icon sizes at or above this show image/video thumbnails instead of icons.
THUMBNAIL_MIN_SIZE = 48


def _cache_key(path: str, size: int, icon_only: bool) -> str:
    return f"{size}|{'i' if icon_only else 't'}|{path}"


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


class FileEntry:
    __slots__ = (
        "name",
        "path",
        "is_dir",
        "size",
        "modified",
        "ext",
        "is_link",
        "link_kind",
        "hidden",
        "broken",
        "_icon",
        "_tip",
    )

    def __init__(
        self,
        name: str,
        path: str,
        is_dir: bool,
        size: int,
        modified: float,
        ext: str,
        is_link: bool = False,
        link_kind: str = "",
        hidden: bool = False,
        broken: bool = False,
    ):
        self.name = name
        self.path = path
        self.is_dir = is_dir
        self.size = size
        self.modified = modified
        self.ext = ext
        self.is_link = is_link  # NTFS junction or symlink
        self.link_kind = link_kind  # "junction" | "symlink" | ""
        self.hidden = hidden  # hidden or system attribute
        self.broken = broken  # link whose target no longer exists
        self._icon: QIcon | None = None
        self._tip: str | None = None


def scan_entry(entry: os.DirEntry) -> FileEntry:
    """Build a FileEntry from a DirEntry (raises OSError if it vanished)."""
    # On Windows DirEntry.stat(follow_symlinks=False) reuses the FindNextFile
    # data, so attributes cost no extra syscall.
    st = entry.stat(follow_symlinks=False)
    attrs = st.st_file_attributes
    name = entry.name
    if entry.is_junction():
        link_kind = "junction"
    elif entry.is_symlink():
        link_kind = "symlink"
    else:
        link_kind = ""
    # A directory symlink is not a dir with follow_symlinks=False; its own
    # DIRECTORY attribute says what it points at (G04).
    is_dir = bool(attrs & stat_mod.FILE_ATTRIBUTE_DIRECTORY) and not name.lower().endswith(".lnk")
    broken = bool(link_kind) and not os.path.exists(entry.path)
    return FileEntry(
        name,
        entry.path,
        is_dir,
        st.st_size,
        st.st_mtime,
        os.path.splitext(name)[1],
        bool(link_kind),
        link_kind,
        bool(attrs & _HIDDEN_MASK),
        broken,
    )


def _display_stem(name: str) -> str:
    return name[:-4] if name.lower().endswith(".lnk") else name


def sort_entries(entries: list[FileEntry], col: int, order: Qt.SortOrder) -> None:
    """Sort in place the way the list view expects."""
    reverse = order == Qt.SortOrder.DescendingOrder

    # Name: true name order, folders and files intermixed, numeric-aware.
    # Sort on the displayed name (.lnk stripped) so order matches the column.
    if col == 0:
        entries.sort(key=lambda e: _natural_key(_display_stem(e.name)), reverse=reverse)
        return

    # Date Modified: strict time order, no folder/file grouping.
    if col == 3:
        entries.sort(key=lambda e: e.modified, reverse=reverse)
        return

    # Size / Type: folders stay grouped at the top in BOTH directions.
    # `reverse` must apply to the column value only, never to the
    # folder-first grouping -- otherwise a descending sort flips the
    # whole (dir_priority, value) tuple and sinks folders below files.
    # Sort by the value first (honoring direction), then stable-sort by
    # dir_priority ascending so folders stay on top regardless of order.
    if col == 1:
        entries.sort(key=lambda e: e.size, reverse=reverse)
    else:  # col == 2 (Type)
        entries.sort(key=lambda e: e.ext.lower(), reverse=reverse)
    entries.sort(key=lambda e: 0 if e.is_dir else 1)


def _type_label(entry: FileEntry) -> str:
    if entry.broken:
        return "失效連結"
    if entry.link_kind == "junction":
        return "Junction"
    if entry.link_kind == "symlink":
        return "符號連結（資料夾）" if entry.is_dir else "符號連結"
    if entry.is_dir:
        return "資料夾"
    if entry.name.lower().endswith(".lnk"):
        return "捷徑"
    return entry.ext.upper()[1:] if entry.ext else ""


def _link_tooltip(entry: FileEntry) -> str | None:
    """Tooltip "→ target" for junctions, symlinks and .lnk shortcuts (G02)."""
    if entry._tip is None:
        target = ""
        if entry.is_link:
            target = link_target(entry.path) or ""
        elif entry.name.lower().endswith(".lnk"):
            resolved = _resolve_lnk_target(entry.path)
            target = "" if resolved == entry.path else resolved
        if target and entry.broken:
            target += "（目標不存在）"
        entry._tip = f"→ {target}" if target else ""
    return entry._tip or None


class _ScanWorker(QThread):
    """Background thread: list a directory and sort it before handing it over."""

    done = Signal(list)  # list[FileEntry], already sorted
    progress = Signal(int)  # entries found so far (large folders only)

    def __init__(
        self,
        path: str,
        show_hidden: bool = False,
        sort_column: int = 0,
        sort_order: Qt.SortOrder = Qt.SortOrder.AscendingOrder,
        parent=None,
    ):
        super().__init__(parent)
        self._path = path
        self._show_hidden = show_hidden
        self._sort = (sort_column, sort_order)

    def run(self):
        entries = []
        try:
            with os.scandir(self._path) as it:
                for entry in it:
                    try:
                        fe = scan_entry(entry)
                    except OSError:
                        continue
                    if fe.hidden and not self._show_hidden:
                        continue
                    entries.append(fe)
                    if len(entries) % _SCAN_PROGRESS_EVERY == 0:
                        self.progress.emit(len(entries))
        except OSError:
            pass
        sort_entries(entries, *self._sort)
        self.done.emit(entries)


class DirectoryModel(QAbstractItemModel):
    """A flat table model that lists files in a single directory."""

    COLUMNS = ["名稱", "大小", "類型", "修改日期"]

    scan_progress = Signal(int)  # entries found so far while a big folder loads
    scan_finished = Signal()
    root_missing = Signal(str)  # the shown folder disappeared (drive removed …)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entries: list[FileEntry] = []
        self._row_of: dict[str, int] = {}
        self._root_path = ""
        self._sort_column = 0
        self._sort_order = Qt.SortOrder.AscendingOrder
        self._scan_worker: _ScanWorker | None = None
        # Every scan thread stays referenced until it finishes, so dropping a
        # superseded or completed scan never destroys a running QThread.
        self._live_workers: list[_ScanWorker] = []
        self._show_hidden = False
        self._show_extensions = True
        self._type_colors: dict[str, QColor] = {}  # empty = colouring off
        self._text_color = QColor("#cccccc")
        self._icon_size = 16

        icon_loader().loaded.connect(self._on_icon_loaded)

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

    def is_loading(self) -> bool:
        return self._scan_worker is not None

    def set_view_options(
        self,
        show_hidden: bool,
        show_extensions: bool,
        type_colors: dict[str, str] | None,
        text_color: str = "#cccccc",
    ) -> None:
        """Apply preference toggles; rescans only when the hidden filter changes."""
        rescan = show_hidden != self._show_hidden
        self._show_hidden = show_hidden
        self._show_extensions = show_extensions
        self._type_colors = {k: QColor(v) for k, v in (type_colors or {}).items()}
        self._text_color = QColor(text_color)
        if rescan:
            self._reload()
        else:
            self._emit_all_changed()

    def set_icon_size(self, size: int) -> None:
        """Pixel size the view draws icons at; large sizes request bigger shell icons."""
        if size != self._icon_size:
            self._icon_size = size
            for e in self._entries:
                e._icon = None
            self._emit_all_changed()

    def sort_state(self) -> tuple[int, Qt.SortOrder]:
        return self._sort_column, self._sort_order

    def file_path(self, index: QModelIndex) -> str:
        e = self.entry(index)
        return e.path if e else ""

    def is_dir(self, index: QModelIndex) -> bool:
        e = self.entry(index)
        return e.is_dir if e else False

    def file_name(self, index: QModelIndex) -> str:
        e = self.entry(index)
        return e.name if e else ""

    def entry(self, index: QModelIndex) -> FileEntry | None:
        if index.isValid() and 0 <= index.row() < len(self._entries):
            return self._entries[index.row()]
        return None

    def entries(self) -> list[FileEntry]:
        return list(self._entries)

    def row_of(self, path: str) -> int:
        return self._row_of.get(path, -1)

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
                return self.display_name(entry)
            elif col == 1:
                if entry.is_dir:
                    return ""
                return _format_size(entry.size)
            elif col == 2:
                return _type_label(entry)
            elif col == 3:
                try:
                    return time.strftime("%Y/%m/%d %H:%M", time.localtime(entry.modified))
                except (OSError, ValueError):
                    return ""
        elif role == Qt.ItemDataRole.DecorationRole and col == 0:
            return self._get_icon(entry)
        elif role == Qt.ItemDataRole.ForegroundRole:
            return self._foreground(entry)
        elif role == Qt.ItemDataRole.ToolTipRole and col == 0:
            return _link_tooltip(entry)

        return None

    def display_name(self, entry: FileEntry) -> str:
        name = _display_stem(entry.name)
        if not self._show_extensions and not entry.is_dir:
            stem, ext = os.path.splitext(name)
            if stem and ext:
                return stem
        return name

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            if 0 <= section < len(self.COLUMNS):
                return self.COLUMNS[section]
        return None

    def sort(self, column, order=Qt.SortOrder.AscendingOrder):
        self._sort_column = column
        self._sort_order = order
        self.layoutAboutToBeChanged.emit()
        sort_entries(self._entries, column, order)
        self._rebuild_row_index()
        self.layoutChanged.emit()

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

    def _foreground(self, entry: FileEntry) -> QColor | None:
        color = None
        if entry.broken:
            color = QColor(self._type_colors.get("broken", QColor("#f14c4c")))
        elif self._type_colors and not entry.is_dir:
            cat = category(entry.ext)
            if cat:
                color = QColor(self._type_colors[cat])
        if entry.hidden:
            # Hidden items are drawn semi-transparent (A04)
            color = QColor(color or self._text_color)
            color.setAlpha(120)
        return color

    def _get_icon(self, entry: FileEntry) -> QIcon:
        global _folder_icon
        if entry._icon is not None:
            return entry._icon

        ext = entry.ext.lower()
        # Large icon view shows real thumbnails for pictures and videos (A02).
        thumb = (
            not entry.is_dir
            and self._icon_size >= THUMBNAIL_MIN_SIZE
            and category(ext) in ("image", "video")
        )
        if entry.is_dir:
            if _folder_icon is None:
                _folder_icon = _icon_provider.icon(QFileIconProvider.IconType.Folder)
            icon = _folder_icon
        elif thumb or ext in _PER_FILE_ICON_EXTS:
            key = _cache_key(entry.path, self._icon_size, not thumb)
            icon = _file_icon_cache.get(key)
            if icon is None:
                # Placeholder now; the real image arrives from the icon loader.
                icon_loader().request(entry.path, self._icon_size, not thumb)
                return self._ext_icon(entry, ext)
            _file_icon_cache.move_to_end(key)
        else:
            icon = self._ext_icon(entry, ext)

        # .lnk shortcuts get the same arrow badge as junctions (A15)
        if entry.is_link or ext == ".lnk":
            icon = with_link_overlay(icon)

        entry._icon = icon
        return icon

    @staticmethod
    def _ext_icon(entry: FileEntry, ext: str) -> QIcon:
        icon = _ext_icon_cache.get(ext)
        if icon is None:
            icon = _icon_provider.icon(QFileInfo(entry.path))
            if ext and ext not in _PER_FILE_ICON_EXTS:  # those differ per file
                _ext_icon_cache[ext] = icon
        return icon

    def _on_icon_loaded(self, path: str, size: int, icon_only: bool, img: QImage):
        key = _cache_key(path, size, icon_only)
        if key not in _file_icon_cache:  # every model gets the signal; store once
            _file_icon_cache[key] = QIcon(QPixmap.fromImage(img))
            if len(_file_icon_cache) > _FILE_ICON_CACHE_MAX:
                _file_icon_cache.popitem(last=False)
        row = self._row_of.get(path, -1)
        if row >= 0 and size == self._icon_size:
            self._entries[row]._icon = None
            idx = self.index(row, 0)
            self.dataChanged.emit(idx, idx, [Qt.ItemDataRole.DecorationRole])

    def _emit_all_changed(self):
        if self._entries:
            self.dataChanged.emit(
                self.index(0, 0), self.index(len(self._entries) - 1, len(self.COLUMNS) - 1)
            )

    def _rebuild_row_index(self):
        self._row_of = {e.path: i for i, e in enumerate(self._entries)}

    def _on_dir_changed(self, path: str):
        self._refresh_timer.start()

    def _reload(self):
        # Ignore the previous scan (its result may still be queued even if it stopped)
        if self._scan_worker is not None:
            self._scan_worker.done.disconnect()
            self._scan_worker.progress.disconnect()
            self._scan_worker = None

        if not self._root_path or not os.path.isdir(self._root_path):
            self.beginResetModel()
            self._entries = []
            self._row_of = {}
            self.endResetModel()
            if self._root_path:
                self.root_missing.emit(self._root_path)
            return

        worker = _ScanWorker(
            self._root_path, self._show_hidden, self._sort_column, self._sort_order
        )
        worker.done.connect(self._on_scan_done)
        worker.progress.connect(self.scan_progress.emit)
        self._live_workers.append(worker)
        # Bound slot on this main-thread object -> queued, runs after the thread ended.
        worker.finished.connect(self._forget_finished_workers)
        self._scan_worker = worker
        worker.start()

    def _forget_finished_workers(self):
        self._live_workers = [w for w in self._live_workers if not w.isFinished()]

    def _on_scan_done(self, entries: list[FileEntry]):
        worker = self._scan_worker
        self.beginResetModel()
        self._entries = entries
        # The user may have re-sorted while the scan was running.
        if worker is not None and worker._sort != (self._sort_column, self._sort_order):
            sort_entries(self._entries, self._sort_column, self._sort_order)
        self._rebuild_row_index()
        self.endResetModel()
        self._scan_worker = None
        self.scan_finished.emit()
