"""Cut/copy state shared by all panels (single source of truth)."""

import os

from PySide6.QtCore import QMimeData, QUrl
from PySide6.QtWidgets import QApplication


class FileClipboard:
    """Remembers which paths were cut or copied and mirrors them to the OS clipboard.

    The OS clipboard is used as a fallback source when nothing was cut/copied
    inside the app (e.g. files copied in Explorer).
    """

    def __init__(self):
        self._paths: list[str] = []
        self._op = ""  # "copy" | "cut" | ""

    def set(self, paths: list[str], op: str) -> None:
        self._paths = list(paths)
        self._op = op
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(os.path.normpath(p)) for p in paths])
        mime.setText("\n".join(os.path.normpath(p) for p in paths))
        QApplication.clipboard().setMimeData(mime)

    def contents(self) -> tuple[list[str], str]:
        """Return (paths, op); falls back to files on the OS clipboard as a copy."""
        if self._paths:
            return list(self._paths), self._op
        mime = QApplication.clipboard().mimeData()
        if mime and mime.hasUrls():
            paths = [u.toLocalFile() for u in mime.urls() if u.isLocalFile()]
            if paths:
                return paths, "copy"
        return [], ""

    def clear(self) -> None:
        self._paths = []
        self._op = ""


file_clipboard = FileClipboard()
