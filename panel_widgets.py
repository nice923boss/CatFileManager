"""Small custom widgets used by FilePanel: line edits, file views, breadcrumb, search."""

import os

from PySide6.QtCore import QDir, QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCompleter,
    QFileSystemModel,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QListView,
    QPushButton,
    QScrollArea,
    QToolTip,
    QTreeView,
    QWidget,
)

from copy_engine import same_drive


class _PathLineEdit(QLineEdit):
    """QLineEdit that steals Return/Backspace/Space from parent QShortcuts."""

    def event(self, e):
        if e.type() == e.Type.ShortcutOverride:
            k = e.key()
            if k in (
                Qt.Key.Key_Return,
                Qt.Key.Key_Enter,
                Qt.Key.Key_Backspace,
                Qt.Key.Key_Space,
                Qt.Key.Key_Delete,
                Qt.Key.Key_Tab,
            ):
                e.accept()
                return True
        return super().event(e)


def drop_operation(paths: list[str], dest: str, modifiers) -> str:
    """Explorer convention: Ctrl copies, Shift moves, otherwise same drive moves."""
    if modifiers & Qt.KeyboardModifier.ControlModifier:
        return "copy"
    if modifiers & Qt.KeyboardModifier.ShiftModifier:
        return "move"
    return "move" if paths and same_drive(paths[0], dest) else "copy"


class _DropMixin:
    """Drag-out via the model's MIME data, drop-in reported through `files_dropped`.

    While dragging, a tooltip next to the cursor says whether the drop will
    move or copy and where to (C06).
    """

    _HINT_OFFSET = QPoint(16, 16)

    def _init_drag_drop(self) -> None:
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDropIndicatorShown(False)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self._fallback_dir = ""  # folder shown by the panel; set by the owner

    @staticmethod
    def _extract_paths(event) -> list[str]:
        mime = event.mimeData()
        if not mime or not mime.hasUrls():
            return []
        return [u.toLocalFile() for u in mime.urls() if u.isLocalFile() and u.toLocalFile()]

    def _target_dir_at(self, event) -> str:
        """Return the folder under the cursor (if any), else empty string."""
        index = self.indexAt(event.position().toPoint())
        model = self.model()
        if not index.isValid() or model is None or not hasattr(model, "is_dir"):
            return ""
        path = model.file_path(index)
        if path and model.is_dir(index) and os.path.isdir(path):
            return path
        return ""

    def _drag_hint(self, event) -> None:
        paths = self._extract_paths(event)
        dest = self._target_dir_at(event) or self._fallback_dir
        if not paths or not dest:
            QToolTip.hideText()
            return
        op = drop_operation(paths, dest, event.modifiers())
        verb = "移動到" if op == "move" else "複製到"
        hint = f"{verb}「{os.path.basename(dest) or dest}」\nCtrl：複製　Shift：移動"
        global_pos = self.viewport().mapToGlobal(event.position().toPoint())
        QToolTip.showText(global_pos + self._HINT_OFFSET, hint, self)

    def dragEnterEvent(self, event):
        if event.mimeData() and event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData() and event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._drag_hint(event)
            return
        super().dragMoveEvent(event)

    def dragLeaveEvent(self, event):
        QToolTip.hideText()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        QToolTip.hideText()
        paths = self._extract_paths(event)
        if not paths:
            super().dropEvent(event)
            return
        target_dir = self._target_dir_at(event)
        # Always report Copy so the source app does not also delete the files;
        # we perform move semantics ourselves when requested.
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        self.files_dropped.emit(paths, event.modifiers(), target_dir)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        self.pressed_anywhere.emit()


class _FileTreeView(_DropMixin, QTreeView):
    """Details view (columns)."""

    # (paths, keyboard modifiers, explicit target directory or "")
    files_dropped = Signal(list, object, str)
    # Fired for any mouse press, including clicks on empty space where no item exists.
    pressed_anywhere = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_drag_drop()


class _FileIconView(_DropMixin, QListView):
    """Large-icon view with thumbnails (A02); shares the panel's model and selection."""

    files_dropped = Signal(list, object, str)
    pressed_anywhere = Signal()

    ICON_SIZE = 96

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setIconSize(QSize(self.ICON_SIZE, self.ICON_SIZE))
        self.setGridSize(QSize(self.ICON_SIZE + 40, self.ICON_SIZE + 44))
        self.setWordWrap(True)
        self.setUniformItemSizes(True)
        self.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self._init_drag_drop()


class _RenameLineEdit(QLineEdit):
    """QLineEdit with Shift+Up (select to start) and Shift+Down (select to end)."""

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Up and event.modifiers() == Qt.KeyboardModifier.ShiftModifier:
            self.setSelection(0, self.cursorPosition())
            return
        if (
            event.key() == Qt.Key.Key_Down
            and event.modifiers() == Qt.KeyboardModifier.ShiftModifier
        ):
            pos = self.cursorPosition()
            self.setSelection(pos, len(self.text()) - pos)
            return
        super().keyPressEvent(event)

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)


def expand_user_path(raw: str) -> str:
    """Turn typed text into a path: strips quotes, expands %VARS%, ~ and shell:folders (B11)."""
    from shell_utils import resolve_shell_folder

    raw = raw.strip()
    # Strip surrounding quotes (Windows Explorer "Copy as path" wraps in ")
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ('"', "'"):
        raw = raw[1:-1].strip()
    if raw.lower().startswith("shell:"):
        head, _, rest = raw.partition("\\")
        base = resolve_shell_folder(head[6:])
        if not base:
            return ""
        raw = os.path.join(base, rest) if rest else base
    path = os.path.expandvars(os.path.expanduser(raw))
    return os.path.normpath(path) if path else ""


# --- Breadcrumb Path Bar ---


class BreadcrumbBar(QWidget):
    """Clickable breadcrumb path bar with a path input (paste or type + Enter).

    The input completes folder names as you type (B03), accepts UNC paths and
    mapped drives (B10), environment variables and shell:folders (B11).
    """

    path_clicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("breadcrumb")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(4, 2, 4, 2)
        outer.setSpacing(4)
        self.setFixedHeight(28)
        self._path = ""

        # Left: breadcrumb buttons container
        self._crumb_container = QWidget()
        self._layout = QHBoxLayout(self._crumb_container)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        # Keep every crumb at full width; the QSS "QPushButton { min-width }" rule
        # would otherwise let the layout squeeze names down to a few pixels.
        self._layout.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)
        # Scroll area (no visible scrollbar) lets a long path shrink instead of
        # widening the panel; it stays scrolled to the right so the current
        # folder remains visible.
        self._crumb_container.setObjectName("crumbContainer")
        self._crumb_scroll = QScrollArea()
        self._crumb_scroll.setObjectName("crumbScroll")
        self._crumb_scroll.setWidget(self._crumb_container)
        self._crumb_scroll.setWidgetResizable(True)
        self._crumb_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._crumb_scroll.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._crumb_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._crumb_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._crumb_scroll.viewport().setAutoFillBackground(False)
        hbar = self._crumb_scroll.horizontalScrollBar()
        hbar.rangeChanged.connect(lambda _lo, hi: hbar.setValue(hi))
        outer.addWidget(self._crumb_scroll, 1)

        # Right: always-visible path input (paste + Enter to jump)
        self._line_edit = _PathLineEdit()
        self._line_edit.setObjectName("breadcrumbEdit")
        self._line_edit.setPlaceholderText("貼路徑按 Enter")
        self._line_edit.setFixedWidth(220)
        self._line_edit.returnPressed.connect(self._on_edit_done)
        outer.addWidget(self._line_edit, 0)

        fs_model = QFileSystemModel(self)
        fs_model.setFilter(QDir.Filter.AllDirs | QDir.Filter.NoDotAndDotDot | QDir.Filter.Drives)
        fs_model.setRootPath("")
        completer = QCompleter(fs_model, self)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self._line_edit.setCompleter(completer)

    def line_edit(self) -> QLineEdit:
        return self._line_edit

    def set_path(self, path: str):
        self._path = path
        self._build_breadcrumbs()

    def _build_breadcrumbs(self):
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        if not self._path:
            return

        parts: list[tuple[str, str]] = []
        p = os.path.normpath(self._path)
        while True:
            head, tail = os.path.split(p)
            if tail:
                parts.append((tail, p))
                p = head
            else:
                if head:
                    parts.append((head, head))
                break
        parts.reverse()

        for i, (label, full_path) in enumerate(parts):
            if i > 0:
                sep = QLabel("›")
                sep.setObjectName("crumbSep")
                self._layout.addWidget(sep)
            btn = QPushButton(label)
            btn.setObjectName("crumbBtn")
            btn.setFlat(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, path=full_path: self.path_clicked.emit(path))
            self._layout.addWidget(btn)

        self._layout.addStretch()

    def _on_edit_done(self):
        """Handle Enter key — navigate if path is valid."""
        path = expand_user_path(self._line_edit.text())
        if path and os.path.isdir(path):
            self._line_edit.clear()
            self._line_edit.clearFocus()
            self.path_clicked.emit(path)
        else:
            # Keep the text and flash a red border so the user can correct it
            self._set_error(True)
            self._line_edit.setFocus()
            self._line_edit.selectAll()
            QTimer.singleShot(800, lambda: self._set_error(False))

    def _set_error(self, on: bool) -> None:
        self._line_edit.setProperty("error", on)
        self._line_edit.style().unpolish(self._line_edit)
        self._line_edit.style().polish(self._line_edit)
