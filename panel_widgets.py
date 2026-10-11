"""Small custom widgets used by FilePanel: line edits, tree view, breadcrumb, search."""

import os

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeView,
    QWidget,
)


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
            ):
                e.accept()
                return True
        return super().event(e)


class _FileTreeView(QTreeView):
    """QTreeView subclass that supports dragging files out and accepting drops.

    Drags expose selected items as a ``text/uri-list`` MIME payload via
    :class:`DirectoryModel`, which is compatible with both other FilePanels and
    external apps (Explorer, LINE, browsers).

    Drops emit :attr:`files_dropped` so the owning :class:`FilePanel` can copy
    or move the files using its existing worker pipeline.
    """

    # (paths, keyboard modifiers, explicit target directory or "")
    files_dropped = Signal(list, object, str)
    # Fired for any mouse press, including clicks on empty space where no item exists.
    pressed_anywhere = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDropIndicatorShown(False)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        self.pressed_anywhere.emit()

    def _extract_paths(self, event) -> list[str]:
        mime = event.mimeData()
        if not mime or not mime.hasUrls():
            return []
        paths: list[str] = []
        for url in mime.urls():
            if url.isLocalFile():
                local = url.toLocalFile()
                if local:
                    paths.append(local)
        return paths

    def _target_dir_at(self, event) -> str:
        """Return the folder under the cursor (if any), else empty string."""
        try:
            pos = event.position().toPoint()
        except AttributeError:
            pos = event.pos()
        index = self.indexAt(pos)
        model = self.model()
        if not index.isValid() or model is None:
            return ""
        if not hasattr(model, "file_path") or not hasattr(model, "is_dir"):
            return ""
        path = model.file_path(index)
        if path and model.is_dir(index) and os.path.isdir(path):
            return path
        return ""

    def dragEnterEvent(self, event):
        if event.mimeData() and event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData() and event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event):
        paths = self._extract_paths(event)
        if not paths:
            super().dropEvent(event)
            return
        target_dir = self._target_dir_at(event)
        # Always report Copy so the source app does not also delete the files;
        # we perform move semantics ourselves when requested.
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        self.files_dropped.emit(paths, event.keyboardModifiers(), target_dir)


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


# --- Breadcrumb Path Bar ---


class BreadcrumbBar(QWidget):
    """Clickable breadcrumb path bar with inline path editing.

    - Click a breadcrumb segment to navigate to that level.
    - Click the empty area, double-click, or press Ctrl+L to type a path.
    - Press Enter to navigate, Escape to cancel.
    """

    path_clicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(4, 2, 4, 2)
        outer.setSpacing(4)
        self.setStyleSheet("background-color: #3c3c3c; border: 1px solid #3e3e3e;")
        self.setFixedHeight(28)
        self._path = ""
        self._edit_mode = False

        # Left: breadcrumb buttons container
        self._crumb_container = QWidget()
        self._layout = QHBoxLayout(self._crumb_container)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        outer.addWidget(self._crumb_container, 1)

        # Right: always-visible path input (paste + Enter to jump)
        self._line_edit = _PathLineEdit()
        self._line_edit.setPlaceholderText("貼路徑按 Enter")  # 貼路徑按 Enter
        self._line_edit.setFixedWidth(220)
        self._line_edit.setStyleSheet(
            "QLineEdit {"
            "  background-color: #1e1e1e; color: #ffffff; border: 1px solid #007acc;"
            "  font-size: 11px; padding: 1px 4px; selection-background-color: #264f78;"
            "}"
        )
        self._line_edit.returnPressed.connect(self._on_edit_done)
        outer.addWidget(self._line_edit, 0)

    def set_path(self, path: str):
        self._path = path
        if not self._edit_mode:
            self._build_breadcrumbs()

    def _build_breadcrumbs(self):
        # Clear existing widgets (except the line edit)
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w and w is not self._line_edit:
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
                sep.setStyleSheet("color: #666666; padding: 0 2px; font-size: 13px;")
                self._layout.addWidget(sep)
            btn = QPushButton(label)
            btn.setFlat(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                "QPushButton { color: #cccccc; padding: 2px 4px; font-size: 12px; border: none; }"
                "QPushButton:hover { background-color: #505050; border-radius: 3px; }"
            )
            fp = full_path
            btn.clicked.connect(lambda checked=False, path=fp: self.path_clicked.emit(path))
            self._layout.addWidget(btn)

        self._layout.addStretch()

    # --- Edit mode activation ---

    def _on_edit_done(self):
        """Handle Enter key — navigate if path is valid."""
        raw = self._line_edit.text().strip()
        # Strip surrounding quotes (Windows Explorer "Copy as path" wraps in ")
        if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ('"', "'"):
            raw = raw[1:-1].strip()
        # Expand environment variables and ~
        path = os.path.expandvars(os.path.expanduser(raw))
        if path:
            path = os.path.normpath(path)
        if path and os.path.isdir(path):
            self._line_edit.clear()
            self._line_edit.clearFocus()
            self.path_clicked.emit(path)
        else:
            # Keep edit mode open and flash red border so user can correct
            self._line_edit.setStyleSheet(
                "QLineEdit {"
                "  background-color: #1e1e1e; color: #ffffff; border: 1px solid #d9534f;"
                "  font-size: 12px; padding: 2px 4px; selection-background-color: #264f78;"
                "}"
            )
            self._line_edit.setFocus()
            self._line_edit.selectAll()
            QTimer.singleShot(800, self._reset_line_edit_style)

    def _reset_line_edit_style(self):
        self._line_edit.setStyleSheet(
            "QLineEdit {"
            "  background-color: #1e1e1e; color: #ffffff; border: 1px solid #007acc;"
            "  font-size: 12px; padding: 2px 4px; selection-background-color: #264f78;"
            "}"
        )


# --- Search Bar ---


class SearchBar(QWidget):
    """Inline search bar that filters the current file list."""

    search_changed = Signal(str)
    closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(4)

        label = QLabel("搜尋：")
        label.setStyleSheet("color: #cccccc; font-size: 12px;")
        layout.addWidget(label)

        self.input = QLineEdit()
        self.input.setPlaceholderText("輸入檔名...")
        self.input.textChanged.connect(self.search_changed.emit)
        layout.addWidget(self.input)

        btn_close = QPushButton("✕")
        btn_close.setFixedWidth(28)
        btn_close.clicked.connect(self._close)
        layout.addWidget(btn_close)

        self.setVisible(False)
        self.setStyleSheet("background-color: #2d2d2d; border: 1px solid #007acc;")

    def activate(self):
        self.setVisible(True)
        self.input.clear()
        self.input.setFocus()

    def _close(self):
        self.input.clear()
        self.setVisible(False)
        self.closed.emit()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self._close()
        else:
            super().keyPressEvent(event)
