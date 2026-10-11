import os
import re

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
