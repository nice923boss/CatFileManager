import os
import re
import types

import pytest
from conftest import make_junction

from search_engine import SearchWorker, _needles, file_contains
from search_utils import SearchHistory, make_matcher


def test_matcher_empty_text_means_no_filter():
    assert make_matcher("   ", regex=False) is None


def test_matcher_substring_is_case_insensitive():
    m = make_matcher("Report", regex=False)
    assert m("monthly_REPORT.xlsx")
    assert not m("summary.xlsx")


def test_matcher_wildcard_matches_whole_name():
    m = make_matcher("*.jpg", regex=False)
    assert m("a.JPG")
    assert not m("a.jpg.bak")


def test_matcher_regex_and_invalid_regex():
    assert make_matcher(r"^img_\d+", regex=True)("IMG_001.png")
    with pytest.raises(re.error):
        make_matcher("(", regex=True)


def test_history_most_recent_first_without_duplicates(qapp):
    h = SearchHistory()
    emitted = []
    h.changed.connect(emitted.append)
    for text in ("a", "b", "a", "  "):
        h.add(text)
    assert h.items() == ["a", "b"]
    h.remove("a")
    assert h.items() == ["b"]
    h.clear()
    assert h.items() == [] and emitted[-1] == []


def test_history_limit(qapp):
    h = SearchHistory()
    h.load([str(i) for i in range(50)])
    assert len(h.items()) == SearchHistory.LIMIT


def test_file_contains_utf8_cp950_and_case(tmp_path):
    utf8 = tmp_path / "u.txt"
    utf8.write_text("Hello 貓咪 World", encoding="utf-8")
    big5 = tmp_path / "b.txt"
    big5.write_bytes("報價單 貓咪".encode("cp950"))
    assert file_contains(str(utf8), _needles("world"))
    assert file_contains(str(utf8), _needles("貓咪"))
    assert file_contains(str(big5), _needles("貓咪"))
    assert not file_contains(str(utf8), _needles("dog"))


def test_file_contains_across_chunk_boundary(tmp_path, monkeypatch):
    import search_engine

    monkeypatch.setattr(search_engine, "_CHUNK", 8)
    p = tmp_path / "x.txt"
    p.write_bytes(b"0123456needle89")
    assert file_contains(str(p), _needles("needle"))


def _run(mode, root, text, regex=False):
    worker = SearchWorker(mode, str(root), text, regex)
    hits, done = [], []
    worker.found.connect(hits.extend)
    worker.done.connect(lambda err, limited: done.append((err, limited)))
    worker.run()  # synchronous on purpose
    return sorted(os.path.basename(h.path) for h in hits), done


def test_worker_name_search_is_recursive(qapp, tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.jpg").write_text("")
    (tmp_path / "sub" / "b.JPG").write_text("")
    (tmp_path / "c.png").write_text("")
    names, done = _run("name", tmp_path, "*.jpg")
    assert names == ["a.jpg", "b.JPG"]
    assert done == [("", False)]


def test_worker_content_search(qapp, tmp_path):
    (tmp_path / "yes.txt").write_text("the secret word", encoding="utf-8")
    (tmp_path / "no.txt").write_text("nothing", encoding="utf-8")
    names, _ = _run("content", tmp_path, "SECRET")
    assert names == ["yes.txt"]


def test_worker_does_not_follow_junctions(qapp, tmp_path):
    target = tmp_path / "real"
    target.mkdir()
    (target / "hit.txt").write_text("")
    make_junction(tmp_path / "link", target)
    names, _ = _run("name", tmp_path, "hit")
    assert names == ["hit.txt"]  # found once, not again through the junction


def _fake_es(monkeypatch, codes, hit_paths=()):
    """Stand in for es.exe: return `codes` in turn, export `hit_paths` on success."""
    import search_engine

    calls = []

    def run(args, **_kwargs):
        calls.append(args)
        code = codes[len(calls) - 1]
        if code == 0:
            out = args[args.index("-export-txt") + 1]
            with open(out, "w", encoding="utf-8-sig") as f:
                f.write("".join(f"{p}\n" for p in hit_paths))
        return types.SimpleNamespace(returncode=code)

    monkeypatch.setattr(search_engine, "find_es_exe", lambda _override="": "es.exe")
    monkeypatch.setattr(search_engine.subprocess, "run", run)
    return calls


def test_everything_retries_alpha_instance(qapp, tmp_path, monkeypatch):
    (tmp_path / "報告.txt").write_text("")
    calls = _fake_es(monkeypatch, [8, 0], [tmp_path / "報告.txt"])
    names, done = _run("everything", "", "報告")
    assert names == ["報告.txt"] and done == [("", False)]
    assert "-instance" not in calls[0] and calls[1][1:3] == ["-instance", "1.5a"]


def test_everything_not_running_offers_install(qapp, monkeypatch):
    _fake_es(monkeypatch, [8, 8])
    worker = SearchWorker("everything", "", "x", False)
    errors = []
    worker.done.connect(lambda err, _limited: errors.append(err))
    worker.run()
    assert "沒有在執行" in errors[0] and worker.needs_install


def test_everything_missing_es_offers_install(qapp, monkeypatch):
    import search_engine

    monkeypatch.setattr(search_engine, "find_es_exe", lambda _override="": "")
    worker = SearchWorker("everything", "", "x", False)
    worker.run()
    assert worker.needs_install


def test_find_es_exe_sees_winget_package(tmp_path, monkeypatch):
    import search_engine

    pkg = tmp_path / "Microsoft" / "WinGet" / "Packages" / "voidtools.Everything.Cli_abc"
    pkg.mkdir(parents=True)
    (pkg / "es.exe").write_bytes(b"")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(search_engine.shutil, "which", lambda _name: None)
    assert search_engine.find_es_exe() == str(pkg / "es.exe")


def test_install_script_is_bundled_with_bom():
    import search_engine

    with open(search_engine.INSTALL_SCRIPT, "rb") as f:
        assert f.read(3) == b"\xef\xbb\xbf"  # Windows PowerShell 5.1 reads BOM-less as ANSI
    spec = os.path.join(os.path.dirname(search_engine.INSTALL_SCRIPT), "CatFileManager.spec")
    with open(spec, encoding="utf-8") as f:
        assert "('install_everything.ps1', '.')" in f.read()


def test_results_dialog_offers_install_and_retry(qapp, monkeypatch):
    from PySide6.QtWidgets import QWidget

    import search_dialog
    import search_engine

    monkeypatch.setattr(search_engine, "find_es_exe", lambda _override="": "")
    launched = []
    monkeypatch.setattr(search_dialog, "run_install_script", lambda: launched.append(True))

    def finish(dlg):
        dlg._worker.wait()
        qapp.processEvents()  # deliver the queued done signal

    dlg = search_dialog.SearchResultsDialog(QWidget(), "everything", "", "x", False)
    finish(dlg)
    assert not dlg.install_btn.isHidden() and not dlg.retry_btn.isHidden()
    dlg.install_btn.click()
    assert launched and "重新搜尋" in dlg.status.text()

    first = dlg._worker
    dlg.retry_btn.click()
    assert dlg._worker is not first and dlg.install_btn.isHidden()
    finish(dlg)
    assert not dlg.install_btn.isHidden()
    dlg.close()
