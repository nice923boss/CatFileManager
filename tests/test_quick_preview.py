"""Space-bar lightbox preview for images, PDF, Markdown, text, video and audio."""

import os
import wave

from PySide6.QtCore import QCoreApplication, QElapsedTimer, QEvent, QPoint, Qt
from PySide6.QtGui import QColor, QImage, QKeyEvent, QPainter, QPdfWriter
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtPdf import QPdfDocument
from PySide6.QtTest import QTest

import panels
from panels import FilePanel
from quick_preview import QuickPreview, _is_mpeg_ts, _read_text, _split_long_lines, preview_kind


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
    (tmp_path / "g.docx").write_bytes(b"PK office")
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
    assert preview_kind("notes.txt") == "text"
    assert preview_kind("app.py") == "text"
    assert preview_kind("index.ts") == "text"  # MPEG-TS is sniffed when loading
    assert preview_kind("Clip.MKV") == "video"
    assert preview_kind("song.mp3") == "audio"
    assert preview_kind("report.docx") == ""  # Office stays with QuickLook
    assert preview_kind("phone.heic") == ""  # Qt has no reader; QuickLook handles it


def test_space_opens_lightbox_and_arrows_step_through_files(qapp, tmp_path):
    panel = _panel(_sample_folder(tmp_path))
    preview = _start(panel, "a.png")
    assert preview is not None
    assert _names(preview) == ["a.png", "b.txt", "c.md", "d.pdf"]
    assert preview._stack.currentWidget() is preview._image
    assert not preview._image.pixmap().isNull()
    assert preview._counter.text() == "1 / 4"

    QTest.keyClick(preview, Qt.Key.Key_Down)
    assert preview._stack.currentWidget() is preview._code
    assert preview._code.toPlainText() == "plain"

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
    assert preview._counter.text() == "3 / 4"


def test_order_follows_panel_sort_and_filter(qapp, tmp_path):
    panel = _panel(_sample_folder(tmp_path))
    panel.tree.sortByColumn(0, Qt.SortOrder.DescendingOrder)
    panel._apply_filter(lambda name: name != "c.md")
    preview = _start(panel, "d.pdf")
    assert _names(preview) == ["d.pdf", "b.txt", "a.png"]


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
    assert _start(panel, "g.docx") is None
    assert messages and "QuickLook" in messages[-1]


def _wait(condition, ms: int = 5000) -> bool:
    timer = QElapsedTimer()
    timer.start()
    while not condition() and timer.elapsed() < ms:
        QTest.qWait(20)
    return condition()


def _write_silent_wav(path, seconds: int = 12) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\0\0" * 8000 * seconds)


def test_read_text_encodings_and_truncation(tmp_path):
    path = tmp_path / "t.txt"
    path.write_bytes("記事".encode("utf-16"))  # with BOM, as Notepad's "Unicode"
    assert _read_text(str(path)) == ("記事", False)
    path.write_bytes("繁體".encode("cp950"))
    assert _read_text(str(path)) == ("繁體", False)
    path.write_bytes("中文字".encode())  # 9 bytes; a cut after 4 splits the second character
    assert _read_text(str(path), limit=4) == ("中", True)


def test_huge_lines_are_cut_into_blocks():
    text = "a" * 25000 + "\n\nb"
    assert [len(line) for line in _split_long_lines(text).split("\n")] == [10000, 10000, 5000, 0, 1]
    assert _split_long_lines("short\nlines") == "short\nlines"


def test_mpeg_ts_is_told_apart_from_typescript(tmp_path):
    video = tmp_path / "clip.ts"
    video.write_bytes((b"\x47" + b"\0" * 187) * 3)
    code = tmp_path / "app.ts"
    code.write_text("export const x = 1;\n" * 30)
    assert _is_mpeg_ts(str(video))
    assert not _is_mpeg_ts(str(code))
    preview = _start(_panel(tmp_path), "app.ts")
    assert preview._stack.currentWidget() is preview._code


def test_audio_plays_and_keys_control_it(qapp, tmp_path):
    _write_silent_wav(tmp_path / "tone.wav")
    preview = _start(_panel(tmp_path), "tone.wav")
    player = preview._media.player()
    assert preview._stack.currentWidget() is preview._media
    assert "Enter" in preview._hint.text()
    assert _wait(lambda: player.playbackState() == QMediaPlayer.PlaybackState.PlayingState)
    assert _wait(lambda: player.duration() > 0)

    QTest.keyClick(preview, Qt.Key.Key_Return)
    assert player.playbackState() == QMediaPlayer.PlaybackState.PausedState
    start = player.position()
    QTest.keyClick(preview, Qt.Key.Key_Right)
    assert _wait(lambda: player.position() >= start + 4000)
    QTest.keyClick(preview, Qt.Key.Key_Left)
    assert _wait(lambda: player.position() < start + 1000)
    QTest.keyClick(preview, Qt.Key.Key_Enter)
    assert player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    QTest.keyClick(preview, Qt.Key.Key_Right)
    # Closing right after a seek used to deadlock Qt's player; Space still closes and
    # lets go of the file.
    QTest.keyClick(preview, Qt.Key.Key_Space)
    assert player.source().isEmpty()
    os.remove(tmp_path / "tone.wav")


def test_unplayable_media_shows_message(qapp, tmp_path):
    (tmp_path / "broken.mp4").write_bytes(b"not a video" * 100)
    preview = _start(_panel(tmp_path), "broken.mp4")
    assert _wait(lambda: preview._stack.currentWidget() is preview._message)
    assert preview._message.text() == "無法播放這個檔案"
    assert "Enter" not in preview._hint.text()
