"""Space-bar quick preview (lightbox) for images, PDF and Markdown.

`QuickPreview` covers the whole main window with a dark backdrop and shows one
file at a time; Up / Down step through the other previewable files of the
panel, Space / Esc / a click on the backdrop close it. Other file types keep
going to QuickLook (see `FilePanel._preview`).
"""

import logging
import os

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QImageReader, QPainter, QPixmap
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPdfWidgets import QPdfView
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from file_types import IMAGE_EXTS

log = logging.getLogger(__name__)

_QT_IMAGE_EXTS = {"." + bytes(f).decode() for f in QImageReader.supportedImageFormats()}
_KINDS = {
    **{ext: "image" for ext in IMAGE_EXTS & _QT_IMAGE_EXTS},  # .heic has no Qt reader
    ".pdf": "pdf",
    ".md": "markdown",
    ".markdown": "markdown",
}
_MARKDOWN_MAX_WIDTH = 900


def preview_kind(path: str) -> str:
    """Return "image" / "pdf" / "markdown", or "" when the built-in preview can't show it."""
    return _KINDS.get(os.path.splitext(path)[1].lower(), "")


def _read_text(path: str) -> str:
    with open(path, "rb") as f:
        data = f.read()
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp950", errors="replace")


class _ImageView(QWidget):
    """Draws one image centred, shrunk to fit but never enlarged."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._source = QPixmap()
        self._scaled = QPixmap()

    def set_pixmap(self, pixmap: QPixmap) -> None:
        self._source = pixmap
        self._scaled = QPixmap()
        self.update()

    def pixmap(self) -> QPixmap:
        return self._source

    def _image_rect(self) -> QRect:
        if self._scaled.isNull():
            dpr = self.devicePixelRatioF()
            size = self._source.size()
            if size.width() > self.width() * dpr or size.height() > self.height() * dpr:
                size = size.scaled(self.size() * dpr, Qt.AspectRatioMode.KeepAspectRatio)
            self._scaled = self._source.scaled(
                size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            )
            self._scaled.setDevicePixelRatio(dpr)
        logical = self._scaled.deviceIndependentSize().toSize()
        rect = QRect(QPoint(0, 0), logical)
        rect.moveCenter(self.rect().center())
        return rect

    def resizeEvent(self, event):
        self._scaled = QPixmap()
        super().resizeEvent(event)

    def paintEvent(self, _event):
        if self._source.isNull():
            return
        rect = self._image_rect()
        QPainter(self).drawPixmap(rect.topLeft(), self._scaled)

    def mousePressEvent(self, event):
        # Clicks beside the image reach the backdrop and close the preview.
        if self._source.isNull() or not self._image_rect().contains(event.position().toPoint()):
            event.ignore()


class QuickPreview(QWidget):
    """Lightbox over `host` (the main window) for `paths`, starting at `index`."""

    current_changed = Signal(str)  # path now shown, so the panel can select it
    closed = Signal()

    def __init__(self, host: QWidget, paths: list[str], index: int):
        super().__init__(host)
        self.setObjectName("quickPreview")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._paths = paths
        self._index = index

        self._title = QLabel()
        self._title.setObjectName("previewTitle")
        self._counter = QLabel()
        self._counter.setObjectName("previewDim")
        close_btn = QPushButton("✕")
        close_btn.setObjectName("previewClose")
        close_btn.setToolTip("關閉（Esc）")
        close_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        close_btn.clicked.connect(self.close)
        top = QHBoxLayout()
        top.addWidget(self._title, 1)
        top.addWidget(self._counter)
        top.addWidget(close_btn)

        self._image = _ImageView()
        self._pdf_doc = QPdfDocument(self)
        self._pdf = QPdfView()
        self._pdf.setObjectName("previewPdf")
        self._pdf.setDocument(self._pdf_doc)
        self._pdf.setPageMode(QPdfView.PageMode.MultiPage)
        self._pdf.setZoomMode(QPdfView.ZoomMode.FitInView)
        self._text = QTextBrowser()
        self._text.setObjectName("previewText")
        self._text.setOpenExternalLinks(True)
        self._text.setMaximumWidth(_MARKDOWN_MAX_WIDTH)
        self._text.document().setDocumentMargin(24)
        text_page = QWidget()
        text_row = QHBoxLayout(text_page)
        text_row.setContentsMargins(0, 0, 0, 0)
        text_row.addWidget(self._text)
        self._message = QLabel()
        self._message.setObjectName("previewTitle")
        self._message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        for w in (self._pdf, self._text):
            # Keys stay with the lightbox (Up / Down switch files); the wheel still scrolls.
            w.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._stack = QStackedWidget()
        for page in (self._image, self._pdf, text_page, self._message):
            self._stack.addWidget(page)
        self._pages = {"image": self._image, "pdf": self._pdf, "markdown": text_page}

        hint = QLabel("↑ ↓ 上一個／下一個　　空白鍵或 Esc 關閉")
        hint.setObjectName("previewDim")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 12, 40, 12)
        layout.addLayout(top)
        layout.addWidget(self._stack, 1)
        layout.addWidget(hint)

        host.installEventFilter(self)

    # --- Public ---

    def open(self) -> None:
        self.setGeometry(self.parentWidget().rect())
        self.raise_()
        self.show()
        self.setFocus()
        self._load()

    def current_path(self) -> str:
        return self._paths[self._index]

    def step(self, delta: int) -> None:
        index = max(0, min(len(self._paths) - 1, self._index + delta))
        if index != self._index:
            self._index = index
            self._load()
            self.current_changed.emit(self.current_path())

    # --- Loading ---

    def _load(self) -> None:
        path = self.current_path()
        self._title.setText(os.path.basename(path))
        self._counter.setText(f"{self._index + 1} / {len(self._paths)}")
        self._pdf_doc.close()
        self._text.clear()
        self._image.set_pixmap(QPixmap())
        kind = preview_kind(path)
        loaders = {"image": self._load_image, "pdf": self._load_pdf, "markdown": self._load_text}
        error = loaders[kind](path)
        if error:
            self._message.setText(error)
            self._stack.setCurrentWidget(self._message)
        else:
            self._stack.setCurrentWidget(self._pages[kind])

    def _load_image(self, path: str) -> str:
        reader = QImageReader(path)
        reader.setAutoTransform(True)  # EXIF rotation
        # Decode no larger than the screen: big photos load faster and use less memory.
        screen = self.screen().geometry().size() * self.devicePixelRatioF()
        bound = max(screen.width(), screen.height())
        size = reader.size()
        if size.isValid() and (size.width() > bound or size.height() > bound):
            reader.setScaledSize(
                size.scaled(QSize(bound, bound), Qt.AspectRatioMode.KeepAspectRatio)
            )
        image = reader.read()
        if image.isNull():
            log.warning("Cannot preview image %s: %s", path, reader.errorString())
            return "無法讀取這張圖片"
        self._image.set_pixmap(QPixmap.fromImage(image))
        return ""

    def _load_pdf(self, path: str) -> str:
        error = self._pdf_doc.load(path)
        if error == QPdfDocument.Error.IncorrectPassword:
            return "這份 PDF 有密碼保護，無法預覽"
        if error != QPdfDocument.Error.None_:
            log.warning("Cannot preview PDF %s: %s", path, error)
            return "無法開啟這份 PDF"
        return ""

    def _load_text(self, path: str) -> str:
        try:
            text = _read_text(path)
        except OSError as e:
            log.warning("Cannot preview %s: %s", path, e)
            return "無法讀取這個檔案"
        # Relative image links in the Markdown resolve against the file's folder.
        self._text.document().setBaseUrl(QUrl.fromLocalFile(os.path.dirname(path) + os.sep))
        self._text.setMarkdown(text)
        return ""

    # --- Events ---

    def eventFilter(self, obj, event):
        if obj is self.parentWidget() and event.type() == QEvent.Type.Resize:
            self.setGeometry(obj.rect())
        return False

    def event(self, e):
        if e.type() == QEvent.Type.ShortcutOverride:
            # Keep panel / window shortcuts (Tab, Delete, Ctrl+Z…) from acting behind the preview.
            e.accept()
            return True
        return super().event(e)

    def focusNextPrevChild(self, _next: bool) -> bool:
        return False  # Tab must not move focus to the panels underneath

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_Up:
            self.step(-1)
        elif key == Qt.Key.Key_Down:
            self.step(1)
        elif key in (Qt.Key.Key_Escape, Qt.Key.Key_Space):
            self.close()

    def mousePressEvent(self, event):
        self.close()  # only clicks on the backdrop get here

    def paintEvent(self, _event):
        QPainter(self).fillRect(self.rect(), QColor(0, 0, 0, 215))

    def closeEvent(self, event):
        self.parentWidget().removeEventFilter(self)
        self.closed.emit()
        super().closeEvent(event)
