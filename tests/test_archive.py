import io
import os
import tarfile

from file_operations import ZipCompressWorker
from panel_actions import FilePanelActionsMixin


class _Messages:
    def __init__(self):
        self.items: list[str] = []

    def emit(self, text: str) -> None:
        self.items.append(text)


class _Panel(FilePanelActionsMixin):
    """Just enough of FilePanel to call _extract_archive."""

    def __init__(self):
        self.status_message = _Messages()

    def _refresh(self):
        pass


def _zip(sources, zip_path, cancel=False):
    worker = ZipCompressWorker([str(s) for s in sources], str(zip_path))
    done, errors = [], []
    worker.finished.connect(done.append)
    worker.error.connect(errors.append)
    if cancel:
        worker.cancel()
    worker.run()  # synchronous on purpose
    return done, errors


def test_zip_then_extract_round_trip(qapp, tmp_path):
    src = tmp_path / "資料"
    (src / "sub").mkdir(parents=True)
    (src / "sub" / "報價單.txt").write_text("貓咪", encoding="utf-8")
    single = tmp_path / "one.txt"
    single.write_text("1", encoding="utf-8")
    archive = tmp_path / "pack.zip"

    done, errors = _zip([src, single], archive)
    assert errors == [] and "完成" in done[0]

    panel = _Panel()
    panel._extract_archive([str(archive)])
    out = tmp_path / "pack"
    assert (out / "資料" / "sub" / "報價單.txt").read_text(encoding="utf-8") == "貓咪"
    assert (out / "one.txt").read_text(encoding="utf-8") == "1"
    assert "解壓縮完成：1" in panel.status_message.items[-1]


def test_extract_picks_new_folder_name_when_taken(qapp, tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x")
    archive = tmp_path / "pack.zip"
    _zip([f], archive)
    (tmp_path / "pack").mkdir()
    _Panel()._extract_archive([str(archive)])
    assert (tmp_path / "pack (1)" / "a.txt").exists()


def test_cancelled_zip_leaves_no_file(qapp, tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x")
    archive = tmp_path / "pack.zip"
    done, _ = _zip([f], archive, cancel=True)
    assert "取消" in done[0]
    assert not archive.exists()


def test_extract_tar_blocks_path_traversal(qapp, tmp_path):
    archive = tmp_path / "evil.tar"
    with tarfile.open(archive, "w") as tf:
        data = b"pwned"
        info = tarfile.TarInfo("../escaped.txt")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))

    panel = _Panel()
    panel._extract_archive([str(archive)])
    assert not (tmp_path / "escaped.txt").exists()
    assert "失敗 1" in panel.status_message.items[-1]


def test_extract_reports_bad_zip(qapp, tmp_path):
    bad = tmp_path / "broken.zip"
    bad.write_bytes(b"not a zip")
    panel = _Panel()
    panel._extract_archive([str(bad)])
    assert "不是有效的 ZIP 檔" in panel.status_message.items[-1]
    assert not os.path.exists(tmp_path / "broken")
