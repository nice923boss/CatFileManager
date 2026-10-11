"""TransferWorker: conflicts, merge, move, verify, cancel, long paths, links."""

import os

from conftest import make_junction

from copy_engine import OVERWRITE, RENAME, SKIP, TransferWorker, unique_name
from long_path import lp


def _run(op, sources, dest, answer=None, apply_all=False, verify=False):
    worker = TransferWorker(op, [str(s) for s in sources], str(dest), verify=verify)
    asked = []
    results = []

    def on_conflict(src, dst, *_):
        asked.append((os.path.basename(src), os.path.basename(dst)))
        worker.resolve_conflict(answer, apply_all)

    worker.conflict.connect(on_conflict)
    worker.done.connect(results.append)
    worker.run()  # synchronous: signals go to the slots directly
    return results[0], asked


def test_copy_file_and_folder(qapp, tmp_path):
    src = tmp_path / "src"
    (src / "sub").mkdir(parents=True)
    (src / "sub" / "b.txt").write_text("bbb")
    (tmp_path / "a.txt").write_text("aaa")
    dest = tmp_path / "dest"
    dest.mkdir()

    result, asked = _run("copy", [tmp_path / "a.txt", src], dest)
    assert not result.errors and not asked
    assert (dest / "a.txt").read_text() == "aaa"
    assert (dest / "src" / "sub" / "b.txt").read_text() == "bbb"
    assert ("created", str(dest / "src")) in result.records
    assert not list(dest.rglob("*.catfm-part"))


def test_conflict_choices(qapp, tmp_path):
    (tmp_path / "a.txt").write_text("new")
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "a.txt").write_text("old")

    _, asked = _run("copy", [tmp_path / "a.txt"], dest, SKIP)
    assert asked == [("a.txt", "a.txt")] and (dest / "a.txt").read_text() == "old"

    _run("copy", [tmp_path / "a.txt"], dest, RENAME)
    assert (dest / "a (1).txt").read_text() == "new"

    result, _ = _run("copy", [tmp_path / "a.txt"], dest, OVERWRITE)
    assert (dest / "a.txt").read_text() == "new"
    assert not result.undo_complete


def test_apply_all_asks_once(qapp, tmp_path):
    dest = tmp_path / "dest"
    dest.mkdir()
    files = []
    for n in "xyz":
        (tmp_path / f"{n}.txt").write_text("new")
        (dest / f"{n}.txt").write_text("old")
        files.append(tmp_path / f"{n}.txt")
    _, asked = _run("copy", files, dest, SKIP, apply_all=True)
    assert len(asked) == 1


def test_merge_folder_on_overwrite(qapp, tmp_path):
    src = tmp_path / "f"
    src.mkdir()
    (src / "one.txt").write_text("1")
    dest = tmp_path / "dest"
    (dest / "f").mkdir(parents=True)
    (dest / "f" / "keep.txt").write_text("k")
    _run("copy", [src], dest, OVERWRITE)
    assert sorted(p.name for p in (dest / "f").iterdir()) == ["keep.txt", "one.txt"]


def test_same_folder_copy_makes_numbered_duplicate(qapp, tmp_path):
    (tmp_path / "a.txt").write_text("a")
    result, asked = _run("copy", [tmp_path / "a.txt"], tmp_path)
    assert not asked and (tmp_path / "a (1).txt").exists()
    assert unique_name(str(tmp_path / "a.txt")).endswith("a (2).txt")


def test_move_same_drive_records_undo(qapp, tmp_path):
    (tmp_path / "m.txt").write_text("m")
    dest = tmp_path / "dest"
    dest.mkdir()
    result, _ = _run("move", [tmp_path / "m.txt"], dest)
    assert not (tmp_path / "m.txt").exists() and (dest / "m.txt").exists()
    assert result.records == [("moved", str(tmp_path / "m.txt"), str(dest / "m.txt"))]


def test_refuses_copy_into_own_subfolder(qapp, tmp_path):
    src = tmp_path / "p"
    (src / "c").mkdir(parents=True)
    result, _ = _run("copy", [src], src / "c")
    assert result.errors and "子資料夾" in result.errors[0]


def test_verify_passes_with_hash(qapp, tmp_path):
    (tmp_path / "big.bin").write_bytes(os.urandom(3 * 1024 * 1024 + 7))
    dest = tmp_path / "dest"
    dest.mkdir()
    result, _ = _run("copy", [tmp_path / "big.bin"], dest, verify=True)
    assert not result.errors
    assert (dest / "big.bin").read_bytes() == (tmp_path / "big.bin").read_bytes()


def test_cancel_mid_file_leaves_no_partial_file(qapp, tmp_path):
    (tmp_path / "big.bin").write_bytes(os.urandom(4 * 1024 * 1024))
    dest = tmp_path / "dest"
    dest.mkdir()
    worker = TransferWorker("copy", [str(tmp_path / "big.bin")], str(dest))
    results = []
    original_emit = worker._emit

    def emit_then_cancel(name, force=False):
        original_emit(name, force)
        if worker._bytes_done > 0:  # first chunk written, file is half-copied
            worker.cancel()

    worker._emit = emit_then_cancel
    worker.done.connect(results.append)
    worker.run()
    assert results[0].cancelled
    assert list(dest.iterdir()) == []


def test_long_path_copy(qapp, tmp_path):
    deep = str(tmp_path)
    while len(deep) < 300:
        deep = os.path.join(deep, "d" * 40)
    os.makedirs(lp(deep))
    with open(lp(os.path.join(deep, "f.txt")), "w") as f:
        f.write("deep")
    dest = tmp_path / "dest"
    dest.mkdir()
    first = os.path.join(str(tmp_path), "d" * 40)
    result, _ = _run("copy", [first], dest)
    assert not result.errors
    copied = [os.path.join(r, n) for r, _, files in os.walk(lp(str(dest))) for n in files]
    assert len(copied) == 1


def test_nested_junction_recreated_not_followed(qapp, tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    (target / "t.txt").write_text("t")
    src = tmp_path / "src"
    src.mkdir()
    make_junction(src / "link", target)
    dest = tmp_path / "dest"
    dest.mkdir()
    result, _ = _run("copy", [src], dest)
    assert not result.errors
    assert os.path.isjunction(dest / "src" / "link")
    assert os.path.realpath(dest / "src" / "link") == os.path.realpath(target)
