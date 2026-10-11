"""DirectoryModel: hidden filter, extensions, link kinds, colours, icons."""

import os
import shutil

from conftest import make_junction, set_hidden
from PySide6.QtCore import QCoreApplication, QElapsedTimer, Qt

import file_model
from file_model import DirectoryModel, _ScanWorker, _type_label


def _scan(path, show_hidden=False):
    worker = _ScanWorker(str(path), show_hidden)
    result = []
    worker.done.connect(result.extend)
    worker.run()  # synchronous for the test
    return {e.name: e for e in result}


def _wait(model, qapp, ms=5000):
    timer = QElapsedTimer()
    timer.start()
    while model.is_loading() and timer.elapsed() < ms:
        QCoreApplication.processEvents()


def test_hidden_files_filtered_and_flagged(qapp, tmp_path):
    (tmp_path / "shown.txt").write_text("a")
    secret = tmp_path / "secret.txt"
    secret.write_text("b")
    set_hidden(secret)

    assert set(_scan(tmp_path)) == {"shown.txt"}
    both = _scan(tmp_path, show_hidden=True)
    assert both["secret.txt"].hidden and not both["shown.txt"].hidden


def test_junction_and_broken_link(qapp, tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    gone = tmp_path / "gone"
    gone.mkdir()
    make_junction(tmp_path / "j_ok", real)
    make_junction(tmp_path / "j_bad", gone)
    shutil.rmtree(gone)

    entries = _scan(tmp_path)
    ok, bad = entries["j_ok"], entries["j_bad"]
    assert ok.is_dir and ok.link_kind == "junction" and not ok.broken
    assert bad.is_dir and bad.broken
    assert _type_label(ok) == "Junction"
    assert _type_label(bad) == "失效連結"
    assert _type_label(entries["real"]) == "資料夾"


def test_tooltip_shows_link_target(qapp, tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    make_junction(tmp_path / "link", real)
    entry = _scan(tmp_path)["link"]
    tip = file_model._link_tooltip(entry)
    assert tip == f"→ {os.path.realpath(real)}"
    assert file_model._link_tooltip(_scan(tmp_path)["real"]) is None


def test_display_name_respects_extension_toggle(qapp):
    model = DirectoryModel()
    f = file_model.FileEntry("photo.jpg", r"C:\photo.jpg", False, 1, 0, ".jpg")
    d = file_model.FileEntry("v1.2", r"C:\v1.2", True, 0, 0, "")
    lnk = file_model.FileEntry("App.lnk", r"C:\App.lnk", False, 1, 0, ".lnk")
    assert model.display_name(f) == "photo.jpg"
    assert model.display_name(lnk) == "App"
    model.set_view_options(False, False, None)
    assert model.display_name(f) == "photo"
    assert model.display_name(d) == "v1.2"  # folders keep dots
    assert model.display_name(lnk) == "App"


def test_type_colours_and_hidden_alpha(qapp):
    model = DirectoryModel()
    model.set_view_options(False, True, {"image": "#00ff00", "broken": "#ff0000"}, "#cccccc")
    img = file_model.FileEntry("a.png", r"C:\a.png", False, 1, 0, ".png")
    txt = file_model.FileEntry("a.txt", r"C:\a.txt", False, 1, 0, ".txt", hidden=True)
    assert model._foreground(img).name() == "#00ff00"
    hidden = model._foreground(txt)
    assert hidden.alpha() == 120 and hidden.name() == "#cccccc"
    model.set_view_options(False, True, None)
    assert model._foreground(img) is None


def test_chinese_headers(qapp):
    model = DirectoryModel()
    headers = [model.headerData(i, Qt.Orientation.Horizontal) for i in range(4)]
    assert headers == ["名稱", "大小", "類型", "修改日期"]


def test_model_scans_sorted_in_background(qapp, tmp_path):
    for name in ["10.txt", "2.txt", "1.txt"]:
        (tmp_path / name).write_text("x")
    model = DirectoryModel()
    model.set_root_path(str(tmp_path))
    _wait(model, qapp)
    names = [model.file_name(model.index(r, 0)) for r in range(model.rowCount())]
    assert names == ["1.txt", "2.txt", "10.txt"]
    assert model.row_of(str(tmp_path / "10.txt")) == 2


def test_root_missing_signal(qapp, tmp_path):
    folder = tmp_path / "usb"
    folder.mkdir()
    model = DirectoryModel()
    model.set_root_path(str(folder))
    _wait(model, qapp)
    missing = []
    model.root_missing.connect(missing.append)
    folder.rmdir()
    model.refresh()
    assert missing == [os.path.normpath(str(folder))]


def test_shell_image_keeps_alpha(qapp):
    from icon_loader import _ole32, shell_image

    # The app only calls this on the loader thread, which initializes COM itself.
    _ole32.CoInitializeEx(None, 2)  # COINIT_APARTMENTTHREADED
    img = shell_image(r"C:\Windows\explorer.exe", 48, True)
    assert img is not None and img.width() == 48
    assert img.hasAlphaChannel()
    assert img.pixelColor(0, 0).alpha() < 255  # icon corner is transparent
