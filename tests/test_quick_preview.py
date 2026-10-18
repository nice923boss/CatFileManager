"""Space-bar lightbox preview for images, PDF and Markdown."""

import os

from PySide6.QtCore import QCoreApplication, QElapsedTimer, QEvent, QPoint, Qt
from PySide6.QtGui import QColor, QImage, QKeyEvent, QPainter, QPdfWriter
from PySide6.QtPdf import QPdfDocument
from PySide6.QtTest import QTest

import panels
from panels import FilePanel
from quick_preview import QuickPreview, preview_kind


def _write_pdf(path) -> None:
    writer = QPdfWriter(str(path))
    painter = QPainter(writer)
    painter.drawText(100, 100, "page one")
    painter.end()


def _sample_folder(tmp_path):
    image = QImage(40, 30, QImage.Format.Format_RGB32)
    image.fill(QColor("red"))
    image.save(str(tmp_path / "a.png"))
    (tmp_path / "b.txt").write_text("plain")
    (tmp_path / "c.md").write_text("# 標題\n\n內文", encoding="utf-8")
    _write_pdf(tmp_path / "d.pdf")
    (tmp_path / "e.png").mkdir()  # a folder named like an image is skipped
    (tmp_path / "f.heic").write_bytes(b"no Qt reader")
    return tmp_path


def _panel(folder) -> FilePanel:
    panel = FilePanel(0, None)
    panel.resize(900, 700)
    panel.show()  # stands in for the main window the lightbox covers
    panel.tree.sortByColumn(0, Qt.SortOrder.AscendingOrder)
    panel.navigate_to(str(folder))
    timer = QElapsedTimer()
    timer.start()
    while panel.model.is_loading() and timer.elapsed() < 5000:
        QCoreApplication.processEvents()
    return panel


def _start(panel, name) -> QuickPreview | None:
    panel._select_path(os.path.join(panel.current_path(), name))
    panel.run_action("preview")
    return next((w for w in panel.findChildren(QuickPreview) if w.isVisible()), None)


def _names(preview) -> list[str]:
    return [os.path.basename(p) for p in preview._paths]


def test_preview_kind():
    assert preview_kind(r"C:\x\Photo.JPG") == "image"
    assert preview_kind("doc.pdf") == "pdf"
    assert preview_kind("README.md") == "markdown"
    assert preview_kind("notes.txt") == ""
    assert preview_kind("phone.heic") == ""  # Qt has no reader; QuickLook handles it


def test_space_opens_lightbox_and_arrows_step_through_files(qapp, tmp_path):
    panel = _panel(_sample_folder(tmp_path))
    preview = _start(panel, "a.png")
    assert preview is not None
    assert _names(preview) == ["a.png", "c.md", "d.pdf"]
    assert preview._stack.currentWidget() is preview._image
    assert not preview._image.pixmap().isNull()
    assert preview._counter.text() == "1 / 3"

    QTest.keyClick(preview, Qt.Key.Key_Down)
    assert os.path.basename(preview.current_path()) == "c.md"
    assert panel._get_selected_paths() == [str(tmp_path / "c.md")]  # list follows the preview
    assert "標題" in preview._text.toPlainText()

    QTest.keyClick(preview, Qt.Key.Key_Down)
    assert os.path.basename(preview.current_path()) == "d.pdf"
    assert preview._pdf_doc.status() == QPdfDocument.Status.Ready
    assert preview._pdf_doc.pageCount() == 1

    QTest.keyClick(preview, Qt.Key.Key_Down)  # last file: stays
    assert os.path.basename(preview.current_path()) == "d.pdf"
    QTest.keyClick(preview, Qt.Key.Key_Up)
    assert os.path.basename(preview.current_path()) == "c.md"
    assert preview._counter.text() == "2 / 3"


def test_order_follows_panel_sort_and_filter(qapp, tmp_path):
    panel = _panel(_sample_folder(tmp_path))
    panel.tree.sortByColumn(0, Qt.SortOrder.DescendingOrder)
    panel._apply_filter(lambda name: name != "c.md")
    preview = _start(panel, "d.pdf")
    assert _names(preview) == ["d.pdf", "a.png"]


def test_escape_space_and_backdrop_click_close(qapp, tmp_path):
    panel = _panel(_sample_folder(tmp_path))
    for close in (
        lambda p: QTest.keyClick(p, Qt.Key.Key_Escape),
        lambda p: QTest.keyClick(p, Qt.Key.Key_Space),
        lambda p: QTest.mouseClick(p, Qt.MouseButton.LeftButton, pos=QPoint(5, 5)),
    ):
        preview = _start(panel, "a.png")
        closed = []
        preview.closed.connect(lambda closed=closed: closed.append(True))
        close(preview)
        assert closed == [True]
        assert not preview.isVisible()


def test_shortcuts_behind_lightbox_are_blocked(qapp, tmp_path):
    panel = _panel(_sample_folder(tmp_path))
    preview = _start(panel, "a.png")
    for key in (Qt.Key.Key_Delete, Qt.Key.Key_Tab, Qt.Key.Key_F2):
        event = QKeyEvent(QEvent.Type.ShortcutOverride, key, Qt.KeyboardModifier.NoModifier)
        event.ignore()
        QCoreApplication.sendEvent(preview, event)
        assert event.isAccepted(), key


def test_unreadable_image_shows_message(qapp, tmp_path):
    (tmp_path / "broken.png").write_bytes(b"not a png")
    preview = _start(_panel(tmp_path), "broken.png")
    assert preview._stack.currentWidget() is preview._message
    assert preview._message.text() == "無法讀取這張圖片"


def test_other_types_still_use_quicklook(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(panels, "_quicklook_exe", lambda: "")
    panel = _panel(_sample_folder(tmp_path))
    messages = []
    panel.status_message.connect(messages.append)
    assert _start(panel, "b.txt") is None
    assert messages and "QuickLook" in messages[-1]
