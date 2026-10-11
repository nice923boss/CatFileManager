import os
import re
import time

import pytest

from batch_rename import (
    BatchRenameDialog,
    build_rename_pairs,
    build_transform_pairs,
    change_case,
    date_prefix,
    execute_batch_rename,
    replace_text,
)
from undo import UndoStack


def _touch(folder, *names):
    paths = []
    for n in names:
        p = os.path.join(folder, n)
        open(p, "w").close()
        paths.append(p)
    return paths


def test_replace_plain_text_ignores_regex_syntax():
    assert replace_text("a.b.c", ".", "-", regex=False, ignore_case=False) == "a-b-c"
    assert replace_text("x", "x", r"\1", regex=False, ignore_case=False) == r"\1"


def test_replace_regex_with_groups_and_ignore_case():
    assert replace_text("IMG_0012", r"img_(\d+)", r"photo-\1", True, True) == "photo-0012"
    assert replace_text("IMG_0012", r"img_(\d+)", r"photo-\1", True, False) == "IMG_0012"


def test_replace_invalid_regex_raises():
    with pytest.raises(re.error):
        replace_text("abc", "(", "", regex=True, ignore_case=False)


def test_change_case_modes():
    assert change_case("my File", "upper") == "MY FILE"
    assert change_case("my File", "lower") == "my file"
    assert change_case("my file", "title") == "My File"


def test_date_prefix_uses_format():
    ts = time.mktime((2026, 10, 11, 15, 30, 0, 0, 0, -1))
    assert date_prefix("report", ts, "%Y%m%d_") == "20261011_report"


def test_transform_keeps_extension_and_folder_names(tmp_path):
    (f,) = _touch(tmp_path, "a.tar.gz")
    d = tmp_path / "dir.v2"
    d.mkdir()
    pairs = build_transform_pairs([f, str(d)], lambda stem, _p, _i: stem.upper())
    assert os.path.basename(pairs[0][1]) == "A.TAR.gz"
    assert os.path.basename(pairs[1][1]) == "DIR.V2"


def test_sequence_pairs(tmp_path):
    paths = _touch(tmp_path, "x.jpg", "y.png")
    names = [os.path.basename(d) for _, d in build_rename_pairs(paths, "trip", 1, 2)]
    assert names == ["trip_01.jpg", "trip_02.png"]


def test_case_only_rename_and_undo(tmp_path):
    (src,) = _touch(tmp_path, "abc.txt")
    dst = os.path.join(tmp_path, "ABC.txt")
    assert execute_batch_rename([(src, dst)]) == (1, [])
    assert os.listdir(tmp_path) == ["ABC.txt"]

    stack = UndoStack()
    stack.push("rename", [("renamed", src, dst)])
    _label, errors = stack.undo()
    assert errors == []
    assert os.listdir(tmp_path) == ["abc.txt"]


def test_dialog_only_returns_changed_items(qapp, tmp_path):
    paths = _touch(tmp_path, "IMG_1.jpg", "notes.txt")
    dlg = BatchRenameDialog(paths)
    dlg._mode.setCurrentIndex(1)
    dlg._find_edit.setText("IMG_")
    dlg._repl_edit.setText("photo_")
    assert [os.path.basename(d) for _, d in dlg.rename_pairs()] == ["photo_1.jpg"]
    assert dlg._hint.text() == ""


def test_dialog_blocks_duplicate_targets(qapp, tmp_path):
    paths = _touch(tmp_path, "a1.txt", "a2.txt")
    dlg = BatchRenameDialog(paths)
    dlg._mode.setCurrentIndex(1)
    dlg._regex_box.setChecked(True)
    dlg._find_edit.setText(r"\d")
    assert "同一個名稱" in dlg._hint.text()
