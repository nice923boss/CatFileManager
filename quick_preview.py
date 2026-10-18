"""Space-bar quick preview (lightbox) for images, PDF, Markdown, plain text / code,
video and audio.

`QuickPreview` covers the whole main window with a dark backdrop and shows one
file at a time; Up / Down step through the other previewable files of the
panel, Space / Esc / a click on the backdrop close it. Video and audio start
playing at once; Enter pauses / resumes and Left / Right seek. Other file types
keep going to QuickLook (see `FilePanel._preview`).
"""

import codecs
import logging
import os

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QImageReader, QPainter, QPixmap
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPdfWidgets import QPdfView
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from file_types import IMAGE_EXTS, VIDEO_EXTS
from preview_media import SEEK_STEP_MS, MediaView

log = logging.getLogger(__name__)

_QT_IMAGE_EXTS = {"." + bytes(f).decode() for f in QImageReader.supportedImageFormats()}
_TEXT_EXTS = {
    ".txt", ".log", ".ini", ".cfg", ".conf", ".toml", ".yaml", ".yml", ".properties", ".env",
    ".json", ".jsonl", ".csv", ".tsv", ".xml", ".html", ".htm", ".css", ".srt", ".vtt", ".ass",
    ".py", ".pyw", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".vue", ".sql",
    ".bat", ".cmd", ".ps1", ".sh", ".vbs", ".reg",
    ".c", ".h", ".cpp", ".hpp", ".cs", ".java", ".go", ".rs", ".php", ".rb", ".xaml",
}  # fmt: skip
_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".flac", ".aac", ".ogg", ".oga", ".opus", ".wma"}
_KINDS = {
    **{ext: "image" for ext in IMAGE_EXTS & _QT_IMAGE_EXTS},  # .heic has no Qt reader
    **{ext: "text" for ext in _TEXT_EXTS},
    **{ext: "video" for ext in VIDEO_EXTS - {".ts"}},  # .ts: TypeScript or MPEG-TS, sniffed
    **{ext: "audio" for ext in _AUDIO_EXTS},
    ".pdf": "pdf",
    ".md": "markdown",
    ".markdown": "markdown",
}
_MARKDOWN_MAX_WIDTH = 900
_TEXT_LIMIT = 2 * 1024 * 1024
_LINE_CHUNK = 10000
_TRUNCATED_NOTE = "\n\n……（檔案超過 2 MB，只顯示開頭）"
_HINT = "↑ ↓ 上一個／下一個　　空白鍵或 Esc 關閉"
_MEDIA_HINT = "↑ ↓ 上一個／下一個　　Enter 暫停／播放　　← → 倒轉／快轉 5 秒　　空白鍵或 Esc 關閉"


def preview_kind(path: str) -> str:
    """Return "image" / "pdf" / "markdown" / "text" / "video" / "audio", or "" when the
    built-in preview can't show it."""
    return _KINDS.get(os.path.splitext(path)[1].lower(), "")


def _is_mpeg_ts(path: str) -> bool:
    """MPEG transport streams are 188-byte packets that each start with 0x47."""
    try:
        with open(path, "rb") as f:
            head = f.read(377)
    except OSError:
        return False
    return len(head) == 377 and head[0] == head[188] == head[376] == 0x47


def _read_text(path: str, limit: int = _TEXT_LIMIT) -> tuple[str, bool]:
    """Decode the first `limit` bytes; returns (text, truncated)."""
    with open(path, "rb") as f:
        data = f.read(limit + 1)
    truncated = len(data) > limit
    data = data[:limit]
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return data.decode("utf-16", errors="replace"), truncated
    try:
        # Incremental, so a cut in the middle of a character isn't taken for non-UTF-8.
        return codecs.getincrementaldecoder("utf-8-sig")().decode(data, not truncated), truncated
    except UnicodeDecodeError:
        return data.decode("cp950", errors="replace"), truncated


def _split_long_lines(text: str) -> str:
    """Laying out one huge line (minified JS / JSON) takes seconds; cut into blocks it takes
    milliseconds and, wrapped, looks the same."""
    lines = text.split("\n")
    if max(map(len, lines)) <= _LINE_CHUNK:
        return text
    return "\n".join(
        line[i : i + _LINE_CHUNK]
        for line in lines
        for i in range(0, max(len(line), 1), _LINE_CHUNK)
    )


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
        self._code = QPlainTextEdit()
        self._code.setObjectName("previewCode")
        self._code.setReadOnly(True)
        self._media = MediaView()
        self._media.failed.connect(self._on_media_failed)
        self._message = QLabel()
        self._message.setObjectName("previewTitle")
        self._message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        for w in (self._pdf, self._text, self._code):
            # Keys stay with the lightbox (Up / Down switch files); the wheel still scrolls.
            w.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._stack = QStackedWidget()
        for page in (self._image, self._pdf, text_page, self._code, self._media, self._message):
            self._stack.addWidget(page)
        self._pages = {
            "image": self._image,
            "pdf": self._pdf,
            "markdown": text_page,
            "text": self._code,
            "video": self._media,
            "audio": self._media,
        }

        self._hint = QLabel(_HINT)
        self._hint.setObjectName("previewDim")
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 12, 40, 12)
        layout.addLayout(top)
        layout.addWidget(self._stack, 1)
        layout.addWidget(self._hint)

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
        self._media.stop()
        self._pdf_doc.close()
        self._text.clear()
        self._code.clear()
        self._image.set_pixmap(QPixmap())
        kind = preview_kind(path)
        if kind == "text" and path.lower().endswith(".ts") and _is_mpeg_ts(path):
            kind = "video"
        loaders = {
            "image": self._load_image,
            "pdf": self._load_pdf,
            "markdown": self._load_markdown,
            "text": self._load_plain,
            "video": lambda p: self._load_media(p, video=True),
            "audio": lambda p: self._load_media(p, video=False),
        }
        error = loaders[kind](path)
        if error:
            self._show_message(error)
        else:
            self._stack.setCurrentWidget(self._pages[kind])
        self._hint.setText(_MEDIA_HINT if self._showing_media() else _HINT)

    def _show_message(self, text: str) -> None:
        self._message.setText(text)
        self._stack.setCurrentWidget(self._message)

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

    def _read(self, path: str) -> str | None:
        try:
            text, truncated = _read_text(path)
        except OSError as e:
            log.warning("Cannot preview %s: %s", path, e)
            return None
        return text + _TRUNCATED_NOTE if truncated else text

    def _load_markdown(self, path: str) -> str:
        text = self._read(path)
        if text is None:
            return "無法讀取這個檔案"
        # Relative image links in the Markdown resolve against the file's folder.
        self._text.document().setBaseUrl(QUrl.fromLocalFile(os.path.dirname(path) + os.sep))
        self._text.setMarkdown(text)
        return ""

    def _load_plain(self, path: str) -> str:
        text = self._read(path)
        if text is None:
            return "無法讀取這個檔案"
        self._code.setPlainText(_split_long_lines(text))
        return ""

    def _load_media(self, path: str, video: bool) -> str:
        self._media.play(path, video)
        return ""

    def _showing_media(self) -> bool:
        return self._stack.currentWidget() is self._media

    def _on_media_failed(self, message: str) -> None:
        if self._showing_media():
            self._show_message(message)
            self._hint.setText(_HINT)

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
        elif self._showing_media() and key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._media.toggle()
        elif self._showing_media() and key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            self._media.seek_by(SEEK_STEP_MS if key == Qt.Key.Key_Right else -SEEK_STEP_MS)

    def mousePressEvent(self, event):
        self.close()  # only clicks on the backdrop get here

    def paintEvent(self, _event):
        QPainter(self).fillRect(self.rect(), QColor(0, 0, 0, 215))

    def closeEvent(self, event):
        self._media.stop()
        self.parentWidget().removeEventFilter(self)
        self.closed.emit()
        super().closeEvent(event)
